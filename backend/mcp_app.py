"""HTTP MCP 서버 — 배포 서버가 /mcp 로 함께 제공한다.

사용자는 설치 없이 명령 한 줄로 등록한다:
  claude mcp add --transport http prd-spec https://<호스트>/mcp -H "Authorization: Bearer <세션토큰>"

인증은 요청마다 Authorization 헤더로 한다. 서버는 토큰을 저장하지 않으며,
권한 판정은 main.py 의 기존 핸들러(opt_user / check_access / check_owner)를 그대로 재사용한다.
"""

import os

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

import main

server = MCPServer(
    "prd-spec",
    version="0.1.0",
    instructions=(
        "PRD 문서와 계층형 기능명세서를 읽고 고치는 툴이다. "
        "먼저 list_projects 로 project_id 를 얻고, get_spec 으로 전체를 읽는다. "
        "트리를 크게 고치기 전에는 save_version 으로 스냅샷을 남긴다."
    ),
)


def _user(ctx: Context) -> dict:
    """MCP 요청 헤더의 세션 토큰으로 사용자를 판별한다."""
    headers = ctx.headers or {}
    auth = headers.get("authorization") or headers.get("Authorization")
    user = main.opt_user(authorization=auth)
    if not user:
        raise ToolError(
            "인증 실패: 유효한 세션 토큰이 필요합니다. "
            "등록할 때 -H \"Authorization: Bearer <토큰>\" 을 넣었는지 확인하세요.")
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

@server.tool()
def list_projects(ctx: Context) -> list[dict]:
    """내 프로젝트 목록. 다른 툴에 넘길 project_id 를 여기서 얻는다."""
    return _wrap(main.list_projects, user=_user(ctx))


@server.tool()
def get_spec(project_id: int, ctx: Context) -> dict:
    """프로젝트의 PRD 본문과 기능명세서 트리를 한 번에 가져온다.

    nodes 의 number 는 화면에 보이는 계층 번호(1, 1.1 …)다.
    parent_id 가 null 이면 대분류이고 트리는 최대 4단계까지 쓴다.
    importance 는 1 필수 / 2 권장 / 3 선택 / 4 보류.
    """
    user = _user(ctx)
    prd = _wrap(main.get_prd, project_id, user=user)["content"]
    nodes = _wrap(main.list_nodes, project_id, user=user)
    return {"project_id": project_id, "prd": prd, "nodes": _numbered(nodes)}


@server.tool()
def set_prd(project_id: int, content: str, ctx: Context) -> dict:
    """PRD 본문(마크다운) 전체를 덮어쓴다. 부분 수정이 아니므로 get_spec 으로 받은 뒤 고쳐서 보낸다."""
    _wrap(main.put_prd, project_id, main.PrdIn(content=content), user=_user(ctx))
    return {"ok": True, "chars": len(content)}


# ---------- 기능명세서 ----------

@server.tool()
def create_node(project_id: int, title: str, ctx: Context,
                parent_id: int | None = None) -> dict:
    """기능 항목을 추가한다. parent_id 를 비우면 대분류로 만든다."""
    return _wrap(main.create_node, project_id,
                 main.NodeIn(parent_id=parent_id, title=title), user=_user(ctx))


@server.tool()
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


@server.tool()
def delete_node(node_id: int, ctx: Context) -> dict:
    """기능 항목을 삭제한다. 하위 항목과 코멘트도 함께 사라진다.
    되돌릴 수 없으니 지우기 전에 save_version 으로 스냅샷을 남기는 것이 좋다."""
    _wrap(main.delete_node, node_id, user=_user(ctx))
    return {"deleted": node_id}


# ---------- 용어 사전 ----------

@server.tool()
def list_terms(project_id: int, ctx: Context) -> list[dict]:
    """용어 목록. 호출할 때 본문을 훑어 새 용어는 등록하고 쓰이지 않는 용어는 지운다.
    nodes 는 그 용어가 쓰인 기능 항목, in_prd 는 PRD 본문에 쓰였는지를 뜻한다."""
    return _wrap(main.list_terms, project_id, user=_user(ctx))


@server.tool()
def set_term(term_id: int, ctx: Context, description: str | None = None,
             category_id: int | None = None, sort_order: int | None = None) -> dict:
    """용어의 설명(마크다운)·카테고리·표시 순서를 바꾼다.
    용어 자체는 본문에서 자동 수집되므로 여기서 만들 수는 없다."""
    fields = {k: v for k, v in {
        "description": description, "category_id": category_id, "sort_order": sort_order,
    }.items() if v is not None}
    if not fields:
        raise ToolError("바꿀 항목을 하나 이상 넘겨야 합니다")
    return _wrap(main.update_term, term_id, main.TermIn(**fields), user=_user(ctx))


# ---------- 버전 ----------

@server.tool()
def save_version(project_id: int, ctx: Context) -> dict:
    """현재 PRD 와 기능명세서를 함께 스냅샷으로 저장한다. 크게 고치기 전에 먼저 호출할 것."""
    return _wrap(main.save_version, project_id, user=_user(ctx))


@server.tool()
def list_versions(project_id: int, ctx: Context) -> list[dict]:
    """저장된 버전 목록(저장 일시·저장한 사용자·항목 수)."""
    return _wrap(main.list_versions, project_id, user=_user(ctx))


@server.tool()
def restore_version(version_id: int, ctx: Context) -> dict:
    """PRD 와 기능명세서를 해당 버전 시점으로 되돌린다. 그 뒤의 변경은 사라지므로 사용자 확인을 받고 호출할 것."""
    return _wrap(main.restore_version, version_id, user=_user(ctx))


# ---------- 코멘트 ----------

@server.tool()
def list_comments(node_id: int, ctx: Context) -> list[dict]:
    """기능 항목에 달린 코멘트 목록."""
    return _wrap(main.list_comments, node_id, user=_user(ctx))


@server.tool()
def add_comment(node_id: int, content: str, ctx: Context) -> dict:
    """기능 항목에 코멘트를 남긴다. 작성자는 토큰의 주인으로 기록된다."""
    return _wrap(main.create_comment, node_id,
                 main.CommentIn(content=content), user=_user(ctx))


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
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=security,
    )
