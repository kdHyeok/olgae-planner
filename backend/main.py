import hashlib
import os
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from psycopg_pool import ConnectionPool
from pydantic import BaseModel

pool = ConnectionPool(os.environ["DATABASE_URL"])
app = FastAPI()

SEED_PRD = """# PRD

## 개요

### 한 줄 정의
실제 TESS 광도곡선을 직접 분석하고 외계행성 후보를 함께 찾아가는 시민과학형 탐색 서비스

### 제품 목표
전문 천문 데이터 분석의 진입 장벽을 낮춰 일반 사용자가 실제 관측 데이터를 탐색하고 후보 판정에 참여하게 한다.

탐색 결과를 검증 가능한 형태로 축적하여 새로운 외계행성 후보의 발견과 후속 연구에 기여할 수 있는 기반을 만든다.

### 배경
과학은 새로운 관측 데이터가 축적될수록 기존 이론을 검증하고 발전시키며, 아직 풀리지 않은 근본적인 질문에 더 가까이 다가갈 수 있다.

외계행성을 더 많이 발견할수록 행성의 형성과 진화, 지구와 같은 행성의 보편성, 생명체가 존재할 수 있는 환경에 대한 새로운 관측 데이터가 축적된다.

외계행성 탐색은 광도곡선과 BLS 같은 분석 개념을 이해해야 하므로 일반 사용자가 참여하기 어렵다.

따라서 외계행성 탐색의 장벽을 낮추고 더 많은 사람이 더 많은 데이터를 효율적으로 탐색할 수 있도록 한다면, 새로운 외계행성의 발견 가능성을 높이고 궁극적으로 우주와 생명에 대한 과학적 이해의 발전을 가속할 수 있다.

## 문제 및 해결 방안

### 사용자 문제
천문학 비전문가는 실제 관측 데이터의 의미와 분석 방법을 알기 어렵고, 기존 분석 도구는 설치·파라미터 설정·결과 해석의 부담이 크다. 분석을 마쳐도 자신의 판단을 기존 결과와 비교하거나 다른 사용자와 논의하고 후속 제보로 연결할 일관된 경로가 부족하다.

### 해결 방안
동일한 튜토리얼 별에서 시작하여 개인 별 지도에서 탐색 대상을 선택하고, 기본 BLS 결과와 주기 조절·구간 드래그 기반의 수동 광도곡선 분석을 함께 제공한다. 사용자는 행성 후보 유무와 선택한 주기·통과 지속시간을 제출하고 기존 결과와 비교한다. 미확인 후보나 알려진 후보와 다른 신호는 추가 검증 및 연구기관 제보를 준비할 수 있게 지원하며, 별·후보 단위 커뮤니티에서 분석 근거를 공유한다.

### 차별점
자동 판정 결과만 보여주는 서비스가 아니라 사용자가 실제 TESS 데이터를 직접 조작하고 판단하는 경험을 중심에 둔다. 탐색 완료에 따라 개인 별 지도가 밝아지고 확장되는 시각적 보상으로 반복 참여를 유도하며, 개인 판정·기존 결과 비교·커뮤니티 검토·후속 제보 준비를 하나의 흐름으로 연결한다.

## 타겟 및 시나리오

### 타겟 사용자
우주와 외계행성에 관심이 있지만 전문 분석 도구 경험은 적은 일반 사용자와 학생, 실제 관측 데이터를 활용한 시민과학 활동에 참여하려는 천문 동호인. 초기 버전은 웹 브라우저에서 그래프를 직접 조작할 수 있는 사용자를 우선 대상으로 한다.

### 사용자 시나리오
사용자는 별이 수놓인 랜딩 페이지에서 로그인한 뒤 공통 튜토리얼 별을 분석한다. 개인 별 지도에서 흐린 별을 선택하고 기본 BLS 결과와 수동 주기 조절, 통과 구간 선택을 이용해 광도곡선을 탐색한다. 후보 유무를 제출한 뒤 기존 판정과 비교하거나 신규 후보의 후속 검증·제보 준비로 이동하고, 별 또는 후보 게시글에서 의견을 공유한다. 완료한 별은 밝게 등록되고 주변에 새 탐색 대상이 나타나면서 같은 흐름을 반복한다.

## 성공·위험 요소

### 핵심 지표
튜토리얼 완료율, 첫 번째 별 판정 완료율, 사용자당 탐색 완료 별 수, 탐색 시작 대비 판정 제출률, 재방문 및 반복 탐색률, 기존 판정과의 일치율, 신규 후보 후속 검토 전환 수, 근거가 연결된 커뮤니티 참여율을 측정한다. 목표 수치는 파일럿 운영 데이터로 정한다.

### 리스크
광도곡선과 BLS만으로 실제 행성을 확정할 수 없으므로 모든 결과를 '행성 후보'로 명시하고 과학적 확정으로 오인되지 않게 해야 한다. 신규 후보 제보에는 중복·오탐·품질 검토가 필요하며 연구기관이 결과를 수용한다는 보장은 없다. BLS 재분석의 계산 비용과 응답 시간이 사용자 증가 시 병목이 될 수 있으므로 처리량은 실제 운영 환경 부하 시험 전까지 보장하지 않는다. 관측 데이터 출처·라이선스·인용 정책과 커뮤니티 운영 기준도 별도로 확정해야 한다.

## 속성 설정

- 사용자 역할: 탐색 사용자, 운영자
- 기기: 데스크톱 웹, 모바일 웹
"""

