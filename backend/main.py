import hashlib
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

pool = ConnectionPool(os.environ["DATABASE_URL"])
app = FastAPI()

PRD_TEMPLATE = "# PRD\n\n## 개요\n\n내용을 작성하세요.\n"


@app.on_event("startup")
def init_db():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id serial PRIMARY KEY,
                username text NOT NULL UNIQUE,
                password text NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token text PRIMARY KEY,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS projects (
                id serial PRIMARY KEY,
                owner_id int REFERENCES users(id) ON DELETE CASCADE,
                name text NOT NULL,
                prd text NOT NULL DEFAULT '',
                share_token text
            );
            CREATE TABLE IF NOT EXISTS nodes (
                id serial PRIMARY KEY,
                parent_id int REFERENCES nodes(id) ON DELETE CASCADE,
                title text NOT NULL,
                description text NOT NULL DEFAULT '',
                status text NOT NULL DEFAULT '기획 작성중',
                importance int NOT NULL DEFAULT 2,
                sort_order int NOT NULL DEFAULT 0
            );
            ALTER TABLE nodes ADD COLUMN IF NOT EXISTS
                project_id int REFERENCES projects(id) ON DELETE CASCADE;
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
        cur.execute("""SELECT u.id, u.username FROM sessions s
                       JOIN users u ON u.id = s.user_id WHERE s.token = %s""",
                    (authorization[7:],))
        row = cur.fetchone()
    return {"id": row[0], "username": row[1]} if row else None


def current_user(user: dict | None = Depends(opt_user)) -> dict:
    if not user:
        raise HTTPException(401, "로그인이 필요합니다")
    return user


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
        raise HTTPException(404, "not found")
    return row[0]


def make_session(cur, user_id: int) -> str:
    token = secrets.token_hex(32)
    cur.execute("INSERT INTO sessions (token, user_id) VALUES (%s, %s)", (token, user_id))
    return token


@app.post("/api/auth/register", status_code=201)
def register(body: Credentials):
    if not body.username.strip() or len(body.password) < 4:
        raise HTTPException(400, "사용자 이름과 4자 이상의 비밀번호가 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE username = %s", (body.username,))
        if cur.fetchone():
            raise HTTPException(409, "이미 존재하는 사용자 이름입니다")
        cur.execute("INSERT INTO users (username, password) VALUES (%s, %s) RETURNING id",
                    (body.username.strip(), hash_pw(body.password)))
        return {"token": make_session(cur, cur.fetchone()[0]), "username": body.username.strip()}


@app.post("/api/auth/login")
def login(body: Credentials):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, password FROM users WHERE username = %s", (body.username,))
        row = cur.fetchone()
        if not row or not secrets.compare_digest(
                hash_pw(body.password, row[1].split("$")[0]), row[1]):
            raise HTTPException(401, "사용자 이름 또는 비밀번호가 올바르지 않습니다")
        return {"token": make_session(cur, row[0]), "username": body.username}


@app.post("/api/auth/logout", status_code=204)
def logout(authorization: str | None = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token = %s", (authorization[7:],))


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


# ---------- comments ----------
class CommentIn(BaseModel):
    content: str


@app.get("/api/nodes/{node_id}/comments")
def list_comments(node_id: int, share: str | None = None,
                  user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, node_project(cur, node_id), user, share)
        cur.execute("""SELECT c.id, c.node_id, u.username, c.content, c.created_at
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
