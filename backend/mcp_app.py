"""HTTP MCP 서버 — 배포 서버가 /mcp 로 함께 제공한다.

사용자는 설치 없이 명령 한 줄로 등록한다:
  claude mcp add --transport http olgae-planner https://<호스트>/mcp -H "Authorization: Bearer <세션토큰>"

인증은 요청마다 Authorization 헤더로 한다. API 토큰은 원문, OAuth 토큰은 해시로 저장하며,
권한 판정은 main.py 의 기존 핸들러(opt_user / check_access / check_owner)를 그대로 재사용한다.
"""

import json
import os
import secrets
import time
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthClientInformationFull,
    OAuthToken,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

import main


ACCESS_TTL = 3600
REFRESH_TTL = 30 * 24 * 3600
OAUTH_META = {"securitySchemes": [{"type": "oauth2", "scopes": [main.OAUTH_SCOPE]}]}


def _safe_redirect(uri: str) -> bool:
    parsed = urlparse(uri)
    return (parsed.scheme == "https" or
            (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})) \
        and bool(parsed.netloc) and not parsed.fragment and not parsed.username and not parsed.password


class OAuthProvider:
    """PostgreSQL-backed opaque OAuth tokens; raw tokens are never stored."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT client_info FROM oauth_clients WHERE client_id = %s", (client_id,))
            row = cur.fetchone()
        return OAuthClientInformationFull.model_validate(row[0]) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirects = [str(uri) for uri in (client_info.redirect_uris or [])]
        if client_info.token_endpoint_auth_method != "none":
            raise RegistrationError("invalid_client_metadata", "PKCE public clients only")
        if not redirects or len(redirects) > 10 or any(not _safe_redirect(uri) for uri in redirects):
            raise RegistrationError("invalid_redirect_uri", "Only HTTPS redirect URIs are allowed")
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oauth_clients (client_id, client_info) VALUES (%s, %s)
                           ON CONFLICT (client_id) DO UPDATE SET client_info = excluded.client_info""",
                        (client_info.client_id, json.dumps(client_info.model_dump(mode="json"))))

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        scopes = params.scopes or [main.OAUTH_SCOPE]
        if params.resource != main.OAUTH_RESOURCE:
            raise AuthorizeError("invalid_target", "The resource does not match this MCP server")
        if set(scopes) != {main.OAUTH_SCOPE}:
            raise AuthorizeError("invalid_scope", "Only the mcp scope is supported")
        raw = secrets.token_urlsafe(32)
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oauth_requests
                           (request_hash, client_id, state, scopes, code_challenge, redirect_uri,
                            redirect_uri_provided_explicitly, resource, expires_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + interval '10 minutes')""",
                        (main.token_hash(raw), client.client_id, params.state, json.dumps(scopes),
                         params.code_challenge, str(params.redirect_uri),
                         params.redirect_uri_provided_explicitly, params.resource))
        return main.PUBLIC_URL + "/oauth/login?" + urlencode({"request": raw})

    async def pending_info(self, request_id: str) -> dict | None:
        if not request_id:
            return None
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT coalesce(c.client_info->>'client_name', 'ChatGPT / Codex')
                           FROM oauth_requests r JOIN oauth_clients c ON c.client_id = r.client_id
                           WHERE r.request_hash = %s AND r.expires_at > now()""",
                        (main.token_hash(request_id),))
            row = cur.fetchone()
        return {"client_name": row[0]} if row else None

    async def complete_authorization(self, request_id: str, user_id: int) -> str | None:
        code = secrets.token_urlsafe(32)
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""DELETE FROM oauth_requests WHERE request_hash = %s AND expires_at > now()
                           RETURNING client_id, state, scopes, code_challenge, redirect_uri,
                                     redirect_uri_provided_explicitly, resource""",
                        (main.token_hash(request_id),))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("""INSERT INTO oauth_codes
                           (code_hash, client_id, user_id, scopes, code_challenge, redirect_uri,
                            redirect_uri_provided_explicitly, resource, expires_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() + interval '5 minutes')""",
                        (main.token_hash(code), row[0], user_id, json.dumps(row[2]), row[3],
                         row[4], row[5], row[6]))
        values = {"code": code}
        if row[1] is not None:
            values["state"] = row[1]
        return construct_redirect_uri(row[4], **values)

    async def load_authorization_code(self, client: OAuthClientInformationFull,
                                      authorization_code: str) -> AuthorizationCode | None:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT scopes, extract(epoch from expires_at), code_challenge,
                                  redirect_uri, redirect_uri_provided_explicitly, resource, user_id
                           FROM oauth_codes WHERE code_hash = %s AND client_id = %s""",
                        (main.token_hash(authorization_code), client.client_id))
            row = cur.fetchone()
        if not row:
            return None
        return AuthorizationCode(code=authorization_code, scopes=row[0], expires_at=row[1],
                                 client_id=client.client_id, code_challenge=row[2], redirect_uri=row[3],
                                 redirect_uri_provided_explicitly=row[4], resource=row[5],
                                 subject=str(row[6]))

    def _issue_tokens(self, cur, client_id: str, user_id: int,
                      scopes: list[str], resource: str) -> OAuthToken:
        access = main.OAUTH_ACCESS_PREFIX + secrets.token_urlsafe(32)
        refresh = "olgr_" + secrets.token_urlsafe(32)
        now = int(time.time())
        cur.execute("""INSERT INTO oauth_tokens
                       (access_token_hash, refresh_token_hash, client_id, user_id, scopes, resource,
                        access_expires_at, refresh_expires_at)
                       VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), to_timestamp(%s))""",
                    (main.token_hash(access), main.token_hash(refresh), client_id, user_id,
                     json.dumps(scopes), resource, now + ACCESS_TTL, now + REFRESH_TTL))
        return OAuthToken(access_token=access, refresh_token=refresh, expires_in=ACCESS_TTL,
                          scope=" ".join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull,
                                          authorization_code: AuthorizationCode) -> OAuthToken:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""DELETE FROM oauth_codes WHERE code_hash = %s AND client_id = %s
                           AND expires_at > now() RETURNING user_id, scopes, resource""",
                        (main.token_hash(authorization_code.code), client.client_id))
            row = cur.fetchone()
            if not row:
                raise TokenError("invalid_grant", "Authorization code is invalid or expired")
            return self._issue_tokens(cur, client.client_id, row[0], row[1], row[2])

    async def load_refresh_token(self, client: OAuthClientInformationFull,
                                 refresh_token: str) -> RefreshToken | None:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT t.scopes, extract(epoch from t.refresh_expires_at), t.user_id
                           FROM oauth_tokens t JOIN users u ON u.id = t.user_id
                           WHERE t.refresh_token_hash = %s AND t.client_id = %s
                             AND t.refresh_expires_at > now() AND u.status = 'active'""",
                        (main.token_hash(refresh_token), client.client_id))
            row = cur.fetchone()
        return (RefreshToken(token=refresh_token, client_id=client.client_id, scopes=row[0],
                             expires_at=int(row[1]), subject=str(row[2])) if row else None)

    async def exchange_refresh_token(self, client: OAuthClientInformationFull,
                                     refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""DELETE FROM oauth_tokens WHERE refresh_token_hash = %s AND client_id = %s
                           AND refresh_expires_at > now() RETURNING user_id, resource""",
                        (main.token_hash(refresh_token.token), client.client_id))
            row = cur.fetchone()
            if not row:
                raise TokenError("invalid_grant", "Refresh token is invalid or expired")
            return self._issue_tokens(cur, client.client_id, row[0], scopes, row[1])

    async def load_access_token(self, token: str) -> AccessToken | None:
        user = main.lookup_token_user(token)
        if not user:
            return None
        return AccessToken(token=token, client_id=user.get("client_id", "legacy-token"),
                           scopes=user.get("scopes", [main.OAUTH_SCOPE]),
                           expires_at=user.get("expires_at"), resource=main.OAUTH_RESOURCE,
                           subject=str(user["id"]))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        with main.pool.connection() as conn, conn.cursor() as cur:
            digest = main.token_hash(token.token)
            cur.execute("""DELETE FROM oauth_tokens
                           WHERE access_token_hash = %s OR refresh_token_hash = %s""", (digest, digest))


provider = OAuthProvider()

server = MCPServer(
    "olgae-planner",
    version="0.1.0",
    instructions=(
        "PRD 문서와 계층형 기능명세서를 읽고 고치는 툴이다. "
        "먼저 list_projects 로 slug 를 얻어 project_id 로 넘기고, get_spec 으로 전체를 읽는다. "
        "트리를 크게 고치기 전에는 save_version 으로 스냅샷을 남긴다."
    ),
    auth_server_provider=provider,
    auth=AuthSettings(
        issuer_url=main.PUBLIC_URL,
        service_documentation_url=main.PUBLIC_URL,
        resource_server_url=main.OAUTH_RESOURCE,
        required_scopes=[main.OAUTH_SCOPE],
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[main.OAUTH_SCOPE], default_scopes=[main.OAUTH_SCOPE]),
        revocation_options=RevocationOptions(enabled=True),
    ),
)


def _user(ctx: Context) -> dict:
    """MCP 요청 헤더의 API/OAuth 토큰으로 사용자를 판별한다."""
    headers = ctx.headers or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    user = main.opt_user(authorization=auth)
    if not user:
        raise ToolError(
            "인증 실패: OAuth 연결 또는 유효한 API 토큰이 필요합니다.")
    return user


def _wrap(fn, *args, **kwargs):
    """기존 핸들러를 호출하고 HTTPException 을 모델이 읽을 메시지로 바꾼다."""
    try:
        return fn(*args, **kwargs)
    except main.HTTPException as e:
        raise ToolError(f"{e.status_code}: {e.detail}") from e


def _numbered(nodes: list[dict]) -> list[dict]:
    """화면과 같은 계층 번호(1, 1.1 …)를 붙인다. 사람이 보는 번호로 항목을 지칭할 수 있게."""
    by_parent: dict[object, list[dict]] = {}
    for n in nodes:
        by_parent.setdefault(n["parent_id"], []).append(n)
    for group in by_parent.values():
        group.sort(key=lambda n: (n["sort_order"], n["id"]))
    out: list[dict] = []

    def walk(parent, prefix):
        for i, n in enumerate(by_parent.get(parent, []), 1):
            num = f"{prefix}{i}"
            out.append({**n, "number": num})
            walk(n["id"], num + ".")

    walk(None, "")
    return out


# ---------- 프로젝트 ----------

@server.tool(meta=OAUTH_META)
def list_projects(ctx: Context) -> list[dict]:
    """내 프로젝트 목록. 각 항목의 slug 를 다른 툴의 project_id 로 넘긴다(숫자 id 는 쓰지 않는다)."""
    return _wrap(main.list_projects, user=_user(ctx))


@server.tool(meta=OAUTH_META)
def get_spec(project_id: str, ctx: Context) -> dict:
    """프로젝트의 PRD 본문과 기능명세서 트리를 한 번에 가져온다.

    nodes 의 number 는 화면에 보이는 계층 번호(1, 1.1 …)다.
    parent_id 가 null 이면 대분류이고 트리는 최대 4단계까지 쓴다.
    importance 는 1 필수 / 2 권장 / 3 선택 / 4 보류.
    """
    user = _user(ctx)
    prd = _wrap(main.get_prd, project_id, user=user)["content"]
    nodes = _wrap(main.list_nodes, project_id, user=user)
    return {"project_id": project_id, "prd": prd, "nodes": _numbered(nodes)}


@server.tool(meta=OAUTH_META)
def set_prd(project_id: str, content: str, ctx: Context) -> dict:
    """PRD 본문(마크다운) 전체를 덮어쓴다. 부분 수정이 아니므로 get_spec 으로 받은 뒤 고쳐서 보낸다."""
    _wrap(main.put_prd, project_id, main.PrdIn(content=content), user=_user(ctx))
    return {"ok": True, "chars": len(content)}


# ---------- 기능명세서 ----------

@server.tool(meta=OAUTH_META)
def create_node(project_id: str, title: str, ctx: Context,
                parent_id: int | None = None) -> dict:
    """기능 항목을 추가한다. parent_id 를 비우면 대분류로 만든다."""
    return _wrap(main.create_node, project_id,
                 main.NodeIn(parent_id=parent_id, title=title), user=_user(ctx))


@server.tool(meta=OAUTH_META)
def update_node(node_id: int, ctx: Context, title: str | None = None,
                description: str | None = None, status: str | None = None,
                importance: int | None = None, sort_order: int | None = None,
                parent_id: int | None = None) -> dict:
    """기능 항목을 부분 수정한다. 넘긴 항목만 바뀐다.

    status: 기획 작성중 / 기획 완료 / 개발 중 / 완료
    importance: 1 필수 · 2 권장 · 3 선택 · 4 보류
    description: 마크다운. `용어` 로 감싸면 용어 사전에 자동 등록된다.
    parent_id: 다른 항목의 하위로 옮긴다. 자기 하위나 다른 프로젝트로는 옮길 수 없다.
    """
    fields = {k: v for k, v in {
        "title": title, "description": description, "status": status,
        "importance": importance, "sort_order": sort_order, "parent_id": parent_id,
    }.items() if v is not None}
    if not fields:
        raise ToolError("바꿀 항목을 하나 이상 넘겨야 합니다")
    return _wrap(main.update_node, node_id, main.NodeUpdate(**fields), user=_user(ctx))


@server.tool(meta=OAUTH_META)
def delete_node(node_id: int, ctx: Context) -> dict:
    """기능 항목을 삭제한다. 하위 항목과 코멘트도 함께 사라진다.
    되돌릴 수 없으니 지우기 전에 save_version 으로 스냅샷을 남기는 것이 좋다."""
    _wrap(main.delete_node, node_id, user=_user(ctx))
    return {"deleted": node_id}


# ---------- 용어 사전 ----------

@server.tool(meta=OAUTH_META)
def list_terms(project_id: str, ctx: Context) -> list[dict]:
    """용어 목록. 호출할 때 본문을 훑어 새 용어는 등록하고 쓰이지 않는 용어는 지운다.
    nodes 는 그 용어가 쓰인 기능 항목, in_prd 는 PRD 본문에 쓰였는지를 뜻한다."""
    return _wrap(main.list_terms, project_id, user=_user(ctx))


@server.tool(meta=OAUTH_META)
def set_term(term_id: int, ctx: Context, description: str | None = None, note: str | None = None,
             category_id: int | None = None, sort_order: int | None = None) -> dict:
    """용어의 설명(마크다운)·비고·카테고리·표시 순서를 바꾼다.
    용어 자체는 본문에서 자동 수집되므로 여기서 만들 수는 없다."""
    fields = {k: v for k, v in {
        "description": description, "note": note, "category_id": category_id, "sort_order": sort_order,
    }.items() if v is not None}
    if not fields:
        raise ToolError("바꿀 항목을 하나 이상 넘겨야 합니다")
    return _wrap(main.update_term, term_id, main.TermIn(**fields), user=_user(ctx))


# ---------- 버전 ----------

@server.tool(meta=OAUTH_META)
def save_version(project_id: str, ctx: Context) -> dict:
    """현재 PRD 와 기능명세서를 함께 스냅샷으로 저장한다. 크게 고치기 전에 먼저 호출할 것."""
    return _wrap(main.save_version, project_id, user=_user(ctx))


@server.tool(meta=OAUTH_META)
def list_versions(project_id: str, ctx: Context) -> list[dict]:
    """저장된 버전 목록(저장 일시·저장한 사용자·항목 수)."""
    return _wrap(main.list_versions, project_id, user=_user(ctx))


@server.tool(meta=OAUTH_META)
def restore_version(version_id: int, ctx: Context) -> dict:
    """PRD 와 기능명세서를 해당 버전 시점으로 되돌린다. 그 뒤의 변경은 사라지므로 사용자 확인을 받고 호출할 것."""
    return _wrap(main.restore_version, version_id, user=_user(ctx))


# ---------- 코멘트 ----------

@server.tool(meta=OAUTH_META)
def list_comments(node_id: int, ctx: Context) -> list[dict]:
    """기능 항목에 달린 코멘트 목록."""
    return _wrap(main.list_comments, node_id, user=_user(ctx))


@server.tool(meta=OAUTH_META)
def add_comment(node_id: int, content: str, ctx: Context) -> dict:
    """기능 항목에 코멘트를 남긴다. 작성자는 토큰의 주인으로 기록된다."""
    return _wrap(main.create_comment, node_id,
                 main.CommentIn(content=content), user=_user(ctx))


async def oauth_metadata(_request):
    """SDK 기본값 대신 PKCE 공개 클라이언트(`none`) 지원을 명시한다."""
    base = main.PUBLIC_URL
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": base + "/authorize",
        "token_endpoint": base + "/token",
        "registration_endpoint": base + "/register",
        "revocation_endpoint": base + "/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": [main.OAUTH_SCOPE],
    }, headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"})


async def oauth_revoke(request):
    """SDK의 공개 클라이언트 폐기 요청에서 빈 client_secret을 요구하지 않게 한다."""
    form = await request.form()
    client_id, token = str(form.get("client_id", "")), str(form.get("token", ""))
    client = await provider.get_client(client_id)
    if not client or client.token_endpoint_auth_method != "none":
        return JSONResponse({"error": "unauthorized_client"}, status_code=401)
    digest = main.token_hash(token)
    with main.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""DELETE FROM oauth_tokens WHERE client_id = %s
                       AND (access_token_hash = %s OR refresh_token_hash = %s)""",
                    (client_id, digest, digest))
    return Response(status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def asgi_app():
    """FastAPI 에 마운트할 ASGI 앱. 세션 없는(stateless) HTTP 로 둔다."""
    # 프록시(nginx) 뒤에 서므로 Host/Origin 검사 대상은 배포 주소다.
    # MCP_ALLOWED_HOSTS 를 주면 그 목록만 허용하고(권장), 비어 있으면 검사를 끈다.
    # 인증은 요청마다 Authorization 헤더로 하므로 이 검사는 DNS 리바인딩 방어용이다.
    allowed = [h.strip() for h in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = (TransportSecuritySettings(allowed_hosts=allowed, allowed_origins=allowed)
                if allowed else
                TransportSecuritySettings(enable_dns_rebinding_protection=False,
                                          allowed_hosts=[], allowed_origins=[]))
    oauth_app = server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=security,
    )
    # Starlette는 먼저 일치한 라우트를 쓰므로 SDK 메타데이터보다 앞에 둔다.
    oauth_app.router.routes[0:0] = [
        Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET", "OPTIONS"]),
        Route("/revoke", oauth_revoke, methods=["POST"]),
    ]
    return oauth_app