SEED_TREE = [
    ("서비스 진입 및 튜토리얼",
     "- 별이 수놓인 형태의 랜딩 페이지를 제공합니다.\n- 로그인 후 사용자의 나만의 별 페이지로 이동합니다.\n- 처음 시작하는 사용자는 모두 동일한 튜토리얼 별을 탐색합니다.\n- 튜토리얼 완료 후 각 사용자에게 서로 다른 탐색 별이 제공됩니다.",
     ["랜딩 페이지", "로그인", "공통 튜토리얼 별"]),
    ("나만의 별 페이지", "",
     ["랜덤 생성 미탐색 별", "탐색 중인 별", "탐색 완료 별"]),
    ("광도곡선 분석", "",
     ["기본 BLS 분석 결과 제공", "수동 광도곡선 탐색", "개인 선택 값 기반 BLS 분석 제공", "사용자 판정 제출"]),
    ("주간 과제 별찾기", "", ["정밀 BLS 제공"]),
    ("별·후보 커뮤니티", "", []),
    ("연구소 제보",
     "### 제보 버튼 생성 조건\n- 아직 행성 유무가 판정되지 않은 별에서 행성 후보를 발견한 경우\n- 이미 행성이 알려진 별에서 기존 행성과 다른 주기의 추가 후보를 발견한 경우\n\n### 제보 지원 내용\n- 대상 별의 기본 정보 정리\n- 사용자가 선택한 주기와 통과 지속시간 정리\n- 광도곡선과 BLS 분석 결과 첨부\n- 기존에 알려진 후보와의 차이 안내\n- 제보에 필요한 설명문 작성 지원\n- 관련 연구기관 또는 제보 경로 안내",
     []),
    ("행성 위키", "", []),
]


