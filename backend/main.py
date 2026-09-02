import hashlib
import json
import os
import re
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
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
            CREATE TABLE IF NOT EXISTS versions (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id int REFERENCES users(id) ON DELETE SET NULL,
                username text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                data jsonb NOT NULL
            );
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
                project_id int REFERENCES projects(id) ON DELETE CASCADE,
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


# ---------- versions (기능명세서 스냅샷) ----------
NODE_FIELDS = ("id", "parent_id", "title", "description", "status", "importance", "sort_order")


@app.post("/api/projects/{pid}/versions", status_code=201)
def save_version(pid: int, share: str | None = None, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, pid, user, share)
        cur.execute(f"SELECT {', '.join(NODE_FIELDS)} FROM nodes WHERE project_id = %s"
                    " ORDER BY sort_order, id", (pid,))
        snapshot = rows_to_dicts(cur)
        cur.execute("""INSERT INTO versions (project_id, user_id, username, data)
                       VALUES (%s, %s, %s, %s) RETURNING id, created_at""",
                    (pid, user["id"], user["username"], json.dumps(snapshot)))
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
    """스냅샷 상태로 되돌린다. 살아남는 항목은 id 를 유지해 코멘트가 보존된다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id, data FROM versions WHERE id = %s", (vid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        pid, snapshot = row
        check_access(cur, pid, user, share)

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
        raise HTTPException(404, "not found")
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
