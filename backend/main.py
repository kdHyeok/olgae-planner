import hashlib
import json
import os
import re
import secrets

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

pool = ConnectionPool(os.environ["DATABASE_URL"])


@asynccontextmanager
async def lifespan(_app):
    init_db()
    # /mcp 는 streamable HTTP 라 세션 매니저의 태스크 그룹이 떠 있어야 한다
    async with mcp_app.server.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)

PRD_TEMPLATE = "# PRD\n\n## 개요\n\n내용을 작성하세요.\n"

# 등급별 프로젝트 개수 한도 (None = 무제한)
ROLE_LIMITS = {"admin": None, "pro": 5, "member": 3, "guest": 1}
LOGIN_MAX_FAILS = 5      # 같은 IP 에서 한 계정에 대한 연속 실패 허용 횟수
LOGIN_IP_MAX_FAILS = 20  # 한 IP 에서의 총 실패 허용 횟수 (여러 계정 대입 방어)
LOGIN_FAIL_WINDOW_MIN = 10       # 이 시간 안의 실패만 이어서 센다
LOGIN_LOCK_STEPS = [30, 60, 180, 300, 600, 1800]   # 잠금이 반복될수록 길어진다(초)
LOGIN_LOCK_RESET_H = 24          # 이만큼 조용하면 잠금 단계가 처음으로 돌아간다

MAX_AVATAR_CHARS = 200_000       # 프로필 이미지(data URL) 길이 상한, 대략 150KB

# 등급별 이미지 업로드 총량 (MB, None = 무제한). 프로젝트 소유자 기준으로 합산한다
ROLE_UPLOAD_MB = {"admin": None, "pro": 500, "member": 200, "guest": 50}


