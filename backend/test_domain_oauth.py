"""격리 DB에서 새 도메인 Google 로그인과 중첩 MCP OAuth callback을 검증한다.

Google 외부 토큰 응답/서명 검증만 mock하며 state·nonce·PKCE·DB·세션·MCP 승인 처리는 실제 코드를 쓴다.
"""

import base64
import hashlib
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

import main


class DomainOAuthTests(unittest.TestCase):
    def test_public_origin_validation(self):
        for value in ("https://prd.donyk.link", "https://PRD.DONYK.LINK/",
                      "https://prd.donyk.link:443"):
            self.assertEqual(main.normalize_public_url(value), "https://prd.donyk.link")
        for host in ("localhost", "127.0.0.1"):
            value = f"http://{host}:3000"
            self.assertEqual(main.normalize_public_url(value), value)
        for value in ("", " https://prd.donyk.link", "http://prd.donyk.link",
                      "https://prd.donyk.link:8443", "https://user@prd.donyk.link",
                      "https://prd.donyk.link/path", "https://prd.donyk.link?x=1",
                      "https://prd.donyk.link#fragment", "https://prd.donyk.link?",
                      "https://prd.donyk.link//", "https://evil\\@prd.donyk.link"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                main.normalize_public_url(value)

    def test_google_host_and_origin(self):
        self.assertEqual(main.PUBLIC_URL, "https://prd.donyk.link")
        for host in ("prd.donyk.link", "PRD.DONYK.LINK", "prd.donyk.link:443"):
            request = SimpleNamespace(headers={"host": host, "origin": main.PUBLIC_URL})
            self.assertEqual(main.google_redirect_uri(request),
                             main.PUBLIC_URL + "/api/auth/google/callback")
        for headers in ({"host": "prd.donhse.duckdns.org"}, {"host": "evil.example"},
                        {"host": "prd.donyk.link:8443"}, {"host": "localhost:3000"},
                        {"host": "prd.donyk.link", "origin": "https://evil.example"}):
            with self.subTest(headers=headers), self.assertRaises(HTTPException) as caught:
                main.google_redirect_uri(SimpleNamespace(headers=headers))
            self.assertEqual(caught.exception.status_code, 400)

    def test_google_web_and_plugin_callback(self):
        main.init_db()
        suffix = secrets.token_hex(6)
        client_id = None
        user_id = None
        http_client = httpx.Client
        nonce = ""
        sub = "domain-qa-" + suffix
        email = suffix + "@example.test"
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")

        def google_exchange(request):
            values = parse_qs(request.content.decode())
            self.assertEqual(str(request.url), main.GOOGLE_TOKEN_URL)
            self.assertEqual(values["redirect_uri"], [main.PUBLIC_URL + "/api/auth/google/callback"])
            self.assertEqual(values["code"], ["google-test-code"])
            self.assertTrue(values["code_verifier"][0])
            return httpx.Response(200, json={"id_token": "mock-signed-google-id-token"})

        def google_claims(raw, request, audience):
            self.assertEqual(raw, "mock-signed-google-id-token")
            self.assertEqual(audience, main.GOOGLE_CLIENT_ID)
            return {"sub": sub, "email": email, "email_verified": True,
                    "name": "Domain QA", "nonce": nonce}

        transport = httpx.MockTransport(google_exchange)
        try:
            with main.pool.connection() as conn, conn.cursor() as cur:
                cur.execute("""INSERT INTO users
                               (username, login_id, display_name, password, role, status, google_sub)
                               VALUES (%s, %s, 'Domain QA', %s, 'guest', 'active', %s) RETURNING id""",
                            (email, email, main.hash_pw(secrets.token_urlsafe(20)), sub))
                user_id = cur.fetchone()[0]
            with TestClient(main.app, base_url=main.PUBLIC_URL, follow_redirects=False) as client:
                # 로컬 웹 로그인: 새 callback, PKCE, 일회용 state와 Secure 세션 쿠키.
                start = client.post("/api/auth/google/start", json={"mode": "login", "return_to": "/"})
                self.assertEqual(start.status_code, 200)
                query = parse_qs(urlsplit(start.json()["url"]).query)
                self.assertEqual(query["redirect_uri"], [main.PUBLIC_URL + "/api/auth/google/callback"])
                self.assertEqual(query["code_challenge_method"], ["S256"])
                nonce = query["nonce"][0]
                with patch.object(main.httpx, "Client", side_effect=lambda **kw: http_client(transport=transport, **kw)), \
                        patch.object(main.google_id_token, "verify_oauth2_token", side_effect=google_claims):
                    callback = client.get("/api/auth/google/callback", params={
                        "state": query["state"][0], "code": "google-test-code"})
                self.assertEqual(callback.status_code, 303)
                self.assertEqual(callback.headers["location"], "/?google=authenticated")
                self.assertIn("Secure", callback.headers["set-cookie"])
                self.assertEqual(client.get("/api/me").status_code, 200)
                replay = client.get("/api/auth/google/callback", params={
                    "state": query["state"][0], "code": "google-test-code"})
                self.assertIn("invalid-state", replay.headers["location"])

                registration = client.post("/oauth-server/register", json={
                    "client_name": "Domain QA", "redirect_uris": ["https://chatgpt.com/connector/oauth/domain-qa"],
                    "token_endpoint_auth_method": "none", "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"], "scope": "mcp"})
                self.assertEqual(registration.status_code, 201)
                client_id = registration.json()["client_id"]
                authorize = client.get("/oauth-server/authorize", params={
                    "response_type": "code", "client_id": client_id,
                    "redirect_uri": "https://chatgpt.com/connector/oauth/domain-qa",
                    "resource": main.OAUTH_RESOURCE, "scope": "mcp", "state": "outer-mcp-state",
                    "code_challenge": challenge, "code_challenge_method": "S256"})
                self.assertEqual(authorize.status_code, 302)
                self.assertTrue(authorize.headers["location"].startswith(main.PUBLIC_URL + "/oauth/login?"))
                request_id = parse_qs(urlsplit(authorize.headers["location"]).query)["request"][0]
                start = client.get("/oauth/google/start", params={"request_id": request_id})
                self.assertEqual(start.status_code, 302)
                query = parse_qs(urlsplit(start.headers["location"]).query)
                nonce = query["nonce"][0]
                with patch.object(main.httpx, "Client", side_effect=lambda **kw: http_client(transport=transport, **kw)), \
                        patch.object(main.google_id_token, "verify_oauth2_token", side_effect=google_claims):
                    callback = client.get("/api/auth/google/callback", params={
                        "state": query["state"][0], "code": "google-test-code"})
                self.assertEqual(callback.status_code, 303)
                result = urlsplit(callback.headers["location"])
                self.assertEqual(result.netloc, "chatgpt.com")
                values = parse_qs(result.query)
                self.assertEqual(values["state"], ["outer-mcp-state"])
                token = client.post("/oauth-server/token", data={
                    "grant_type": "authorization_code", "client_id": client_id,
                    "redirect_uri": "https://chatgpt.com/connector/oauth/domain-qa",
                    "code": values["code"][0], "code_verifier": verifier, "resource": main.OAUTH_RESOURCE})
                self.assertEqual(token.status_code, 200)
                self.assertEqual(main.lookup_token_user(token.json()["access_token"])["id"], user_id)

                # 폐기된 도메인의 refresh는 provider를 직접 호출해도 거부한다.
                import asyncio
                provider = main.mcp_app.provider
                oauth_client = asyncio.run(provider.get_client(client_id))
                with main.pool.connection() as conn, conn.cursor() as cur:
                    old = provider._issue_tokens(cur, client_id, user_id, ["mcp"],
                                                 "https://prd.donhse.duckdns.org/mcp")
                self.assertIsNone(asyncio.run(provider.load_refresh_token(oauth_client, old.refresh_token)))
                self.assertIsNone(main.lookup_token_user(old.access_token))
        finally:
            with main.pool.connection() as conn, conn.cursor() as cur:
                if user_id:
                    cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                if client_id:
                    cur.execute("DELETE FROM oauth_clients WHERE client_id = %s", (client_id,))


if __name__ == "__main__":
    unittest.main()