@app.on_event("startup")
def init_db():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prd (
                id int PRIMARY KEY DEFAULT 1,
                content text NOT NULL DEFAULT ''
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
            CREATE TABLE IF NOT EXISTS users (
                id serial PRIMARY KEY,
                username text NOT NULL UNIQUE,
                password text NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token text PRIMARY KEY,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS comments (
                id serial PRIMARY KEY,
                node_id int NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                content text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            );
        """)
        cur.execute("SELECT count(*) FROM prd")
        if cur.fetchone()[0] == 0:
            cur.execute("INSERT INTO prd (id, content) VALUES (1, %s)", (SEED_PRD,))
        cur.execute("SELECT count(*) FROM nodes")
        if cur.fetchone()[0] == 0:
            for i, (title, desc, children) in enumerate(SEED_TREE):
                cur.execute(
                    "INSERT INTO nodes (title, description, sort_order) VALUES (%s, %s, %s) RETURNING id",
                    (title, desc, i))
                pid = cur.fetchone()[0]
                for j, child in enumerate(children):
                    cur.execute(
                        "INSERT INTO nodes (parent_id, title, sort_order) VALUES (%s, %s, %s)",
                        (pid, child, j))


class PrdIn(BaseModel):
    content: str


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


def rows_to_dicts(cur):
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


@app.get("/api/prd")
def get_prd():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT content FROM prd WHERE id = 1")
        return {"content": cur.fetchone()[0]}


@app.put("/api/prd")
def put_prd(body: PrdIn):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE prd SET content = %s WHERE id = 1", (body.content,))
    return {"ok": True}


@app.get("/api/nodes")
def list_nodes():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM nodes ORDER BY sort_order, id")
        return rows_to_dicts(cur)


@app.post("/api/nodes", status_code=201)
def create_node(body: NodeIn):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO nodes (parent_id, title, sort_order)
               VALUES (%s, %s, (SELECT coalesce(max(sort_order), -1) + 1 FROM nodes
                                WHERE parent_id IS NOT DISTINCT FROM %s))
               RETURNING *""",
            (body.parent_id, body.title, body.parent_id))
        return rows_to_dicts(cur)[0]


@app.put("/api/nodes/{node_id}")
def update_node(node_id: int, body: NodeUpdate):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields")
    with pool.connection() as conn, conn.cursor() as cur:
        if "parent_id" in fields:
            pid = fields["parent_id"]
            if pid == node_id:
                raise HTTPException(400, "cannot be its own parent")
            if pid is not None:
                # new parent must not be inside the moved node's subtree
                cur.execute("""
                    WITH RECURSIVE sub AS (
                        SELECT id FROM nodes WHERE id = %s
                        UNION ALL
                        SELECT n.id FROM nodes n JOIN sub s ON n.parent_id = s.id)
                    SELECT 1 FROM sub WHERE id = %s""", (node_id, pid))
                if cur.fetchone():
                    raise HTTPException(400, "cannot move a node into its own subtree")
            if "sort_order" not in fields:
                cur.execute("""SELECT coalesce(max(sort_order), -1) + 1 FROM nodes
                               WHERE parent_id IS NOT DISTINCT FROM %s""", (pid,))
                fields["sort_order"] = cur.fetchone()[0]
        sets = ", ".join(f"{k} = %s" for k in fields)
        cur.execute(f"UPDATE nodes SET {sets} WHERE id = %s RETURNING *",
                    (*fields.values(), node_id))
        rows = rows_to_dicts(cur)
        if not rows:
            raise HTTPException(404, "not found")
        return rows[0]


@app.delete("/api/nodes/{node_id}", status_code=204)
def delete_node(node_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM nodes WHERE id = %s", (node_id,))
        if cur.rowcount == 0:
            raise HTTPException(404, "not found")


# ---------- auth ----------
class Credentials(BaseModel):
    username: str
    password: str


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"


def current_user(authorization: str | None = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "login required")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT u.id, u.username FROM sessions s
                       JOIN users u ON u.id = s.user_id WHERE s.token = %s""",
                    (authorization[7:],))
        row = cur.fetchone()
    if not row:
        raise HTTPException(401, "invalid session")
    return {"id": row[0], "username": row[1]}


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


# ---------- comments ----------
class CommentIn(BaseModel):
    content: str


@app.get("/api/nodes/{node_id}/comments")
def list_comments(node_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT c.id, c.node_id, u.username, c.content, c.created_at
                       FROM comments c JOIN users u ON u.id = c.user_id
                       WHERE c.node_id = %s ORDER BY c.created_at""", (node_id,))
        return rows_to_dicts(cur)


@app.post("/api/nodes/{node_id}/comments", status_code=201)
def create_comment(node_id: int, body: CommentIn, user: dict = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "empty comment")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""INSERT INTO comments (node_id, user_id, content)
                       VALUES (%s, %s, %s) RETURNING id, node_id, content, created_at""",
                    (node_id, user["id"], body.content.strip()))
        row = rows_to_dicts(cur)[0]
        return {**row, "username": user["username"]}


@app.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM comments WHERE id = %s AND user_id = %s",
                    (comment_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "본인 코멘트만 삭제할 수 있습니다")