def init_db():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id serial PRIMARY KEY,
                username text NOT NULL UNIQUE,
                password text NOT NULL
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS role   text NOT NULL DEFAULT 'guest';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
            CREATE TABLE IF NOT EXISTS settings (
                key text PRIMARY KEY,
                value text NOT NULL
            );
            -- 계정 이름만으로 잠그면 남의 아이디를 잠글 수 있어 IP 를 키에 함께 넣는다
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'login_attempts' AND column_name = 'username')
                THEN DROP TABLE login_attempts; END IF;
            END $$;
            CREATE TABLE IF NOT EXISTS login_attempts (
                key text PRIMARY KEY,          -- 'u:<이름>@<IP>' 또는 'ip:<IP>'
                fails int NOT NULL DEFAULT 0,
                last_fail timestamptz NOT NULL DEFAULT now()
            );
            ALTER TABLE login_attempts ADD COLUMN IF NOT EXISTS locks int NOT NULL DEFAULT 0;
            ALTER TABLE login_attempts ADD COLUMN IF NOT EXISTS locked_until timestamptz;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar text;
            CREATE TABLE IF NOT EXISTS sessions (
                token text PRIMARY KEY,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            ALTER TABLE sessions ADD COLUMN IF NOT EXISTS
                created_at timestamptz NOT NULL DEFAULT now();
            CREATE TABLE IF NOT EXISTS projects (
                id serial PRIMARY KEY,
                owner_id int REFERENCES users(id) ON DELETE CASCADE,
                name text NOT NULL,
                prd text NOT NULL DEFAULT '',
                share_token text
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                parent_id int REFERENCES nodes(id) ON DELETE CASCADE,
                title text NOT NULL,
                description text NOT NULL DEFAULT '',
                status text NOT NULL DEFAULT '기획 작성중',
                importance int NOT NULL DEFAULT 2,
                sort_order int NOT NULL DEFAULT 0
            );
            -- 구버전 볼륨 업그레이드용 (새 설치에서는 no-op)
            ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
                project_id int REFERENCES projects(id) ON DELETE CASCADE;
            CREATE TABLE IF NOT EXISTS versions (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id int REFERENCES users(id) ON DELETE SET NULL,
                username text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                data jsonb NOT NULL
            );
            -- 버전에 PRD 도 함께 담는다. 이미 있던 버전은 지금의 PRD 로 한 번만 채운다
            ALTER TABLE versions ADD COLUMN IF NOT EXISTS prd text;
            UPDATE versions v SET prd = p.prd FROM projects p
             WHERE p.id = v.project_id AND v.prd IS NULL;
            CREATE TABLE IF NOT EXISTS term_categories (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                name text NOT NULL,
                UNIQUE (project_id, name)
            );
            CREATE TABLE IF NOT EXISTS terms (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                term text NOT NULL,
                description text NOT NULL DEFAULT '',
                UNIQUE (project_id, term)
            );
            ALTER TABLE terms ADD COLUMN IF NOT EXISTS sort_order int NOT NULL DEFAULT 0;
            ALTER TABLE terms ADD COLUMN IF NOT EXISTS
                category_id int REFERENCES term_categories(id) ON DELETE SET NULL;
            CREATE TABLE IF NOT EXISTS images (
                id text PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                mime text NOT NULL,
                data bytea NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS comments (
                id serial PRIMARY KEY,
                node_id int NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            );
        """)
        # legacy migration: pre-project nodes/prd become the default project
        cur.execute("SELECT count(*) FROM nodes WHERE project_id IS NULL")
        if cur.fetchone()[0]:
            legacy_prd = ""
            cur.execute("SELECT to_regclass('prd')")
            if cur.fetchone()[0]:
                cur.execute("SELECT content FROM prd LIMIT 1")
                row = cur.fetchone()
                legacy_prd = row[0] if row else ""
            cur.execute("SELECT min(id) FROM users")
            owner = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO projects (owner_id, name, prd) VALUES (%s, %s, %s) RETURNING id",
                (owner, "기본 프로젝트", legacy_prd))
            cur.execute("UPDATE nodes SET project_id = %s WHERE project_id IS NULL",
                        (cur.fetchone()[0],))

        # 정리·최적화 (모두 멱등). 이관이 끝난 뒤에만 실행되도록 마이그레이션 아래에 둔다.
        cur.execute("""
            ALTER TABLE nodes  ALTER COLUMN project_id SET NOT NULL;
            ALTER TABLE images ALTER COLUMN project_id SET NOT NULL;
            DROP TABLE IF EXISTS prd;                         -- projects.prd 로 이관 완료, 레거시
            CREATE INDEX IF NOT EXISTS nodes_project_id_idx    ON nodes (project_id);
            CREATE INDEX IF NOT EXISTS nodes_parent_id_idx     ON nodes (parent_id);
            CREATE INDEX IF NOT EXISTS comments_node_id_idx    ON comments (node_id);
            CREATE INDEX IF NOT EXISTS comments_user_id_idx    ON comments (user_id);
            CREATE INDEX IF NOT EXISTS images_project_id_idx   ON images (project_id);
            CREATE INDEX IF NOT EXISTS terms_project_id_idx    ON terms (project_id);
            CREATE INDEX IF NOT EXISTS terms_category_id_idx   ON terms (category_id);
            CREATE INDEX IF NOT EXISTS term_categories_project_id_idx ON term_categories (project_id);
            CREATE INDEX IF NOT EXISTS versions_project_id_idx ON versions (project_id);
            CREATE INDEX IF NOT EXISTS sessions_user_id_idx    ON sessions (user_id);
            CREATE INDEX IF NOT EXISTS projects_owner_id_idx   ON projects (owner_id);
            CREATE INDEX IF NOT EXISTS users_status_idx         ON users (status);
            INSERT INTO settings (key, value) VALUES ('signup_open', '1')
                ON CONFLICT (key) DO NOTHING;
            -- 최초 부트스트랩: 관리자가 없으면 가장 오래된 계정을 관리자로 올린다
            UPDATE users SET role = 'admin', status = 'active'
             WHERE id = (SELECT min(id) FROM users)
               AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin');
            -- ponytail: 세션 만료는 기동 시 30일 지난 것만 지우는 방식. 요청마다 검사해야 하면 opt_user 에 조건 추가
            DELETE FROM sessions WHERE created_at < now() - interval '30 days';
            DELETE FROM login_attempts WHERE last_fail < now() - interval '24 hours';
        """)


def rows_to_dicts(cur):
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------- auth ----------
class Credentials(BaseModel):
    username: str
    password: str


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"


def opt_user(authorization: str | None = Header(None)) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT u.id, u.username, u.role, u.status FROM sessions s
                       JOIN users u ON u.id = s.user_id WHERE s.token = %s""",
                    (authorization[7:],))
        row = cur.fetchone()
    if not row or row[3] != "active":
        return None                      # 대기·차단 계정의 세션은 통하지 않는다
    return {"id": row[0], "username": row[1], "role": row[2]}


def current_user(user: dict | None = Depends(opt_user)) -> dict:
    if not user:
        raise HTTPException(401, "로그인이 필요합니다")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "관리자만 접근할 수 있습니다")
    return user


def get_setting(cur, key: str, default: str = "") -> str:
    cur.execute("SELECT value FROM settings WHERE key = %s", (key,))
    row = cur.fetchone()
    return row[0] if row else default


def project_count(cur, user_id: int) -> int:
    cur.execute("SELECT count(*) FROM projects WHERE owner_id = %s", (user_id,))
    return cur.fetchone()[0]


def client_ip(request: Request) -> str:
    """nginx 가 넣어 주는 X-Real-IP 를 쓴다 (클라이언트가 보낸 값은 nginx 가 덮어씀)."""
    return (request.headers.get("x-real-ip")
            or (request.client.host if request.client else "?"))


def fail_keys(username: str, ip: str) -> tuple[str, str]:
    return "u:%s@%s" % (username, ip), "ip:%s" % ip


