"""Google OAuth 계정 연결·가입과 세션 보안의 최소 회귀 검사."""

import os
import secrets
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

os.environ["PUBLIC_URL"] = "http://localhost:3000"
os.environ["GOOGLE_CLIENT_ID"] = "test.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-secret"

import main
from fastapi import HTTPException


def run():
    main.init_db()
    suffix = secrets.token_hex(6)
    linked_login = f"google-link-{suffix}@example.test"
    new_login = f"google-new-{suffix}@example.test"
    linked_sub = f"google-link-sub-{suffix}"
    new_sub = f"google-new-sub-{suffix}"
    user_ids = []

    with main.pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM settings WHERE key = 'signup_open'")
        previous_signup = cur.fetchone()
        cur.execute("""INSERT INTO settings (key, value) VALUES ('signup_open', '1')
                       ON CONFLICT (key) DO UPDATE SET value = '1'""")
        cur.execute("""INSERT INTO users
                       (username, login_id, display_name, password, role, status)
                       VALUES (%s, %s, '연결 검사', %s, 'guest', 'active') RETURNING id""",
                    (linked_login, linked_login, main.hash_pw(secrets.token_urlsafe(32))))
        linked_uid = cur.fetchone()[0]
        user_ids.append(linked_uid)

    try:
        local_request = SimpleNamespace(headers={
            "host": "localhost:3000", "origin": "http://localhost:3000"
        })
        prod_request = SimpleNamespace(headers={"host": "prd.donhse.duckdns.org"})
        assert main.google_redirect_uri(local_request) == \
            "http://localhost:3000/api/auth/google/callback"
        assert main.google_redirect_uri(prod_request) == \
            "https://prd.donhse.duckdns.org/api/auth/google/callback"
        try:
            main.google_redirect_uri(SimpleNamespace(headers={"host": "evil.example"}))
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("등록되지 않은 Host가 Google callback으로 사용됐습니다")

        auth_url = main.create_google_request(
            "link", linked_uid, "/?tab=profile", main.google_redirect_uri(local_request))
        query = parse_qs(urlsplit(auth_url).query)
        assert query["redirect_uri"] == ["http://localhost:3000/api/auth/google/callback"]
        assert query["code_challenge_method"] == ["S256"]
        assert len(query["code_challenge"][0]) == 43

        flow = main.consume_google_request(query["state"][0])
        assert flow and flow["mode"] == "link" and flow["user_id"] == linked_uid
        assert main.consume_google_request(query["state"][0]) is None

        result = main.apply_google_identity(flow, {
            "sub": linked_sub, "email": linked_login, "name": "연결된 이름"
        })
        assert result == {"status": "linked"}

        try:
            main.apply_google_identity({"mode": "login", "user_id": None}, {
                "sub": linked_sub + "-other", "email": linked_login, "name": "다른 계정"
            })
        except HTTPException as exc:
            assert exc.status_code == 409 and exc.detail == "link-required"
        else:
            raise AssertionError("같은 이메일의 기존 계정이 자동 연결됐습니다")

        result = main.apply_google_identity({"mode": "login", "user_id": None}, {
            "sub": new_sub, "email": new_login, "name": "신규 닉네임"
        })
        assert result == {"status": "pending"}

        with main.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("""SELECT id, display_name, password, google_sub, status
                             FROM users WHERE login_id = %s""", (new_login,))
            new_uid, name, password_hash, stored_sub, status = cur.fetchone()
            user_ids.append(new_uid)
            assert (name, stored_sub, status) == ("신규 닉네임", new_sub, "pending")
            assert "$" in password_hash and new_login not in password_hash

            token, csrf = main.make_session(cur, linked_uid)
            cur.execute("""SELECT token, csrf_token_hash,
                                  extract(epoch from (expires_at - now()))
                             FROM sessions WHERE user_id = %s ORDER BY created_at DESC LIMIT 1""",
                        (linked_uid,))
            stored_token, stored_csrf, ttl = cur.fetchone()
            assert stored_token == main.token_hash(token) and token != stored_token
            assert stored_csrf == main.token_hash(csrf) and 86_300 < ttl <= 86_400
        assert main.lookup_token_user(token)["id"] == linked_uid
    finally:
        with main.pool.connection() as conn, conn.cursor() as cur:
            if user_ids:
                cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
            if previous_signup:
                cur.execute("UPDATE settings SET value = %s WHERE key = 'signup_open'",
                            (previous_signup[0],))
            else:
                cur.execute("DELETE FROM settings WHERE key = 'signup_open'")

    print("google auth checks passed")


if __name__ == "__main__":
    run()
