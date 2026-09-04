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
        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO users (username, login_id, display_name, password, role, status)
                           VALUES (%s, %s, 'OAuth 점검', %s, 'guest', 'active') RETURNING id""",
                        (login_id, login_id, main.hash_pw(password)))
            user_id = cur.fetchone()[0]
            legacy_token = main.API_TOKEN_PREFIX + secrets.token_urlsafe(24)
            cur.execute("INSERT INTO api_tokens (token, user_id, name) VALUES (%s, %s, 'OAuth 점검')",
                        (legacy_token, user_id))

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