def fmt_dur(secs: int) -> str:
    if secs < 60:
        return "%d초" % secs
    return "%d분" % (secs // 60) + (" %d초" % (secs % 60) if secs % 60 else "")


def lock_left(cur, keys) -> int:
    """잠겨 있으면 남은 초, 아니면 0."""
    cur.execute("""SELECT max(ceil(extract(epoch from (locked_until - now()))))
                   FROM login_attempts WHERE key = ANY(%s) AND locked_until > now()""",
                (list(keys),))
    return int(cur.fetchone()[0] or 0)


def bump_login_fail(username: str, ip: str) -> tuple[int, int]:
    """실패를 기록하고 (남은 시도, 이번에 걸린 잠금 초) 를 돌려준다.

    예외를 던지기 전에 커밋돼야 하므로 별도 트랜잭션으로 처리한다.
    잠금은 반복될수록 길어진다(LOGIN_LOCK_STEPS). 마지막 실패로부터
    LOGIN_LOCK_RESET_H 가 지나면 단계가 처음으로 돌아간다.
    """
    left, locked = LOGIN_MAX_FAILS, 0
    with pool.connection() as conn, conn.cursor() as cur:
        for k, limit in zip(fail_keys(username, ip), (LOGIN_MAX_FAILS, LOGIN_IP_MAX_FAILS)):
            cur.execute("""
                INSERT INTO login_attempts (key, fails, last_fail) VALUES (%s, 1, now())
                ON CONFLICT (key) DO UPDATE SET
                    fails = CASE WHEN login_attempts.last_fail > now() - make_interval(mins => %s)
                                 THEN login_attempts.fails + 1 ELSE 1 END,
                    locks = CASE WHEN login_attempts.last_fail > now() - make_interval(hours => %s)
                                 THEN login_attempts.locks ELSE 0 END,
                    last_fail = now()
                RETURNING fails, locks""",
                (k, LOGIN_FAIL_WINDOW_MIN, LOGIN_LOCK_RESET_H))
            fails, locks = cur.fetchone()
            if k.startswith("u:"):
                left = limit - fails
            if fails >= limit:
                secs = LOGIN_LOCK_STEPS[min(locks, len(LOGIN_LOCK_STEPS) - 1)]
                cur.execute("""UPDATE login_attempts
                                  SET fails = 0, locks = locks + 1,
                                      locked_until = now() + make_interval(secs => %s)
                                WHERE key = %s""", (secs, k))
                locked = max(locked, secs)
    return left, locked


def upload_usage(cur, owner_id: int, role: str):
    """소유자가 가진 모든 프로젝트의 이미지 총량(바이트)과 한도(바이트)."""
    cur.execute("""SELECT coalesce(sum(length(i.data)), 0)
                   FROM images i JOIN projects p ON p.id = i.project_id
                   WHERE p.owner_id = %s""", (owner_id,))
    mb = ROLE_UPLOAD_MB.get(role)
    return cur.fetchone()[0], (None if mb is None else mb * 1024 * 1024)


def check_access(cur, project_id: int, user: dict | None, share: str | None):
    """owner or valid share token may read/write project content."""
    cur.execute("SELECT owner_id, share_token FROM projects WHERE id = %s", (project_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "프로젝트가 없습니다")
    owner_id, token = row
    if user and user["id"] == owner_id:
        return
    if share and token and secrets.compare_digest(share, token):
        return
    raise HTTPException(403, "접근 권한이 없습니다 (공유 링크가 필요합니다)")


def check_owner(cur, project_id: int, user: dict):
    cur.execute("SELECT owner_id FROM projects WHERE id = %s", (project_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "프로젝트가 없습니다")
    if row[0] != user["id"]:
        raise HTTPException(403, "프로젝트 소유자만 가능합니다")


def node_project(cur, node_id: int) -> int:
    cur.execute("SELECT project_id FROM nodes WHERE id = %s", (node_id,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "기능 항목을 찾을 수 없습니다")
    return row[0]


def make_session(cur, user_id: int) -> str:
    token = secrets.token_hex(32)
    cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s)", (token, user_id))
    return token


@app.post("/api/auth/register", status_code=201)
def register(body: Credentials):
    """첫 계정은 곧바로 관리자, 그 뒤는 관리자 승인을 기다리는 대기 상태로 만든다."""
    name = body.username.strip()
    if not name or len(body.password) < 4:
        raise HTTPException(400, "사용자 이름과 4자 이상의 비밀번호가 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        first = cur.fetchone()[0] == 0
        if not first and get_setting(cur, "signup_open", "1") != "1":
            raise HTTPException(403, "지금은 신규 가입을 받지 않습니다. 관리자에게 문의하세요.")
        cur.execute("SELECT 1 FROM users WHERE username = %s", (name,))
        if cur.fetchone():
            raise HTTPException(409, "이미 존재하는 사용자 이름입니다")
        role, status = ("admin", "active") if first else ("guest", "pending")
        cur.execute("""INSERT INTO users (username, password, role, status)
                       VALUES (%s, %s, %s, %s) RETURNING id""",
                    (name, hash_pw(body.password), role, status))
        uid = cur.fetchone()[0]
        if status == "active":
            return {"token": make_session(cur, uid), "username": name, "role": role}
    return {"status": "pending", "username": name,
            "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다."}


@app.post("/api/auth/login")
def login(body: Credentials, request: Request):
    name = body.username.strip()
    ip = client_ip(request)
    ukey, ipkey = fail_keys(name, ip)
    with pool.connection() as conn, conn.cursor() as cur:
        # 잠금 기준은 (계정+IP) 또는 (IP). 계정 이름만으로는 잠그지 않아 남을 잠글 수 없다
        left_sec = lock_left(cur, (ukey, ipkey))
        cur.execute("SELECT id, password, role, status FROM users WHERE username = %s", (name,))
        u = cur.fetchone()

    if left_sec:
        raise HTTPException(429, "로그인 실패가 많아 이 위치에서 로그인이 제한됩니다."
                                 f" {fmt_dur(left_sec)} 뒤에 다시 시도하세요.")
    ok = bool(u) and secrets.compare_digest(
        hash_pw(body.password, u[1].split("$")[0]), u[1])
    if not ok:
        left, locked = bump_login_fail(name, ip)
        raise HTTPException(401, "사용자 이름 또는 비밀번호가 올바르지 않습니다"
                                 + (f" — {fmt_dur(locked)}간 로그인이 제한됩니다" if locked
                                    else f" (남은 시도 {left}회)"))
    if u[3] == "pending":
        raise HTTPException(403, "가입 승인 대기 중입니다. 관리자 승인 후 이용할 수 있습니다.")
    if u[3] != "active":
        raise HTTPException(403, "이 계정은 사용할 수 없습니다. 관리자에게 문의하세요.")

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM login_attempts WHERE key = ANY(%s)", ([ukey, ipkey],))
        return {"token": make_session(cur, u[0]), "username": name, "role": u[2]}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        used = project_count(cur, user["id"])
        up_used, up_limit = upload_usage(cur, user["id"], user["role"])
        cur.execute("SELECT avatar FROM users WHERE id = %s", (user["id"],))
        avatar = cur.fetchone()[0]
    return {"username": user["username"], "role": user["role"],
            "projects": used, "project_limit": ROLE_LIMITS.get(user["role"]),
            "upload_bytes": up_used, "upload_limit": up_limit, "avatar": avatar}


class AvatarIn(BaseModel):
    avatar: str | None = None            # data URL. None 이면 삭제


@app.put("/api/me/avatar", status_code=204)
def set_avatar(body: AvatarIn, user: dict = Depends(current_user)):
    """프로필 이미지. 프런트에서 128px 로 줄여 보내므로 users 행에 data URL 로 둔다."""
    av = body.avatar or None
    if av and not av.startswith("data:image/"):
        raise HTTPException(400, "이미지 파일만 등록할 수 있습니다")
    if av and len(av) > MAX_AVATAR_CHARS:
        raise HTTPException(413, "프로필 이미지가 너무 큽니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET avatar = %s WHERE id = %s", (av, user["id"]))


class PasswordChange(BaseModel):
    current: str
    password: str


@app.put("/api/me/password")
def change_my_password(body: PasswordChange, user: dict = Depends(current_user)):
    """현재 비밀번호를 확인하고 바꾼다. 다른 기기의 세션은 모두 끊고 새 토큰을 준다."""
    if len(body.password) < 4:
        raise HTTPException(400, "새 비밀번호는 4자 이상이어야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT password FROM users WHERE id = %s", (user["id"],))
        cur_hash = cur.fetchone()[0]
        if not secrets.compare_digest(hash_pw(body.current, cur_hash.split("$")[0]), cur_hash):
            raise HTTPException(403, "현재 비밀번호가 올바르지 않습니다")
        cur.execute("UPDATE users SET password = %s WHERE id = %s",
                    (hash_pw(body.password), user["id"]))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user["id"],))
        return {"token": make_session(cur, user["id"]),
                "username": user["username"], "role": user["role"]}


@app.post("/api/auth/logout", status_code=204)
def logout(authorization: str | None = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (authorization[7:],))


# ---------- admin ----------
class RoleIn(BaseModel):
    role: str


class PasswordIn(BaseModel):
    password: str


class SignupSwitch(BaseModel):
    signup_open: bool


def one_admin_left(cur, uid: int) -> bool:
    """uid 가 마지막 남은 관리자인지 (강등·삭제로 관리자가 사라지는 것을 막는다)"""
    cur.execute("SELECT count(*) FROM users WHERE role = 'admin' AND status = 'active'")
    total = cur.fetchone()[0]
    cur.execute("SELECT role FROM users WHERE id = %s", (uid,))
    row = cur.fetchone()
    return bool(row) and row[0] == "admin" and total <= 1


def with_limits(rows):
    for r in rows:
        r["project_limit"] = ROLE_LIMITS.get(r["role"])
        mb = ROLE_UPLOAD_MB.get(r["role"])
        r["upload_limit"] = None if mb is None else mb * 1024 * 1024
    return rows


@app.get("/api/admin/users")
def admin_list_users(_: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT u.id, u.username, u.role, u.status, u.created_at,
                              (SELECT count(*) FROM projects p WHERE p.owner_id = u.id) AS projects,
                              (SELECT coalesce(sum(length(i.data)), 0)
                                 FROM images i JOIN projects p2 ON p2.id = i.project_id
                                WHERE p2.owner_id = u.id) AS upload_bytes
                       FROM users u WHERE u.status <> 'pending' ORDER BY u.id""")
        return with_limits(rows_to_dicts(cur))


@app.get("/api/admin/signups")
def admin_list_signups(_: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, username, created_at FROM users
                       WHERE status = 'pending' ORDER BY created_at""")
        return rows_to_dicts(cur)


@app.post("/api/admin/signups/{uid}/approve")
def admin_approve(uid: int, body: RoleIn, _: dict = Depends(admin_user)):
    if body.role not in ROLE_LIMITS:
        raise HTTPException(400, "등급이 올바르지 않습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE users SET status = 'active', role = %s
                       WHERE id = %s AND status = 'pending' RETURNING username""",
                    (body.role, uid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "대기 중인 신청이 없습니다")
        return {"username": row[0], "role": body.role}


@app.post("/api/admin/signups/{uid}/reject", status_code=204)
def admin_reject(uid: int, _: dict = Depends(admin_user)):
    """거절은 계정을 지운다. 같은 이름으로 다시 신청할 수 있다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE id = %s AND status = 'pending'", (uid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "대기 중인 신청이 없습니다")


@app.put("/api/admin/users/{uid}/role")
def admin_set_role(uid: int, body: RoleIn, _: dict = Depends(admin_user)):
    if body.role not in ROLE_LIMITS:
        raise HTTPException(400, "등급이 올바르지 않습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        if body.role != "admin" and one_admin_left(cur, uid):
            raise HTTPException(400, "마지막 관리자 계정의 등급은 내릴 수 없습니다")
        cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING username",
                    (body.role, uid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        return {"username": row[0], "role": body.role, "project_limit": ROLE_LIMITS[body.role]}


@app.put("/api/admin/users/{uid}/password", status_code=204)
def admin_set_password(uid: int, body: PasswordIn, _: dict = Depends(admin_user)):
    """관리자 계정을 포함해 어떤 계정의 비밀번호도 바꾼다. 기존 세션은 모두 끊는다."""
    if len(body.password) < 4:
        raise HTTPException(400, "비밀번호는 4자 이상이어야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT username FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        cur.execute("UPDATE users SET password = %s WHERE id = %s",
                    (hash_pw(body.password), uid))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
        cur.execute("DELETE FROM login_attempts WHERE key LIKE %s", ("u:" + row[0] + "@%",))


@app.delete("/api/admin/users/{uid}", status_code=204)
def admin_delete_user(uid: int, admin: dict = Depends(admin_user)):
    """계정과 그 계정의 프로젝트·이미지·코멘트까지 DB 에서 완전히 지운다 (FK CASCADE)."""
    if uid == admin["id"]:
        raise HTTPException(400, "자기 계정은 삭제할 수 없습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        if one_admin_left(cur, uid):
            raise HTTPException(400, "마지막 관리자 계정은 삭제할 수 없습니다")
        cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "계정을 찾을 수 없습니다")


@app.get("/api/admin/users/{uid}/projects")
def admin_user_projects(uid: int, _: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT username, role FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        cur.execute("""SELECT p.id, p.name, p.share_token IS NOT NULL AS shared,
                              (SELECT count(*) FROM nodes n WHERE n.project_id = p.id) AS nodes,
                              (SELECT count(*) FROM images i WHERE i.project_id = p.id) AS images
                       FROM projects p WHERE p.owner_id = %s ORDER BY p.id""", (uid,))
        return {"username": row[0], "role": row[1], "project_limit": ROLE_LIMITS.get(row[1]),
                "projects": rows_to_dicts(cur)}


@app.delete("/api/admin/projects/{pid}", status_code=204)
def admin_delete_project(pid: int, _: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM projects WHERE id = %s", (pid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "프로젝트를 찾을 수 없습니다")


@app.get("/api/admin/settings")
def admin_get_settings(_: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        return {"signup_open": get_setting(cur, "signup_open", "1") == "1",
                "role_limits": ROLE_LIMITS, "upload_limits_mb": ROLE_UPLOAD_MB,
                "login_max_fails": LOGIN_MAX_FAILS, "login_ip_max_fails": LOGIN_IP_MAX_FAILS,
                "login_lock_steps": LOGIN_LOCK_STEPS}


@app.put("/api/admin/settings")
def admin_put_settings(body: SignupSwitch, _: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO settings (key, value) VALUES ('signup_open', %s)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    ("1" if body.signup_open else "0",))
    return {"signup_open": body.signup_open}


@app.get("/api/signup-open")
def signup_open():
    """로그인 화면에서 가입 버튼을 보여줄지 판단하는 공개 엔드포인트."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        first = cur.fetchone()[0] == 0
        return {"open": first or get_setting(cur, "signup_open", "1") == "1"}


# ---------- projects ----------
class ProjectIn(BaseModel):
    name: str


@app.get("/api/projects")
def list_projects(user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, name, share_token FROM projects
                       WHERE owner_id = %s ORDER BY id""", (user["id"],))
        return rows_to_dicts(cur)


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, user: dict = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "이름이 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        limit = ROLE_LIMITS.get(user["role"], 1)
        if limit is not None and project_count(cur, user["id"]) >= limit:
            raise HTTPException(403, f"{user['role']} 등급은 프로젝트를 최대 {limit}개까지"
                                     " 만들 수 있습니다. 관리자에게 등급 상향을 요청하세요.")
        cur.execute("""INSERT INTO projects (owner_id, name, prd) VALUES (%s, %s, %s)
                       RETURNING id, name, share_token""",
                    (user["id"], body.name.strip(), PRD_TEMPLATE))
        return rows_to_dicts(cur)[0]


@app.put("/api/projects/{pid}")
def rename_project(pid: int, body: ProjectIn, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_owner(cur, pid, user)
        cur.execute("UPDATE projects SET name = %s WHERE id = %s", (body.name.strip(), pid))
    return {"ok": True}


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_owner(cur, pid, user)
        cur.execute("DELETE FROM projects WHERE id = %s", (pid,))


@app.post("/api/projects/{pid}/share", status_code=201)
def create_share(pid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_owner(cur, pid, user)
        token = secrets.token_urlsafe(24)
        cur.execute("UPDATE projects SET share_token = %s WHERE id = %s", (token, pid))
        return {"share_token": token}


@app.delete("/api/projects/{pid}/share", status_code=204)
def delete_share(pid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_owner(cur, pid, user)
        cur.execute("UPDATE projects SET share_token = NULL WHERE id = %s", (pid,))


@app.get("/api/shared/{token}")
def resolve_share(token: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM projects WHERE share_token = %s", (token,))
        rows = rows_to_dicts(cur)
        if not rows:
            raise HTTPException(404, "유효하지 않은 공유 링크입니다")
        return rows[0]


# ---------- prd ----------
class PrdIn(BaseModel):
    content: str


@app.get("/api/projects/{pid}/prd")
def get_prd(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
        return {"content": cur.fetchone()[0]}


@app.put("/api/projects/{pid}/prd")
def put_prd(pid: int, body: PrdIn, share: str | None = None,
            user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("UPDATE projects SET prd = %s WHERE id = %s", (body.content, pid))
    return {"ok": True}


# ---------- nodes ----------
class NodeIn(BaseModel):
    parent_id: int | None = None
    title: str = "새 기능"


class NodeUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    importance: int | None = None
    sort_order: int | None = None
    parent_id: int | None = None


@app.get("/api/projects/{pid}/nodes")
def list_nodes(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("SELECT * FROM nodes WHERE project_id = %s ORDER BY sort_order, id", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/nodes", status_code=201)
def create_node(pid: int, body: NodeIn, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        if body.parent_id is not None and node_project(cur, body.parent_id) != pid:
            raise HTTPException(400, "다른 프로젝트의 항목 아래에는 추가할 수 없습니다")
        cur.execute(
            """INSERT INTO nodes (project_id, parent_id, title, sort_order)
               VALUES (%s, %s, %s, (SELECT coalesce(max(sort_order), -1) + 1 FROM nodes
                                    WHERE project_id = %s
                                    AND parent_id IS NOT DISTINCT FROM %s))
               RETURNING *""",
            (pid, body.parent_id, body.title, pid, body.parent_id))
        return rows_to_dicts(cur)[0]


@app.put("/api/nodes/{node_id}")
def update_node(node_id: int, body: NodeUpdate, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields")
    with pool.connection() as conn, conn.cursor() as cur:
        pid = node_project(cur, node_id)
        check_access(cur, pid, user, share)
        if "parent_id" in fields:
            new_pid = fields["parent_id"]
            if new_pid == node_id:
                raise HTTPException(400, "cannot be its own parent")
            if new_pid is not None:
                if node_project(cur, new_pid) != pid:
                    raise HTTPException(400, "다른 프로젝트로는 이동할 수 없습니다")
                cur.execute("""
                    WITH RECURSIVE sub AS (
                        SELECT id FROM nodes WHERE id = %s
                        UNION ALL
                        SELECT n.id FROM nodes n JOIN sub s ON n.parent_id = s.id)
                    SELECT 1 FROM sub WHERE id = %s""", (node_id, new_pid))
                if cur.fetchone():
                    raise HTTPException(400, "cannot move a node into its own subtree")
            if "sort_order" not in fields:
                cur.execute("""SELECT coalesce(max(sort_order), -1) + 1 FROM nodes
                               WHERE project_id = %s AND parent_id IS NOT DISTINCT FROM %s""",
                            (pid, new_pid))
                fields["sort_order"] = cur.fetchone()[0]
        sets = ", ".join(f"{k} = %s" for k in fields)
        cur.execute(f"UPDATE nodes SET {sets} WHERE id = %s RETURNING *",
                    (*fields.values(), node_id))
        return rows_to_dicts(cur)[0]


@app.delete("/api/nodes/{node_id}", status_code=204)
def delete_node(node_id: int, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, node_project(cur, node_id), user, share)
        cur.execute("DELETE FROM nodes WHERE id = %s", (node_id,))


# ---------- 용어 사전 ----------
TERM_RE = re.compile(r"`([^`\n]{1,60})`")


class TermIn(BaseModel):
    description: str | None = None
    category_id: int | None = None
    sort_order: int | None = None


def sync_terms(cur, pid: int):
    """본문(PRD·기능 설명)에 있는 `용어` 를 훑어 없는 건 만들고, 안 쓰이는 건 지운다."""
    cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
    texts = [cur.fetchone()[0]]
    cur.execute("SELECT description FROM nodes WHERE project_id = %s"
                " ORDER BY sort_order, id", (pid,))
    texts += [r[0] for r in cur.fetchall()]

    # 본문에 나온 순서대로 (추가 순서가 곧 기본 정렬)
    found, seen = [], set()
    for t in texts:
        for m in TERM_RE.finditer(t or ""):
            w = m.group(1).strip()
            if w and w not in seen:
                seen.add(w)
                found.append(w)
    for term in found:
        cur.execute("""INSERT INTO terms (project_id, term, sort_order)
                       VALUES (%s, %s, (SELECT coalesce(max(sort_order), -1) + 1
                                        FROM terms WHERE project_id = %s))
                       ON CONFLICT (project_id, term) DO NOTHING""", (pid, term, pid))
    cur.execute("DELETE FROM terms WHERE project_id = %s AND NOT (term = ANY(%s))",
                (pid, list(found) or [""]))


@app.get("/api/projects/{pid}/terms")
def list_terms(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        sync_terms(cur, pid)
        cur.execute("""
            SELECT t.id, t.term, t.description, t.category_id, t.sort_order,
                   EXISTS (SELECT 1 FROM projects p WHERE p.id = t.project_id
                           AND position('`' || t.term || '`' in p.prd) > 0) AS in_prd,
                   (SELECT coalesce(json_agg(json_build_object('id', n.id, 'title', n.title)
                                             ORDER BY n.sort_order, n.id), '[]'::json)
                    FROM nodes n WHERE n.project_id = t.project_id
                      AND position('`' || t.term || '`' in n.description) > 0) AS nodes
            FROM terms t WHERE t.project_id = %s
            ORDER BY t.sort_order, t.id""", (pid,))
        return rows_to_dicts(cur)


@app.put("/api/terms/{tid}")
def update_term(tid: int, body: TermIn, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id FROM terms WHERE id = %s", (tid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "용어를 찾을 수 없습니다")
        check_access(cur, row[0], user, share)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise HTTPException(400, "no fields")
        sets = ", ".join(f"{k} = %s" for k in fields)
        cur.execute(f"UPDATE terms SET {sets} WHERE id = %s"
                    " RETURNING id, term, description, category_id, sort_order",
                    (*fields.values(), tid))
        return rows_to_dicts(cur)[0]


class CategoryIn(BaseModel):
    name: str


@app.get("/api/projects/{pid}/term-categories")
def list_categories(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("SELECT id, name FROM term_categories WHERE project_id = %s ORDER BY id", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/term-categories", status_code=201)
def create_category(pid: int, body: CategoryIn, share: str | None = None,
                    user: dict | None = Depends(opt_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "카테고리 이름이 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("""INSERT INTO term_categories (project_id, name) VALUES (%s, %s)
                       ON CONFLICT (project_id, name) DO UPDATE SET name = EXCLUDED.name
                       RETURNING id, name""", (pid, name))
        return rows_to_dicts(cur)[0]


@app.delete("/api/term-categories/{cid}", status_code=204)
def delete_category(cid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    """카테고리만 지운다. 속해 있던 용어는 미분류로 남는다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id FROM term_categories WHERE id = %s", (cid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "카테고리를 찾을 수 없습니다")
        check_access(cur, row[0], user, share)
        cur.execute("DELETE FROM term_categories WHERE id = %s", (cid,))


# ---------- versions (PRD + 기능명세서 스냅샷) ----------
NODE_FIELDS = ("id", "parent_id", "title", "description", "status", "importance", "sort_order")


@app.post("/api/projects/{pid}/versions", status_code=201)
def save_version(pid: int, share: str | None = None, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute(f"SELECT {', '.join(NODE_FIELDS)} FROM nodes WHERE project_id = %s"
                    " ORDER BY sort_order, id", (pid,))
        snapshot = rows_to_dicts(cur)
        cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
        prd = cur.fetchone()[0]
        cur.execute("""INSERT INTO versions (project_id, user_id, username, data, prd)
                       VALUES (%s, %s, %s, %s, %s) RETURNING id, created_at""",
                    (pid, user["id"], user["username"], json.dumps(snapshot), prd))
        vid, created = cur.fetchone()
    return {"id": vid, "created_at": created, "username": user["username"],
            "node_count": len(snapshot)}


@app.get("/api/projects/{pid}/versions")
def list_versions(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("""SELECT id, username, created_at, jsonb_array_length(data) AS node_count
                       FROM versions WHERE project_id = %s ORDER BY created_at DESC""", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/versions/{vid}/restore")
def restore_version(vid: int, share: str | None = None, user: dict = Depends(current_user)):
    """PRD 와 기능 트리를 그 시점으로 되돌린다. 살아남는 항목은 id 를 유지해 코멘트가 보존된다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id, data, prd FROM versions WHERE id = %s", (vid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        pid, snapshot, prd = row
        check_access(cur, pid, user, share)
        if prd is not None:
            cur.execute("UPDATE projects SET prd = %s WHERE id = %s", (prd, pid))

        by_id = {n["id"]: n for n in snapshot}
        cur.execute("DELETE FROM nodes WHERE project_id = %s AND NOT (id = ANY(%s))",
                    (pid, list(by_id) or [0]))

        def depth(n):  # 부모를 먼저 넣어야 외래키가 걸리지 않는다
            d, cur_n = 0, n
            while cur_n and cur_n["parent_id"] is not None:
                cur_n = by_id.get(cur_n["parent_id"])
                d += 1
            return d

        for n in sorted(snapshot, key=depth):
            cur.execute("""
                INSERT INTO nodes (id, project_id, parent_id, title, description,
                                   status, importance, sort_order)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    parent_id = EXCLUDED.parent_id, title = EXCLUDED.title,
                    description = EXCLUDED.description, status = EXCLUDED.status,
                    importance = EXCLUDED.importance, sort_order = EXCLUDED.sort_order
                WHERE nodes.project_id = EXCLUDED.project_id""",
                (n["id"], pid, n["parent_id"], n["title"], n["description"],
                 n["status"], n["importance"], n["sort_order"]))
        cur.execute("""SELECT setval(pg_get_serial_sequence('nodes', 'id'),
                       GREATEST((SELECT coalesce(max(id), 1) FROM nodes), 1))""")
    return {"restored": len(snapshot)}


@app.delete("/api/versions/{vid}", status_code=204)
def delete_version(vid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id FROM versions WHERE id = %s", (vid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        check_owner(cur, row[0], user)
        cur.execute("DELETE FROM versions WHERE id = %s", (vid,))


# ---------- images ----------
MAX_IMAGE_BYTES = 5 * 1024 * 1024


@app.post("/api/projects/{pid}/images", status_code=201)
async def upload_image(pid: int, request: Request, share: str | None = None,
                       user: dict | None = Depends(opt_user)):
    mime = request.headers.get("content-type", "")
    if not mime.startswith("image/"):
        raise HTTPException(400, "이미지 파일만 올릴 수 있습니다")
    data = await request.body()
    if not data:
        raise HTTPException(400, "빈 파일입니다")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "이미지는 5MB 이하만 올릴 수 있습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        # 총량은 프로젝트 소유자 기준 (공유 링크로 올려도 소유자 몫에서 차감된다)
        cur.execute("""SELECT p.owner_id, u.role FROM projects p
                       JOIN users u ON u.id = p.owner_id WHERE p.id = %s""", (pid,))
        owner_id, owner_role = cur.fetchone()
        up_used, up_limit = upload_usage(cur, owner_id, owner_role)
        if up_limit is not None and up_used + len(data) > up_limit:
            raise HTTPException(413,
                "이미지 저장 용량을 초과했습니다"
                " (%dMB / %dMB). 앨범에서 쓰지 않는 이미지를 지우거나"
                " 관리자에게 등급 상향을 요청하세요."
                % (up_used // (1024 * 1024), up_limit // (1024 * 1024)))
        img_id = secrets.token_urlsafe(16)
        cur.execute("INSERT INTO images (id, project_id, mime, data) VALUES (%s, %s, %s, %s)",
                    (img_id, pid, mime.split(";")[0], data))
    return {"url": f"/api/images/{img_id}"}


class ImageIds(BaseModel):
    ids: list[str]


@app.get("/api/projects/{pid}/images")
def list_images(pid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    """앨범 목록. used = 본문(PRD·기능 설명)에서 링크로 쓰이는 중인지."""
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("""
            SELECT i.id, i.mime, i.created_at, length(i.data) AS bytes,
                   (EXISTS (SELECT 1 FROM projects p
                            WHERE p.id = i.project_id
                              AND position('/api/images/' || i.id in p.prd) > 0)
                    OR EXISTS (SELECT 1 FROM nodes n
                               WHERE n.project_id = i.project_id
                                 AND position('/api/images/' || i.id in n.description) > 0)) AS used
            FROM images i WHERE i.project_id = %s
            ORDER BY i.created_at DESC, i.id""", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/images/delete")
def delete_images(pid: int, body: ImageIds, share: str | None = None,
                  user: dict = Depends(current_user)):
    if not body.ids:
        raise HTTPException(400, "선택된 이미지가 없습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute("DELETE FROM images WHERE project_id = %s AND id = ANY(%s)"
                    " RETURNING length(data)", (pid, body.ids))
        sizes = [r[0] for r in cur.fetchall()]
    return {"deleted": len(sizes), "bytes": sum(sizes)}


@app.get("/api/images/{img_id}")
def get_image(img_id: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT mime, data FROM images WHERE id = %s", (img_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    return Response(content=bytes(row[1]), media_type=row[0],
                    headers={"Cache-Control": "public, max-age=31536000"})


# ---------- comments ----------
class CommentIn(BaseModel):
    content: str


@app.get("/api/nodes/{node_id}/comments")
def list_comments(node_id: int, share: str | None = None,
                  user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, node_project(cur, node_id), user, share)
        cur.execute("""SELECT c.id, c.node_id, u.username, u.avatar, c.content, c.created_at
                       FROM comments c JOIN users u ON u.id = c.user_id
                       WHERE c.node_id = %s ORDER BY c.created_at""", (node_id,))
        return rows_to_dicts(cur)


@app.post("/api/nodes/{node_id}/comments", status_code=201)
def create_comment(node_id: int, body: CommentIn, share: str | None = None,
                   user: dict = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "empty comment")
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, node_project(cur, node_id), user, share)
        cur.execute("""INSERT INTO comments (node_id, user_id, content)
                       VALUES (%s, %s, %s) RETURNING id, node_id, content, created_at""",
                    (node_id, user["id"], body.content.strip()))
        return {**rows_to_dicts(cur)[0], "username": user["username"]}


@app.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM comments WHERE id = %s AND user_id = %s",
                    (comment_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "본인 코멘트만 삭제할 수 있습니다")


# ---------- MCP (/mcp) ----------
# 위 핸들러들을 재사용하므로 정의가 끝난 이 자리에서 import 한다.
import mcp_app  # noqa: E402

app.mount("/mcp", mcp_app.asgi_app())
