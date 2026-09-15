"""Runnable OAuth smoke test: docker-compose exec -T backend python test_oauth.py"""

import base64
import hashlib
import json
import secrets
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import main


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(path, *, data=None, headers=None, redirect=True):
    request = Request("http://frontend" + path, data=data, headers=headers or {})
    try:
        return (urlopen if redirect else build_opener(NoRedirect).open)(request)
    except HTTPError as exc:
        return exc


def form(path, values, *, redirect=True):
    return fetch(path, data=urlencode(values).encode(),
                 headers={"Content-Type": "application/x-www-form-urlencoded"}, redirect=redirect)


def run():
    login_id = "oauth-check-" + secrets.token_hex(6)
    password = secrets.token_urlsafe(18)
    client_id = None
    redirect_uri = "https://chatgpt.com/connector_platform_oauth_redirect"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    try:
        unauthenticated = fetch("/mcp")
        assert unauthenticated.status == 401
        assert ('resource_metadata="' + main.PUBLIC_URL +
                '/.well-known/oauth-protected-resource/mcp"') in unauthenticated.headers["WWW-Authenticate"]
        protected = json.load(fetch("/.well-known/oauth-protected-resource/mcp"))
        assert protected["resource"] == main.OAUTH_RESOURCE
        assert protected["authorization_servers"] == [main.PUBLIC_URL]
        metadata = json.load(fetch("/.well-known/oauth-authorization-server"))
        assert metadata["code_challenge_methods_supported"] == ["S256"]
        assert metadata["token_endpoint_auth_methods_supported"] == ["none"]

        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO users (username, login_id, display_name, password, role, status)
                           VALUES (%s, %s, 'OAuth 점검', %s, 'guest', 'active') RETURNING id""",
                        (login_id, login_id, main.hash_pw(password)))
            user_id = cur.fetchone()[0]

        login_response = fetch("/api/auth/login", data=json.dumps({
            "login_id": login_id, "password": password,
        }).encode(), headers={"Content-Type": "application/json"})
        assert login_response.status == 200
        session_token = json.load(login_response)["token"]
        issue_response = fetch("/api/me/tokens", data=b'{"name":"OAuth check"}', headers={
            "Authorization": "Bearer " + session_token, "Content-Type": "application/json",
        })
        assert issue_response.status == 201
        api_token = json.load(issue_response)["token"]
        legacy_token = main.API_TOKEN_PREFIX + secrets.token_urlsafe(24)
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT token, token_hint FROM api_tokens WHERE user_id = %s", (user_id,))
            stored_token, token_hint = cur.fetchone()
            assert stored_token == main.token_hash(api_token)
            assert token_hint == main.mask_api_token(api_token)
            cur.execute("""INSERT INTO api_tokens (token, user_id, name)
                           VALUES (%s, %s, 'Legacy OAuth check')""", (legacy_token, user_id))
            main._migrate_api_tokens(cur)
            cur.execute("SELECT token, token_hint FROM api_tokens WHERE name = 'Legacy OAuth check'")
            stored_token, token_hint = cur.fetchone()
            assert stored_token == main.token_hash(legacy_token)
            assert token_hint == main.mask_api_token(legacy_token)
        assert main.lookup_token_user(api_token)["id"] == user_id

        legacy_initialize = fetch("/mcp", data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "legacy-smoke", "version": "1"}},
        }).encode(), headers={
            "Authorization": "Bearer " + legacy_token,
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "Host": "localhost:3000",
        })
        assert legacy_initialize.status == 200 and b"olgae-planner" in legacy_initialize.read()

        registration = fetch("/register", data=json.dumps({
            "client_name": "OAuth smoke test",
            "redirect_uris": [redirect_uri],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "mcp",
        }).encode(), headers={"Content-Type": "application/json"})
        assert registration.status == 201
        client_id = json.load(registration)["client_id"]

        query = urlencode({
            "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "resource": main.OAUTH_RESOURCE, "scope": "mcp", "state": "smoke-state",
        })
        authorization = fetch("/authorize?" + query, redirect=False)
        assert authorization.status == 302
        login_path = urlsplit(authorization.headers["Location"]).path + "?" + urlsplit(
            authorization.headers["Location"]).query
        request_id = parse_qs(urlsplit(login_path).query)["request"][0]
        login_page = fetch(login_path)
        assert login_page.status == 200
        assert "form-action 'self' https://chatgpt.com" in login_page.headers["Content-Security-Policy"]
        callback = form("/oauth/login", {
            "request_id": request_id, "login_id": login_id, "password": password,
        }, redirect=False)
        assert callback.status == 302
        callback_query = parse_qs(urlsplit(callback.headers["Location"]).query)
        assert callback_query["state"] == ["smoke-state"]

        token_response = form("/token", {
            "grant_type": "authorization_code", "client_id": client_id,
            "code": callback_query["code"][0], "redirect_uri": redirect_uri,
            "code_verifier": verifier, "resource": main.OAUTH_RESOURCE,
        })
        assert token_response.status == 200
        tokens = json.load(token_response)
        assert tokens["access_token"].startswith(main.OAUTH_ACCESS_PREFIX)
        assert tokens["refresh_token"].startswith("olgr_")

        initialize = fetch("/mcp", data=json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "oauth-smoke", "version": "1"}},
        }).encode(), headers={
            "Authorization": "Bearer " + tokens["access_token"],
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "Host": "localhost:3000",
        })
        assert initialize.status == 200 and b"olgae-planner" in initialize.read()

        tools_list = fetch("/mcp", data=json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }).encode(), headers={
            "Authorization": "Bearer " + tokens["access_token"],
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
            "Host": "localhost:3000",
        })
        tools_body = tools_list.read()
        assert tools_list.status == 200 and b"securitySchemes" in tools_body and b"oauth2" in tools_body

        refreshed_response = form("/token", {
            "grant_type": "refresh_token", "client_id": client_id,
            "refresh_token": tokens["refresh_token"], "resource": main.OAUTH_RESOURCE,
        })
        assert refreshed_response.status == 200
        refreshed = json.load(refreshed_response)
        assert refreshed["access_token"] != tokens["access_token"]

        revoked = form("/revoke", {
            "client_id": client_id, "token": refreshed["refresh_token"],
            "token_type_hint": "refresh_token",
        })
        assert revoked.status == 200
        print("API token compatibility + OAuth DCR + PKCE + MCP + refresh + revoke: OK")
    finally:
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE login_id = %s", (login_id,))
            if client_id:
                cur.execute("DELETE FROM oauth_clients WHERE client_id = %s", (client_id,))


if __name__ == "__main__":
    run()
