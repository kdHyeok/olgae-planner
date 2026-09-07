import hashlib
import html
import json
import os
import re
import secrets

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from psycopg.errors import UniqueViolation
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
PASSWORD_MIN = 8
PUBLIC_URL = os.environ.get("PUBLIC_URL", "http://localhost:3000").rstrip("/")
OAUTH_RESOURCE = PUBLIC_URL + "/mcp"
OAUTH_SCOPE = "mcp"
OAUTH_ACCESS_PREFIX = "olgo_"

MAX_AVATAR_CHARS = 200_000       # 프로필 이미지(data URL) 길이 상한, 대략 150KB
# data URL 은 base64 가 아니어도 되므로(`data:image/png,<임의 텍스트>`) 형식을 못 박는다.
# 느슨하면 따옴표가 섞인 값이 저장돼 <img src="…"> 속성을 탈출한다
AVATAR_RE = re.compile(r"^data:image/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/]+={0,2}$")

# 등급별 이미지 업로드 총량 (MB, None = 무제한). 프로젝트 소유자 기준으로 합산한다
ROLE_UPLOAD_MB = {"admin": None, "pro": 500, "member": 200, "guest": 50}


def init_db():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id serial PRIMARY KEY,
                username text NOT NULL UNIQUE,
                login_id text NOT NULL,
                display_name text NOT NULL,
                password text NOT NULL
            );
            ALTER TABLE users ADD COLUMN IF NOT EXISTS login_id text;
            ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name text;
            UPDATE users SET login_id = username WHERE login_id IS NULL;
            UPDATE users SET display_name = username WHERE display_name IS NULL;
            ALTER TABLE users ALTER COLUMN login_id SET NOT NULL;
            ALTER TABLE users ALTER COLUMN display_name SET NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS users_login_id_idx ON users (login_id);
            ALTER TABLE users ADD COLUMN IF NOT EXISTS role   text NOT NULL DEFAULT 'guest';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';
            ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
            -- 주소와 API 에 쓰는 랜덤 키. 순번이 드러나지 않게 한다 (내부 PK 는 숫자 유지)
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS slug text;
            CREATE TABLE IF NOT EXISTS project_members (
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role text NOT NULL DEFAULT 'editor',    -- editor(편집자) · coowner(공동 소유자)
                status text NOT NULL DEFAULT 'pending', -- pending(승인 대기) · active
                created_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (project_id, user_id)
            );
            -- MCP·플러그인용 토큰. 브라우저 세션과 분리해 로그아웃해도 살아 있다
            CREATE TABLE IF NOT EXISTS api_tokens (
                token text PRIMARY KEY,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name text NOT NULL DEFAULT '플러그인',
                created_at timestamptz NOT NULL DEFAULT now(),
                last_used_at timestamptz
            );
            CREATE TABLE IF NOT EXISTS oauth_clients (
                client_id text PRIMARY KEY,
                client_info jsonb NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS oauth_requests (
                request_hash text PRIMARY KEY,
                client_id text NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
                state text,
                scopes jsonb NOT NULL,
                code_challenge text NOT NULL,
                redirect_uri text NOT NULL,
                redirect_uri_provided_explicitly boolean NOT NULL,
                resource text NOT NULL,
                expires_at timestamptz NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_codes (
                code_hash text PRIMARY KEY,
                client_id text NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                scopes jsonb NOT NULL,
                code_challenge text NOT NULL,
                redirect_uri text NOT NULL,
                redirect_uri_provided_explicitly boolean NOT NULL,
                resource text NOT NULL,
                expires_at timestamptz NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_tokens (
                access_token_hash text PRIMARY KEY,
                refresh_token_hash text NOT NULL UNIQUE,
                client_id text NOT NULL REFERENCES oauth_clients(client_id) ON DELETE CASCADE,
                user_id int NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                scopes jsonb NOT NULL,
                resource text NOT NULL,
                access_expires_at timestamptz NOT NULL,
                refresh_expires_at timestamptz NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now(),
                last_used_at timestamptz
            );
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
                note text NOT NULL DEFAULT '',
                UNIQUE (project_id, term)
            );
            ALTER TABLE terms ADD COLUMN IF NOT EXISTS note text NOT NULL DEFAULT '';
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
            CREATE INDEX IF NOT EXISTS project_members_user_id_idx ON project_members (user_id);
            CREATE INDEX IF NOT EXISTS api_tokens_user_id_idx ON api_tokens (user_id);
            CREATE INDEX IF NOT EXISTS oauth_requests_client_id_idx ON oauth_requests (client_id);
            CREATE INDEX IF NOT EXISTS oauth_codes_client_id_idx ON oauth_codes (client_id);
            CREATE INDEX IF NOT EXISTS oauth_codes_user_id_idx ON oauth_codes (user_id);
            CREATE INDEX IF NOT EXISTS oauth_tokens_user_id_idx ON oauth_tokens (user_id);
            CREATE INDEX IF NOT EXISTS oauth_tokens_client_id_idx ON oauth_tokens (client_id);
            -- 목록·삭제에 쓰는 번호. 토큰 값 자체를 다시 내보내지 않으려고 둔다
            ALTER TABLE api_tokens ADD COLUMN IF NOT EXISTS id serial;
            -- 예전 'viewer' 멤버 등급은 없어졌다. 읽기 전용은 이제 공유 링크 상태이지 멤버가 아니다
            -- CREATE TABLE IF NOT EXISTS 로는 기존 테이블의 기본값이 바뀌지 않는다
            ALTER TABLE project_members ALTER COLUMN role SET DEFAULT 'editor';
            UPDATE project_members SET role = 'editor' WHERE role NOT IN ('editor', 'coowner');
            CREATE INDEX IF NOT EXISTS sessions_user_id_idx    ON sessions (user_id);
            CREATE INDEX IF NOT EXISTS projects_owner_id_idx   ON projects (owner_id);
            CREATE INDEX IF NOT EXISTS users_status_idx         ON users (status);
            INSERT INTO settings (key, value) VALUES ('signup_open', '1')
                ON CONFLICT (key) DO NOTHING;
            CREATE UNIQUE INDEX IF NOT EXISTS projects_slug_idx ON projects (slug);
            -- 최초 부트스트랩: 관리자가 없으면 가장 오래된 계정을 관리자로 올린다
            UPDATE users SET role = 'admin', status = 'active'
             WHERE id = (SELECT min(id) FROM users)
               AND NOT EXISTS (SELECT 1 FROM users WHERE role = 'admin');
            -- ponytail: 세션 만료는 기동 시 30일 지난 것만 지우는 방식. 요청마다 검사해야 하면 opt_user 에 조건 추가
            DELETE FROM sessions WHERE created_at < now() - interval '30 days';
            DELETE FROM login_attempts WHERE last_fail < now() - interval '24 hours';
            DELETE FROM oauth_requests WHERE expires_at < now();
            DELETE FROM oauth_codes WHERE expires_at < now();
            DELETE FROM oauth_tokens WHERE refresh_expires_at < now();
        """)

        # ---- 컬렉션(커스텀 표)·번호 체계. 설계는 docs/PLAN-collections.md §4 ----
        cur.execute("""
            -- 프로젝트 키(PLNT)와 번호 카운터. 기능·표 행·작업이 번호 하나를 공유한다 (D1·D2)
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS key text;
            ALTER TABLE projects ADD COLUMN IF NOT EXISTS next_seq int NOT NULL DEFAULT 0;
            -- 노드에도 번호를 준다. 고유성은 next_seq 발급으로 보장 (items 와 공유라 DB UNIQUE 로 못 건다)
            ALTER TABLE nodes ADD COLUMN IF NOT EXISTS seq int;
            CREATE INDEX IF NOT EXISTS nodes_project_seq_idx ON nodes (project_id, seq);

            CREATE TABLE IF NOT EXISTS collections (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                key text NOT NULL,                  -- 'prd' · 'tasks' · 'policies' … 내보내기·MCP 용 안정 키
                title text NOT NULL,                -- 화면 이름. 바꿔도 key 는 유지
                view text NOT NULL DEFAULT 'table', -- document | table | board
                board_by text,                      -- board 일 때 그룹 기준 select 속성 key
                schema jsonb NOT NULL DEFAULT '[]', -- [{key, label, type, options?, target?}]
                sort_order int NOT NULL DEFAULT 0,
                builtin bool NOT NULL DEFAULT false,
                UNIQUE (project_id, key)
            );
            CREATE TABLE IF NOT EXISTS items (
                id serial PRIMARY KEY,
                project_id int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                collection_id int NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                seq int NOT NULL,                   -- <key>-<seq>. 노드와 번호 공유
                props jsonb NOT NULL DEFAULT '{}',  -- {속성key: 값}. 검증은 API 에서
                sort_order int NOT NULL DEFAULT 0,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                created_by int REFERENCES users(id) ON DELETE SET NULL,
                UNIQUE (project_id, seq)
            );
            CREATE INDEX IF NOT EXISTS items_collection_idx ON items (collection_id, sort_order);
            -- items(project_id) · collections(project_id) 단일 인덱스는 두지 않는다:
            -- UNIQUE (project_id, seq) · UNIQUE (project_id, key) 의 앞부분이 그 역할을 한다
            -- 버전 스냅샷에 컬렉션·행도 담는다. data(노드)·prd 는 그대로 (1.8)
            ALTER TABLE versions ADD COLUMN IF NOT EXISTS collections jsonb;
            -- 행의 속성이 언제 누구에 의해 바뀌었는지 (PLAN 2.6)
            CREATE TABLE IF NOT EXISTS item_events (
                id serial PRIMARY KEY,
                item_id int NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                user_id int REFERENCES users(id) ON DELETE SET NULL,
                at timestamptz NOT NULL DEFAULT now(),
                prop text NOT NULL,
                before jsonb,
                after jsonb
            );
            CREATE INDEX IF NOT EXISTS item_events_item_id_idx ON item_events (item_id, at DESC);
            -- 이미 만들어진 tasks 표의 라벨·옵션 순서를 템플릿과 맞춘다 (행의 값은 건드리지 않는다)
            -- jsonb 는 키 순서를 제 맘대로 정렬하므로 실제 저장 순서(… "label", "target" …)에 맞춘다
            UPDATE collections SET schema = replace(schema::text,
                    '"label": "상위", "target"', '"label": "상위 작업", "target"')::jsonb
             WHERE key = 'tasks' AND schema::text LIKE '%"label": "상위", "target"%';
            UPDATE collections SET schema = replace(schema::text,
                    '["에픽", "작업", "이슈"]', '["작업", "에픽", "이슈"]')::jsonb
             WHERE key = 'tasks' AND schema::text LIKE '%["에픽", "작업", "이슈"]%';

            -- 코멘트는 노드 또는 컬렉션 행 중 하나에 달린다 (API·UI 는 2단계 2.7)
            ALTER TABLE comments ALTER COLUMN node_id DROP NOT NULL;
            ALTER TABLE comments ADD COLUMN IF NOT EXISTS item_id int REFERENCES items(id) ON DELETE CASCADE;
            CREATE INDEX IF NOT EXISTS comments_item_id_idx ON comments (item_id);
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'comments_target_chk') THEN
                    ALTER TABLE comments ADD CONSTRAINT comments_target_chk
                        CHECK (node_id IS NOT NULL OR item_id IS NOT NULL);
                END IF;
            END $$;
        """)
        # 행 검색(ILIKE '%q%')·본문 스캔(정규식)이 인덱스를 타게 하는 trigram 인덱스.
        # pg_trgm 이 없는 PG 라면 인덱스 없이 간다 — 결과는 같고 순차 스캔으로 느릴 뿐이다.
        try:
            cur.execute("SAVEPOINT trgm")
            cur.execute("""CREATE EXTENSION IF NOT EXISTS pg_trgm;
                           CREATE INDEX IF NOT EXISTS items_props_trgm_idx
                               ON items USING gin ((props::text) gin_trgm_ops)""")
            cur.execute("RELEASE SAVEPOINT trgm")
        except Exception as e:  # noqa: BLE001 — 확장 부재·권한 부족 어느 쪽이든 기동은 이어 간다
            cur.execute("ROLLBACK TO SAVEPOINT trgm")
            import logging
            logging.getLogger("uvicorn.error").warning(
                "pg_trgm 인덱스를 만들지 못했습니다. 행 검색은 순차 스캔으로 돕니다: %s", e)
        # 예전 기동이 만든 군더더기 (project_id) 단일 인덱스를 치운다
        cur.execute("""DROP INDEX IF EXISTS items_project_id_idx;
                       DROP INDEX IF EXISTS collections_project_id_idx""")

        # 예전 행에는 slug 가 없다. 행마다 다른 난수를 넣어야 하니 여기서 채운다
        cur.execute("SELECT id FROM projects WHERE slug IS NULL")
        for (i,) in cur.fetchall():
            cur.execute("UPDATE projects SET slug = %s WHERE id = %s", (new_slug(), i))

        # ---- 번호 체계 백필 (PLAN §4). 순서가 중요하다: 노드 번호 → 카운터 → 컬렉션 시드 ----
        # 키가 없으면 소유자 안에서 겹치지 않는 P1 · P2 … 를 준다.
        # 사용자가 나중에 바꿔도 링크는 seq 기준이라 안 깨진다
        cur.execute("SELECT id, owner_id FROM projects WHERE key IS NULL ORDER BY id")
        for pid_, owner_ in cur.fetchall():
            cur.execute("UPDATE projects SET key = %s WHERE id = %s",
                        (next_project_key(cur, owner_, pid_), pid_))
        # 번호 없는 노드는 프로젝트별 id 순으로 이어서 매긴다
        cur.execute("""SELECT project_id, coalesce(max(seq), 0) FROM nodes
                       WHERE seq IS NOT NULL GROUP BY project_id""")
        counters = dict(cur.fetchall())
        cur.execute("SELECT id, project_id FROM nodes WHERE seq IS NULL ORDER BY project_id, id")
        for nid, pid in cur.fetchall():
            counters[pid] = counters.get(pid, 0) + 1
            cur.execute("UPDATE nodes SET seq = %s WHERE id = %s", (counters[pid], nid))
        # 카운터는 노드·행 최대 번호 이상이어야 한다
        cur.execute("""UPDATE projects p SET next_seq = GREATEST(p.next_seq,
                         coalesce((SELECT max(seq) FROM nodes n WHERE n.project_id = p.id), 0),
                         coalesce((SELECT max(seq) FROM items i WHERE i.project_id = p.id), 0))""")
        # 컬렉션이 하나도 없는 프로젝트에 prd·tasks 를 심는다. 기존 PRD 본문은 첫 섹션으로 (D7·D11)
        cur.execute("""SELECT p.id, p.prd FROM projects p
                       WHERE NOT EXISTS (SELECT 1 FROM collections c WHERE c.project_id = p.id)""")
        for pid, prd in cur.fetchall():
            seed_collections(cur, pid, prd)



def rows_to_dicts(cur):
    cols = [c.name for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ---------- 컬렉션(커스텀 표) 템플릿 · 번호 발급 (docs/PLAN-collections.md §4·§5) ----------
def base36(n: int) -> str:
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            return out


def project_key(name: str, pid: int) -> str:
    """이름에 영문이 2자 이상 있으면 그 대문자(최대 4자), 없으면 P+id(36진수). 사용자가 바꿀 수 있다."""
    letters = re.sub(r"[^A-Za-z]", "", name).upper()[:4]
    return letters if len(letters) >= 2 else "P" + base36(pid)


def alloc_seq(cur, pid: int) -> int:
    """프로젝트 안 고유 번호. 원자적이라 동시 요청에서도 겹치지 않는다 (D2)."""
    cur.execute("UPDATE projects SET next_seq = next_seq + 1 WHERE id = %s RETURNING next_seq", (pid,))
    return cur.fetchone()[0]


def _prop(key, label, type_, **extra):
    return {"key": key, "label": label, "type": type_, **extra}


def _select(key, label, *options):
    return _prop(key, label, "select", options=list(options))


# 항상 심는 것: prd · tasks. 나머지는 "+ 표 추가 → 템플릿" (D11)
PRD_SECTIONS = ["한 줄 정의", "제품 목표", "배경", "사용자 문제", "해결 방안", "차별점",
                "타겟 사용자", "사용자 시나리오", "접근 기기"]

COLLECTION_TEMPLATES = {
    "prd": {"title": "PRD", "view": "document",
            "schema": [_prop("title", "제목", "text"), _prop("body", "본문", "md")]},
    "tasks": {"title": "작업", "view": "board", "board_by": "status",
              "schema": [_prop("title", "제목", "text"),
                         _select("status", "상태", "할일", "진행중", "완료"),
                         _select("kind", "종류", "작업", "에픽", "이슈"),
                         _prop("parent", "상위 작업", "relation", target="tasks"),
                         _prop("related", "관련", "relation"),
                         _prop("body", "내용", "md")]},
    "policies": {"title": "핵심 정책", "view": "table",
                 "schema": [_prop("policy", "정책", "md")]},
    "nfr": {"title": "비기능 요구사항", "view": "table",
            "schema": [_prop("area", "분야", "text"), _prop("requirement", "요구사항", "md")]},
    "decisions": {"title": "미결정 사항", "view": "board", "board_by": "status",
                  "schema": [_prop("topic", "항목", "text"),
                             _select("status", "상태", "미결정", "결정"),
                             _prop("default", "현재 기본안", "md"),
                             _prop("decision", "결정 내용", "md")]},
    "tests": {"title": "테스트 시나리오", "view": "table",
              "schema": [_prop("scenario", "시나리오", "md"), _prop("expected", "기대 결과", "md"),
                         _prop("related", "관련", "relation")]},
    "actors": {"title": "객체(액터)", "view": "table",
               "schema": [_prop("actor", "액터", "text"), _prop("role", "역할", "md")]},
    "flows": {"title": "전체 흐름", "view": "table",
              "schema": [_prop("acting", "액팅", "text"), _prop("scenario", "시나리오", "md")]},
    "target_users": {"title": "타겟 사용자", "view": "table",
                     "schema": [_prop("user", "사용자", "text"), _prop("purpose", "목적", "md")]},
    "devices": {"title": "접근 기기", "view": "table", "schema": [_prop("value", "값", "text")]},
    "domains": {"title": "도메인", "view": "table", "schema": [_prop("value", "값", "text")]},
}


def add_collection(cur, pid: int, key: str, tpl: dict | None = None, title: str | None = None,
                   sort_order: int | None = None, builtin: bool = False):
    """컬렉션 하나를 만든다. 같은 key 가 이미 있으면 None."""
    t = tpl or COLLECTION_TEMPLATES[key]
    if sort_order is None:
        cur.execute("SELECT coalesce(max(sort_order), -1) + 1 FROM collections WHERE project_id = %s",
                    (pid,))
        sort_order = cur.fetchone()[0]
    cur.execute("""INSERT INTO collections (project_id, key, title, view, board_by, schema,
                                            sort_order, builtin)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (project_id, key) DO NOTHING RETURNING id""",
                (pid, key, title or t["title"], t["view"], t.get("board_by"),
                 json.dumps(t["schema"], ensure_ascii=False), sort_order, builtin))
    row = cur.fetchone()
    return row[0] if row else None


def add_item(cur, pid: int, cid: int, props: dict, sort_order: int | None = None,
             user_id: int | None = None):
    """행 하나를 만들고 (id, seq) 를 돌려준다. 번호는 alloc_seq 로 받는다."""
    if sort_order is None:
        cur.execute("SELECT coalesce(max(sort_order), -1) + 1 FROM items WHERE collection_id = %s",
                    (cid,))
        sort_order = cur.fetchone()[0]
    seq = alloc_seq(cur, pid)
    cur.execute("""INSERT INTO items (project_id, collection_id, seq, props, sort_order, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, seq""",
                (pid, cid, seq, json.dumps(props, ensure_ascii=False), sort_order, user_id))
    return cur.fetchone()


def seed_collections(cur, pid: int, legacy_prd: str = ""):
    """새 프로젝트(또는 컬렉션이 없는 옛 프로젝트)에 prd·tasks 를 심는다 (D7·D11).

    legacy_prd 가 비어 있지 않고 기본 템플릿 문구가 아니면 '기존 PRD' 섹션으로 보존한다.
    """
    cid = add_collection(cur, pid, "prd", builtin=True, sort_order=0)
    if cid:
        text = (legacy_prd or "").strip()
        if text and text != PRD_TEMPLATE.strip():
            add_item(cur, pid, cid, {"title": "기존 PRD", "body": legacy_prd})
        for title in PRD_SECTIONS:
            add_item(cur, pid, cid, {"title": title, "body": ""})
    add_collection(cur, pid, "tasks", builtin=True, sort_order=1)


# ---------- auth ----------
class LoginCredentials(BaseModel):
    login_id: str
    password: str


class RegisterCredentials(LoginCredentials):
    display_name: str


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100_000).hex()
    return f"{salt}${h}"


API_TOKEN_PREFIX = "olg_"       # MCP·플러그인 토큰은 눈으로 구분되게 접두어를 붙인다


def token_hash(token: str) -> str:
    """원문 OAuth 토큰을 DB에 남기지 않기 위한 고정 길이 조회 키."""
    return hashlib.sha256(token.encode()).hexdigest()


def lookup_token_user(tok: str) -> dict | None:
    """브라우저 세션·API 토큰·OAuth access token을 한 곳에서 검증한다."""
    with pool.connection() as conn, conn.cursor() as cur:
        auth = {}
        if tok.startswith(OAUTH_ACCESS_PREFIX):
            digest = token_hash(tok)
            cur.execute("""SELECT u.id, u.login_id, u.display_name, u.role, u.status,
                                  t.client_id, t.scopes, extract(epoch from t.access_expires_at),
                                  t.resource
                           FROM oauth_tokens t JOIN users u ON u.id = t.user_id
                           WHERE t.access_token_hash = %s AND t.access_expires_at > now()
                             AND t.resource = %s""", (digest, OAUTH_RESOURCE))
            row = cur.fetchone()
            if row:
                cur.execute("""UPDATE oauth_tokens SET last_used_at = now()
                               WHERE access_token_hash = %s
                                 AND (last_used_at IS NULL
                                      OR last_used_at < now() - interval '1 hour')""", (digest,))
                auth = {"client_id": row[5], "scopes": row[6],
                        "expires_at": int(row[7]), "resource": row[8]}
        elif tok.startswith(API_TOKEN_PREFIX):
            cur.execute("""SELECT u.id, u.login_id, u.display_name, u.role, u.status FROM api_tokens t
                           JOIN users u ON u.id = t.user_id WHERE t.token = %s""", (tok,))
            row = cur.fetchone()
            if row:
                # 마지막 사용 시각은 한 시간에 한 번만 적는다 (요청마다 쓰면 낭비)
                cur.execute("""UPDATE api_tokens SET last_used_at = now() WHERE token = %s
                               AND (last_used_at IS NULL
                                    OR last_used_at < now() - interval '1 hour')""", (tok,))
        else:
            cur.execute("""SELECT u.id, u.login_id, u.display_name, u.role, u.status FROM sessions s
                           JOIN users u ON u.id = s.user_id WHERE s.token = %s""", (tok,))
            row = cur.fetchone()
    if not row or row[4] != "active":
        return None                      # 대기·차단 계정의 토큰은 통하지 않는다
    return {"id": row[0], "login_id": row[1], "display_name": row[2], "role": row[3], **auth}


def opt_user(authorization: str | None = Header(None)) -> dict | None:
    """Bearer 세션·계정별 API 토큰·OAuth access token으로 사용자를 찾는다."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return lookup_token_user(authorization[7:])


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


MEMBER_ROLES = ("editor", "coowner")   # 멤버로 승인할 수 있는 등급

# 권한 5단계. 숫자가 클수록 많이 할 수 있다
#   reader    공유 링크 · 비로그인 → 읽기, 마크다운 내보내기
#   commenter 공유 링크 · 로그인   → 위 + 코멘트
#   editor    편집자               → 위 + 내용 수정, 이미지 앨범, 버전 기록, MCP·플러그인 조회
#   coowner   공동 소유자           → 위 + 공유 링크 관리, 멤버 관리, 이름 변경
#   owner     소유자               → 위 + 프로젝트 삭제
LEVELS = {"reader": 0, "commenter": 1, "editor": 2, "coowner": 3, "owner": 4}

DENY = {
    "commenter": "로그인이 필요합니다",
    "editor": "편집 권한이 필요합니다. 프로젝트 소유자에게 참여 승인을 요청하세요.",
    "coowner": "공동 소유자만 할 수 있습니다",
    "owner": "프로젝트 소유자만 가능합니다",
}


def new_slug() -> str:
    """주소에 쓰는 랜덤 키. 순번을 감추기 위한 것이고 권한 검사를 대신하지 않는다."""
    return secrets.token_urlsafe(9)


def find_project(cur, ref) -> tuple:
    """slug(숫자를 주면 예전 id) 로 찾아 (id, owner_id, share_token) 을 돌려준다."""
    if isinstance(ref, int) or str(ref).isdigit():
        cur.execute("SELECT id, owner_id, share_token FROM projects WHERE id = %s", (int(ref),))
    else:
        cur.execute("SELECT id, owner_id, share_token FROM projects WHERE slug = %s", (str(ref),))
    row = cur.fetchone()
    if not row:
        raise HTTPException(404, "프로젝트가 없습니다")
    return row


def access_level(cur, ref, user: dict | None, share: str | None) -> tuple:
    """(프로젝트 id, 내 등급). 권한이 전혀 없으면 등급이 None."""
    pid, owner_id, token = find_project(cur, ref)
    if user and user["id"] == owner_id:
        return pid, "owner"
    if user:
        cur.execute("""SELECT role FROM project_members
                       WHERE project_id = %s AND user_id = %s AND status = 'active'""",
                    (pid, user["id"]))
        m = cur.fetchone()
        if m and m[0] in MEMBER_ROLES:
            return pid, m[0]
    if share and token and secrets.compare_digest(share, token):
        # 공유 링크로 들어온 사람. 로그인해 두면 코멘트까지 쓸 수 있다
        return pid, ("commenter" if user else "reader")
    return pid, None


def require(cur, ref, user: dict | None, share: str | None, need: str) -> int:
    """need 등급 이상인지 확인하고 프로젝트의 내부 id 를 돌려준다."""
    pid, level = access_level(cur, ref, user, share)
    if not level:
        raise HTTPException(403, "접근 권한이 없습니다 (공유 링크가 필요합니다)")
    if LEVELS[level] < LEVELS[need]:
        raise HTTPException(401 if need == "commenter" and not user else 403, DENY[need])
    return pid


def check_access(cur, ref, user: dict | None, share: str | None) -> int:
    """읽기. 공유 링크만 있어도 된다."""
    return require(cur, ref, user, share, "reader")


def check_comment(cur, ref, user: dict | None, share: str | None) -> int:
    """코멘트처럼 누가 했는지가 남는 작업. 로그인이 필요하다."""
    return require(cur, ref, user, share, "commenter")


def check_write(cur, ref, user: dict | None, share: str | None = None) -> int:
    """내용 수정 · 이미지 앨범 · 버전 기록. 편집자 이상."""
    return require(cur, ref, user, share, "editor")


def check_own(cur, ref, user: dict | None, share: str | None = None) -> int:
    """공유 링크 관리 · 멤버 관리 · 이름 변경. 공동 소유자 이상."""
    return require(cur, ref, user, share, "coowner")


def check_owner(cur, ref, user: dict) -> int:
    pid, owner_id, _ = find_project(cur, ref)
    if owner_id != user["id"]:
        raise HTTPException(403, "프로젝트 소유자만 가능합니다")
    return pid


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


@app.get("/api/auth/id-available")
def id_available(login_id: str):
    login_id = login_id.strip()
    if not login_id:
        return {"available": False}
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM users WHERE login_id = %s", (login_id,))
        return {"available": cur.fetchone() is None}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterCredentials):
    """첫 계정은 곧바로 관리자, 그 뒤는 관리자 승인을 기다리는 대기 상태로 만든다."""
    login_id, display_name = body.login_id.strip(), body.display_name.strip()
    if not login_id or not display_name:
        raise HTTPException(400, "아이디와 표시 이름이 필요합니다")
    if len(body.password) < PASSWORD_MIN:
        raise HTTPException(400, f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM users")
        first = cur.fetchone()[0] == 0
        if not first and get_setting(cur, "signup_open", "1") != "1":
            raise HTTPException(403, "지금은 신규 가입을 받지 않습니다. 관리자에게 문의하세요.")
        cur.execute("SELECT 1 FROM users WHERE login_id = %s", (login_id,))
        if cur.fetchone():
            raise HTTPException(409, "이미 사용 중인 아이디입니다")
        role, status = ("admin", "active") if first else ("guest", "pending")
        cur.execute("""INSERT INTO users (username, login_id, display_name, password, role, status)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT DO NOTHING RETURNING id""",
                    (login_id, login_id, display_name, hash_pw(body.password), role, status))
        row = cur.fetchone()
        if not row:
            raise HTTPException(409, "이미 사용 중인 아이디입니다")
        uid = row[0]
        if status == "active":
            return {"token": make_session(cur, uid), "id": uid, "login_id": login_id,
                    "display_name": display_name, "role": role}
    return {"status": "pending", "login_id": login_id, "display_name": display_name,
            "message": "가입 신청이 접수되었습니다. 관리자 승인 후 로그인할 수 있습니다."}


def authenticate_user(login_id: str, password: str, request: Request) -> dict:
    """공용 로그인 검증. REST와 OAuth가 같은 잠금 정책을 사용한다."""
    login_id = login_id.strip()
    ip = client_ip(request)
    ukey, ipkey = fail_keys(login_id, ip)
    with pool.connection() as conn, conn.cursor() as cur:
        # 잠금 기준은 (계정+IP) 또는 (IP). 계정 이름만으로는 잠그지 않아 남을 잠글 수 없다
        left_sec = lock_left(cur, (ukey, ipkey))
        cur.execute("""SELECT id, password, role, status, display_name
                       FROM users WHERE login_id = %s""", (login_id,))
        u = cur.fetchone()

    if left_sec:
        raise HTTPException(429, "로그인 실패가 많아 이 위치에서 로그인이 제한됩니다."
                                 f" {fmt_dur(left_sec)} 뒤에 다시 시도하세요.")
    ok = bool(u) and secrets.compare_digest(
        hash_pw(password, u[1].split("$")[0]), u[1])
    if not ok:
        left, locked = bump_login_fail(login_id, ip)
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다"
                                 + (f" — {fmt_dur(locked)}간 로그인이 제한됩니다" if locked
                                    else f" (남은 시도 {left}회)"))
    if u[3] == "pending":
        raise HTTPException(403, "가입 승인 대기 중입니다. 관리자 승인 후 이용할 수 있습니다.")
    if u[3] != "active":
        raise HTTPException(403, "이 계정은 사용할 수 없습니다. 관리자에게 문의하세요.")

    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM login_attempts WHERE key = ANY(%s)", ([ukey, ipkey],))
    return {"id": u[0], "login_id": login_id, "display_name": u[4], "role": u[2]}


@app.post("/api/auth/login")
def login(body: LoginCredentials, request: Request):
    user = authenticate_user(body.login_id, body.password, request)
    with pool.connection() as conn, conn.cursor() as cur:
        return {**user, "token": make_session(cur, user["id"])}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        used = project_count(cur, user["id"])
        up_used, up_limit = upload_usage(cur, user["id"], user["role"])
        cur.execute("SELECT avatar FROM users WHERE id = %s", (user["id"],))
        avatar = cur.fetchone()[0]
    return {"id": user["id"], "login_id": user["login_id"],
            "display_name": user["display_name"], "role": user["role"],
            "projects": used, "project_limit": ROLE_LIMITS.get(user["role"]),
            "upload_bytes": up_used, "upload_limit": up_limit, "avatar": avatar}


class DisplayNameIn(BaseModel):
    display_name: str


@app.put("/api/me/display-name")
def change_display_name(body: DisplayNameIn, user: dict = Depends(current_user)):
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(400, "이름을 입력하세요")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET display_name = %s WHERE id = %s",
                    (display_name, user["id"]))
    return {"display_name": display_name}


class TokenIn(BaseModel):
    name: str = "플러그인"


def token_row(r: dict) -> dict:
    """목록에는 앞뒤만 보여 준다. 전체 값은 발급할 때 한 번만 돌려준다."""
    t = r["token"]
    return {"id": r["id"], "name": r["name"], "created_at": r["created_at"],
            "last_used_at": r["last_used_at"],
            "masked": t[:len(API_TOKEN_PREFIX) + 4] + "\u2026" + t[-4:]}


@app.get("/api/me/tokens")
def list_tokens(user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, token, name, created_at, last_used_at
                       FROM api_tokens WHERE user_id = %s ORDER BY created_at""",
                    (user["id"],))
        return [token_row(r) for r in rows_to_dicts(cur)]


@app.post("/api/me/tokens", status_code=201)
def create_token(body: TokenIn, user: dict = Depends(current_user)):
    """MCP·플러그인용 토큰을 발급한다. 전체 값은 이 응답에서만 볼 수 있다."""
    name = (body.name or "플러그인").strip()[:40] or "플러그인"
    tok = API_TOKEN_PREFIX + secrets.token_urlsafe(24)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM api_tokens WHERE user_id = %s", (user["id"],))
        if cur.fetchone()[0] >= 10:
            raise HTTPException(403, "토큰은 10개까지 만들 수 있습니다. 쓰지 않는 토큰을 지우세요.")
        cur.execute("""INSERT INTO api_tokens (token, user_id, name) VALUES (%s, %s, %s)
                       RETURNING token, name, created_at""", (tok, user["id"], name))
        return rows_to_dicts(cur)[0]


@app.delete("/api/me/tokens/{tid}", status_code=204)
def delete_token(tid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM api_tokens WHERE id = %s AND user_id = %s",
                    (tid, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "토큰을 찾을 수 없습니다")


class AvatarIn(BaseModel):
    avatar: str | None = None            # data URL. None 이면 삭제


@app.put("/api/me/avatar", status_code=204)
def set_avatar(body: AvatarIn, user: dict = Depends(current_user)):
    """프로필 이미지. 프런트에서 128px 로 줄여 보내므로 users 행에 data URL 로 둔다."""
    av = body.avatar or None
    if av and not AVATAR_RE.match(av):
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
    if len(body.password) < PASSWORD_MIN:
        raise HTTPException(400, f"새 비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT password FROM users WHERE id = %s", (user["id"],))
        cur_hash = cur.fetchone()[0]
        if not secrets.compare_digest(hash_pw(body.current, cur_hash.split("$")[0]), cur_hash):
            raise HTTPException(403, "현재 비밀번호가 올바르지 않습니다")
        cur.execute("UPDATE users SET password = %s WHERE id = %s",
                    (hash_pw(body.password), user["id"]))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (user["id"],))
        cur.execute("DELETE FROM oauth_codes WHERE user_id = %s", (user["id"],))
        cur.execute("DELETE FROM oauth_tokens WHERE user_id = %s", (user["id"],))
        return {"token": make_session(cur, user["id"]), "id": user["id"],
                "login_id": user["login_id"], "display_name": user["display_name"],
                "role": user["role"]}


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
        cur.execute("""SELECT u.id, u.login_id, u.display_name, u.role, u.status, u.created_at,
                              (SELECT count(*) FROM projects p WHERE p.owner_id = u.id) AS projects,
                              (SELECT coalesce(sum(length(i.data)), 0)
                                 FROM images i JOIN projects p2 ON p2.id = i.project_id
                                WHERE p2.owner_id = u.id) AS upload_bytes
                       FROM users u WHERE u.status <> 'pending' ORDER BY u.id""")
        return with_limits(rows_to_dicts(cur))


@app.get("/api/admin/signups")
def admin_list_signups(_: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT id, login_id, display_name, created_at FROM users
                       WHERE status = 'pending' ORDER BY created_at""")
        return rows_to_dicts(cur)


@app.post("/api/admin/signups/{uid}/approve")
def admin_approve(uid: int, body: RoleIn, _: dict = Depends(admin_user)):
    if body.role not in ROLE_LIMITS:
        raise HTTPException(400, "등급이 올바르지 않습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""UPDATE users SET status = 'active', role = %s
                       WHERE id = %s AND status = 'pending' RETURNING display_name""",
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
        cur.execute("UPDATE users SET role = %s WHERE id = %s RETURNING display_name",
                    (body.role, uid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        return {"username": row[0], "role": body.role, "project_limit": ROLE_LIMITS[body.role]}


class LoginIdIn(BaseModel):
    login_id: str


@app.put("/api/admin/users/{uid}/login-id")
def admin_set_login_id(uid: int, body: LoginIdIn, _: dict = Depends(admin_user)):
    login_id = body.login_id.strip()
    if not login_id:
        raise HTTPException(400, "아이디를 입력하세요")
    try:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT login_id FROM users WHERE id = %s", (uid,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, "계정을 찾을 수 없습니다")
            old_login_id = row[0]
            cur.execute("UPDATE users SET username = %s, login_id = %s WHERE id = %s",
                        (login_id, login_id, uid))
            cur.execute("DELETE FROM login_attempts WHERE key LIKE %s",
                        ("u:" + old_login_id + "@%",))
    except UniqueViolation:
        raise HTTPException(409, "이미 사용 중인 아이디입니다")
    return {"login_id": login_id}


@app.put("/api/admin/users/{uid}/display-name")
def admin_set_display_name(uid: int, body: DisplayNameIn, _: dict = Depends(admin_user)):
    display_name = body.display_name.strip()
    if not display_name:
        raise HTTPException(400, "이름을 입력하세요")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET display_name = %s WHERE id = %s RETURNING display_name",
                    (display_name, uid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
    return {"display_name": row[0]}


@app.put("/api/admin/users/{uid}/password", status_code=204)
def admin_set_password(uid: int, body: PasswordIn, _: dict = Depends(admin_user)):
    """관리자 계정을 포함해 어떤 계정의 비밀번호도 바꾼다. 기존 세션은 모두 끊는다."""
    if len(body.password) < PASSWORD_MIN:
        raise HTTPException(400, f"비밀번호는 {PASSWORD_MIN}자 이상이어야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT login_id FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        cur.execute("UPDATE users SET password = %s WHERE id = %s",
                    (hash_pw(body.password), uid))
        cur.execute("DELETE FROM sessions WHERE user_id = %s", (uid,))
        # 계정을 되찾는 상황이므로 플러그인 토큰도 함께 끊는다
        cur.execute("DELETE FROM api_tokens WHERE user_id = %s", (uid,))
        cur.execute("DELETE FROM oauth_codes WHERE user_id = %s", (uid,))
        cur.execute("DELETE FROM oauth_tokens WHERE user_id = %s", (uid,))
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
        cur.execute("SELECT display_name, role FROM users WHERE id = %s", (uid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "계정을 찾을 수 없습니다")
        cur.execute("""SELECT p.slug, p.name, p.share_token IS NOT NULL AS shared,
                              (SELECT count(*) FROM nodes n WHERE n.project_id = p.id) AS nodes,
                              (SELECT count(*) FROM images i WHERE i.project_id = p.id) AS images
                       FROM projects p WHERE p.owner_id = %s ORDER BY p.id""", (uid,))
        return {"username": row[0], "role": row[1], "project_limit": ROLE_LIMITS.get(row[1]),
                "projects": rows_to_dicts(cur)}


@app.delete("/api/admin/projects/{pid}", status_code=204)
def admin_delete_project(pid: str, _: dict = Depends(admin_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        real_id, _owner, _tok = find_project(cur, pid)
        cur.execute("DELETE FROM projects WHERE id = %s", (real_id,))


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
    """내가 만든 프로젝트 + 멤버로 참여중인 프로젝트. my_role 로 UI 를 나눈다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT p.slug, p.key, p.name, p.share_token, u.display_name AS owner,
                   CASE WHEN p.owner_id = %(uid)s THEN 'owner' ELSE m.role END AS my_role,
                   (SELECT count(*) FROM project_members q
                     WHERE q.project_id = p.id AND q.status = 'pending') AS pending,
                   (SELECT count(*) FROM project_members q
                     WHERE q.project_id = p.id AND q.status = 'active') AS members
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN project_members m
                   ON m.project_id = p.id AND m.user_id = %(uid)s AND m.status = 'active'
            WHERE p.owner_id = %(uid)s OR m.user_id IS NOT NULL
            ORDER BY (p.owner_id = %(uid)s) DESC, p.id""", {"uid": user["id"]})
        rows = rows_to_dicts(cur)
    for r in rows:
        if r["my_role"] == "editor":
            r["share_token"] = None      # 공유 링크는 공동 소유자 이상만 다룬다
        if r["my_role"] not in ("owner", "coowner"):
            r["pending"] = 0             # 승인 대기 수는 멤버를 관리할 수 있는 사람만 본다
    return rows


@app.post("/api/projects", status_code=201)
def create_project(body: ProjectIn, user: dict = Depends(current_user)):
    if not body.name.strip():
        raise HTTPException(400, "이름이 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        limit = ROLE_LIMITS.get(user["role"], 1)
        if limit is not None and project_count(cur, user["id"]) >= limit:
            raise HTTPException(403, f"{user['role']} 등급은 프로젝트를 최대 {limit}개까지"
                                     " 만들 수 있습니다. 관리자에게 등급 상향을 요청하세요.")
        cur.execute("""INSERT INTO projects (owner_id, name, prd, slug, key)
                       VALUES (%s, %s, %s, %s, %s)
                       RETURNING id, slug, name, share_token, key""",
                    (user["id"], body.name.strip(), PRD_TEMPLATE, new_slug(),
                     next_project_key(cur, user["id"])))
        row = rows_to_dicts(cur)[0]
        pid = row.pop("id")
        # 번호 앞부분(PLNT)과 기본 컬렉션(prd·tasks). PLAN-collections.md D1·D11
        row["key"] = project_key(row["name"], pid)
        cur.execute("UPDATE projects SET key = %s WHERE id = %s", (row["key"], pid))
        seed_collections(cur, pid, PRD_TEMPLATE)
        return row


@app.put("/api/projects/{pid}")
def rename_project(pid: str, body: ProjectIn, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("UPDATE projects SET name = %s WHERE id = %s", (body.name.strip(), pid))
    return {"ok": True}


class KeyIn(BaseModel):
    key: str


KEY_RE = re.compile(r"^[A-Z][A-Z0-9]{1,4}$")


def next_project_key(cur, owner_id: int, exclude_pid: int | None = None) -> str:
    """그 사용자의 프로젝트 안에서 겹치지 않는 P1 · P2 … 를 고른다."""
    cur.execute("SELECT key FROM projects WHERE owner_id = %s AND key IS NOT NULL"
                " AND id IS DISTINCT FROM %s", (owner_id, exclude_pid))
    taken = {r[0] for r in cur.fetchall()}
    i = 1
    while f"P{i}" in taken:
        i += 1
    return f"P{i}"


def key_taken(cur, owner_id: int, key: str, pid: int) -> bool:
    cur.execute("""SELECT 1 FROM projects WHERE owner_id = %s AND upper(key) = %s
                   AND id <> %s LIMIT 1""", (owner_id, key, pid))
    return cur.fetchone() is not None


@app.put("/api/projects/{pid}/key")
def set_project_key(pid: str, body: KeyIn, user: dict = Depends(current_user)):
    """번호 앞부분(PLNT). 바꿔도 링크는 seq 기준이라 안 깨진다 (PLAN D1)."""
    key = body.key.strip().upper()
    if not KEY_RE.match(key):
        raise HTTPException(400, "키는 영문 대문자로 시작하는 2~5자(영문·숫자)여야 합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("SELECT owner_id FROM projects WHERE id = %s", (pid,))
        owner_id = cur.fetchone()[0]
        if key_taken(cur, owner_id, key, pid):
            raise HTTPException(409, f"'{key}' 는 다른 프로젝트가 이미 쓰고 있습니다")
        cur.execute("UPDATE projects SET key = %s WHERE id = %s", (key, pid))
    return {"key": key}


def item_title(props: dict, schema: list) -> str:
    """행의 대표 이름: 첫 text 속성 값. 없으면 첫 비어있지 않은 문자열의 첫 줄 60자."""
    props = props or {}
    for prop in schema or []:
        if prop.get("type") == "text" and props.get(prop["key"]):
            return str(props[prop["key"]])
    for prop in schema or []:
        v = props.get(prop["key"])
        if isinstance(v, str) and v.strip():
            return v.strip().splitlines()[0][:60]
    return ""


def resolve_seq(cur, pid: int, seq: int) -> dict | None:
    """프로젝트 안 번호 → 노드 또는 컬렉션 행. 둘은 번호 공간을 공유한다 (PLAN §6)."""
    cur.execute("SELECT id, title FROM nodes WHERE project_id = %s AND seq = %s", (pid, seq))
    row = cur.fetchone()
    if row:
        return {"kind": "node", "seq": seq, "id": row[0], "title": row[1]}
    cur.execute("""SELECT i.id, i.props, c.key, c.schema FROM items i
                   JOIN collections c ON c.id = i.collection_id
                   WHERE i.project_id = %s AND i.seq = %s""", (pid, seq))
    row = cur.fetchone()
    if not row:
        return None
    iid, props, ckey, schema = row
    return {"kind": "item", "seq": seq, "id": iid, "collection": ckey,
            "title": item_title(props, schema)}


@app.get("/api/projects/{pid}/resolve/{seq}")
def resolve(pid: str, seq: int, share: str | None = None,
            user: dict | None = Depends(opt_user)):
    """`[[KEY-seq]]` 링크가 무엇을 가리키는지. 읽기 권한이면 누구나."""
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("SELECT key FROM projects WHERE id = %s", (pid,))
        key = cur.fetchone()[0]
        hit = resolve_seq(cur, pid, seq)
    if not hit:
        raise HTTPException(404, "번호에 해당하는 항목이 없습니다")
    hit["label"] = f"{key}-{seq}"
    return hit


@app.delete("/api/projects/{pid}", status_code=204)
def delete_project(pid: str, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_owner(cur, pid, user)
        cur.execute("DELETE FROM projects WHERE id = %s", (pid,))


@app.post("/api/projects/{pid}/share", status_code=201)
def create_share(pid: str, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        token = secrets.token_urlsafe(24)
        cur.execute("UPDATE projects SET share_token = %s WHERE id = %s", (token, pid))
        return {"share_token": token}


@app.delete("/api/projects/{pid}/share", status_code=204)
def delete_share(pid: str, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("UPDATE projects SET share_token = NULL WHERE id = %s", (pid,))


@app.get("/api/shared/{token}")
def resolve_share(token: str, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("""SELECT p.slug, p.key, p.name, u.display_name AS owner, p.owner_id, p.id
                       FROM projects p JOIN users u ON u.id = p.owner_id
                       WHERE p.share_token = %s""", (token,))
        rows = rows_to_dicts(cur)
        if not rows:
            raise HTTPException(404, "유효하지 않은 공유 링크입니다")
        pr = rows[0]
        # 참여 버튼을 어떻게 보여줄지 판단할 재료: owner · editor · viewer · pending · none
        join = "none"
        if user:
            if user["id"] == pr["owner_id"]:
                join = "owner"
            else:
                cur.execute("""SELECT role, status FROM project_members
                               WHERE project_id = %s AND user_id = %s""",
                            (pr["id"], user["id"]))
                m = cur.fetchone()
                if m:
                    join = m[0] if m[1] == "active" else "pending"
        pr.pop("owner_id"); pr.pop("id")
        pr["join"] = join
        return pr


# ---------- project members ----------
class MemberRole(BaseModel):
    role: str = "editor"


def valid_role(role: str) -> str:
    if role not in MEMBER_ROLES:
        raise HTTPException(400, "권한은 editor 또는 coowner 여야 합니다")
    return role


@app.post("/api/projects/{pid}/join", status_code=201)
def join_project(pid: str, share: str | None = None, user: dict = Depends(current_user)):
    """공유 링크로 들어온 사람이 참여를 요청한다. 소유자가 승인해야 멤버가 된다."""
    with pool.connection() as conn, conn.cursor() as cur:
        pid, owner_id, token = find_project(cur, pid)
        if owner_id == user["id"]:
            raise HTTPException(400, "내가 만든 프로젝트입니다")
        if not (share and token and secrets.compare_digest(share, token)):
            raise HTTPException(403, "유효한 공유 링크가 필요합니다")
        cur.execute("""INSERT INTO project_members (project_id, user_id) VALUES (%s, %s)
                       ON CONFLICT (project_id, user_id) DO NOTHING
                       RETURNING status""", (pid, user["id"]))
        row = cur.fetchone()
        if row:
            return {"status": row[0], "new": True}
        cur.execute("""SELECT status, role FROM project_members
                       WHERE project_id = %s AND user_id = %s""", (pid, user["id"]))
        st, role = cur.fetchone()
        return {"status": st, "role": role, "new": False}


@app.get("/api/projects/{pid}/members")
def list_members(pid: str, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("""SELECT m.user_id, u.display_name AS username, u.avatar,
                              m.role, m.status, m.created_at
                       FROM project_members m JOIN users u ON u.id = m.user_id
                       WHERE m.project_id = %s
                       ORDER BY (m.status = 'pending') DESC, m.created_at""", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/members/{uid}/approve")
def approve_member(pid: str, uid: int, body: MemberRole, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("""UPDATE project_members SET role = %s, status = 'active'
                       WHERE project_id = %s AND user_id = %s""",
                    (valid_role(body.role), pid, uid))
        if not cur.rowcount:
            raise HTTPException(404, "참여 요청을 찾을 수 없습니다")
    return {"ok": True}


@app.put("/api/projects/{pid}/members/{uid}/role")
def set_member_role(pid: str, uid: int, body: MemberRole, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("""UPDATE project_members SET role = %s
                       WHERE project_id = %s AND user_id = %s AND status = 'active'""",
                    (valid_role(body.role), pid, uid))
        if not cur.rowcount:
            raise HTTPException(404, "멤버를 찾을 수 없습니다")
    return {"ok": True}


@app.delete("/api/projects/{pid}/members/{uid}", status_code=204)
def remove_member(pid: str, uid: int, user: dict = Depends(current_user)):
    """참여 요청 거절과 멤버 삭제를 겸한다."""
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_own(cur, pid, user)
        cur.execute("DELETE FROM project_members WHERE project_id = %s AND user_id = %s",
                    (pid, uid))


# ---------- 컬렉션(커스텀 표) · 행 (docs/PLAN-collections.md §4 · 1.3) ----------
PROP_TYPES = ("text", "md", "select", "checkbox", "relation")
VIEWS = ("document", "table", "board")
PROP_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
COLL_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")


def validate_schema(schema) -> list:
    """속성 정의 배열을 검사해 정규화한다. jsonb 라 DB 가 대신 검사해 주지 않는다."""
    if not isinstance(schema, list) or not schema:
        raise HTTPException(400, "속성이 하나 이상 필요합니다")
    out, seen = [], set()
    for raw in schema:
        if not isinstance(raw, dict):
            raise HTTPException(400, "속성 정의는 객체여야 합니다")
        key = str(raw.get("key", "")).strip()
        typ = raw.get("type")
        if not PROP_KEY_RE.match(key):
            raise HTTPException(400, f"속성 key '{key}' 는 소문자로 시작하는 영문·숫자·_ 만 됩니다")
        if key in seen:
            raise HTTPException(400, f"속성 key '{key}' 가 중복됩니다")
        if typ not in PROP_TYPES:
            raise HTTPException(400, f"속성 타입은 {', '.join(PROP_TYPES)} 중 하나여야 합니다")
        prop = {"key": key, "label": str(raw.get("label", "")).strip() or key, "type": typ}
        if typ == "select":
            opts = [str(o).strip() for o in (raw.get("options") or []) if str(o).strip()]
            if not opts:
                raise HTTPException(400, f"select 속성 '{prop['label']}' 에는 옵션이 필요합니다")
            prop["options"] = opts
        if typ == "relation" and raw.get("target"):
            prop["target"] = str(raw["target"]).strip()
        seen.add(key)
        out.append(prop)
    return out


def validate_props(schema: list, props: dict) -> dict:
    """스키마에 없는 key 는 버리고 타입을 맞춘다. None 은 '비움'."""
    by_key = {p["key"]: p for p in schema}
    out = {}
    for key, val in (props or {}).items():
        prop = by_key.get(key)
        if not prop:
            continue
        typ = prop["type"]
        if val is None:
            out[key] = None
        elif typ in ("text", "md"):
            if not isinstance(val, str):
                raise HTTPException(400, f"'{prop['label']}' 는 문자열이어야 합니다")
            out[key] = val
        elif typ == "select":
            if val not in prop["options"]:
                raise HTTPException(400, f"'{prop['label']}' 는 {' · '.join(prop['options'])} 중 하나여야 합니다")
            out[key] = val
        elif typ == "checkbox":
            out[key] = bool(val)
        elif typ == "relation":
            if not isinstance(val, list) or not all(isinstance(x, int) for x in val):
                raise HTTPException(400, f"'{prop['label']}' 는 번호(seq) 배열이어야 합니다")
            out[key] = val
    return out


def check_relation_cycles(cur, coll: dict, item: dict, patch: dict) -> None:
    """자기 표를 가리키는 relation(상위 작업 같은 것)이 고리를 만들지 않게 막는다.

    A 의 상위를 B 로 두려면 B 를 타고 올라갔을 때 A 가 나오면 안 된다.
    (A→B, B→A 처럼 서로 상위가 되는 상황을 막는다.)
    """
    selfrefs = [x for x in (coll["schema"] or [])
                if x["type"] == "relation" and x.get("target") == coll["key"]]
    if not selfrefs:
        return
    cur.execute("SELECT seq, props FROM items WHERE collection_id = %s", (coll["id"],))
    rows = {seq: (props or {}) for seq, props in cur.fetchall()}
    me = item["seq"]
    for prop in selfrefs:
        if prop["key"] not in patch:
            continue
        for target in patch[prop["key"]] or []:
            if target == me:
                raise HTTPException(400, f"자기 자신을 '{prop['label']}' 로 둘 수 없습니다")
            # target 에서 위로 올라가며 나(me)를 만나면 고리다
            seen, cursor = set(), target
            while cursor is not None and cursor not in seen:
                seen.add(cursor)
                if cursor == me:
                    raise HTTPException(
                        400, f"'{prop['label']}' 가 서로를 가리키게 됩니다. "
                             "이미 이 항목의 아래에 있는 것을 위로 둘 수 없습니다.")
                ups = (rows.get(cursor) or {}).get(prop["key"]) or []
                cursor = ups[0] if ups else None


COLL_COLS = "id, project_id, key, title, view, board_by, schema, sort_order, builtin"


def load_collection(cur, cid: int) -> dict:
    cur.execute(f"SELECT {COLL_COLS} FROM collections WHERE id = %s", (cid,))
    rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(404, "표를 찾을 수 없습니다")
    return rows[0]


def load_item(cur, iid: int) -> tuple[dict, dict]:
    """(행, 소속 컬렉션)."""
    cur.execute("""SELECT id, project_id, collection_id, seq, props, sort_order,
                          created_at, updated_at, created_by
                   FROM items WHERE id = %s""", (iid,))
    rows = rows_to_dicts(cur)
    if not rows:
        raise HTTPException(404, "행을 찾을 수 없습니다")
    return rows[0], load_collection(cur, rows[0]["collection_id"])


def public_collection(c: dict) -> dict:
    return {k: v for k, v in c.items() if k != "project_id"}


def public_item(i: dict) -> dict:
    return {k: v for k, v in i.items() if k not in ("project_id", "collection_id")}


@app.get("/api/projects/{pid}/collections")
def list_collections(pid: str, share: str | None = None,
                     user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute(f"""SELECT {COLL_COLS},
                               (SELECT count(*) FROM items i WHERE i.collection_id = c.id) AS items
                        FROM collections c WHERE project_id = %s ORDER BY sort_order, id""", (pid,))
        return [public_collection(c) for c in rows_to_dicts(cur)]


@app.post("/api/projects/{pid}/collections", status_code=201)
def create_collection(pid: str, body: dict, user: dict = Depends(current_user)):
    """템플릿 key(policies·nfr…)면 템플릿으로, 아니면 title·schema 를 받아 사용자 정의 표로."""
    key = str(body.get("key", "")).strip()
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user)
        if key in COLLECTION_TEMPLATES and not body.get("schema"):
            cid = add_collection(cur, pid, key, title=body.get("title"), builtin=True)
        else:
            if not COLL_KEY_RE.match(key):
                raise HTTPException(400, "표 key 는 소문자로 시작하는 영문·숫자·_ 만 됩니다")
            title = str(body.get("title", "")).strip()
            if not title:
                raise HTTPException(400, "표 이름이 필요합니다")
            view = body.get("view", "table")
            if view not in VIEWS:
                raise HTTPException(400, f"보기는 {', '.join(VIEWS)} 중 하나여야 합니다")
            tpl = {"title": title, "view": view, "board_by": body.get("board_by"),
                   "schema": validate_schema(body.get("schema"))}
            cid = add_collection(cur, pid, key, tpl=tpl)
        if cid is None:
            raise HTTPException(409, f"'{key}' 표가 이미 있습니다")
        return public_collection(load_collection(cur, cid))


@app.put("/api/collections/{cid}")
def update_collection(cid: int, body: dict, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        c = load_collection(cur, cid)
        check_write(cur, c["project_id"], user)
        sets, vals = [], []
        if "title" in body:
            title = str(body["title"]).strip()
            if not title:
                raise HTTPException(400, "표 이름이 필요합니다")
            sets.append("title = %s"); vals.append(title)
        schema = c["schema"]
        if "schema" in body:
            schema = validate_schema(body["schema"])
            sets.append("schema = %s"); vals.append(json.dumps(schema, ensure_ascii=False))
        if "view" in body:
            if body["view"] not in VIEWS:
                raise HTTPException(400, f"보기는 {', '.join(VIEWS)} 중 하나여야 합니다")
            sets.append("view = %s"); vals.append(body["view"])
        if "board_by" in body:
            bb = body["board_by"]
            if bb is not None and not any(p["key"] == bb and p["type"] == "select" for p in schema):
                raise HTTPException(400, "board 그룹 기준은 select 속성이어야 합니다")
            sets.append("board_by = %s"); vals.append(bb)
        if "sort_order" in body:
            sets.append("sort_order = %s"); vals.append(int(body["sort_order"]))
        if not sets:
            raise HTTPException(400, "바꿀 내용이 없습니다")
        cur.execute(f"UPDATE collections SET {', '.join(sets)} WHERE id = %s", (*vals, cid))
        return public_collection(load_collection(cur, cid))


@app.delete("/api/collections/{cid}", status_code=204)
def delete_collection(cid: int, user: dict = Depends(current_user)):
    """표를 지우면 행이 전부 사라진다(CASCADE). 프런트가 행 수를 보여주고 두 번 확인한다."""
    with pool.connection() as conn, conn.cursor() as cur:
        c = load_collection(cur, cid)
        check_write(cur, c["project_id"], user)
        cur.execute("DELETE FROM collections WHERE id = %s", (cid,))


@app.get("/api/collections/{cid}/items")
def list_items(cid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        c = load_collection(cur, cid)
        check_access(cur, c["project_id"], user, share)
        cur.execute("""SELECT id, seq, props, sort_order, created_at, updated_at, created_by
                       FROM items WHERE collection_id = %s ORDER BY sort_order, id""", (cid,))
        return rows_to_dicts(cur)


@app.post("/api/collections/{cid}/items", status_code=201)
def create_item(cid: int, body: dict, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        c = load_collection(cur, cid)
        pid = check_write(cur, c["project_id"], user)
        props = validate_props(c["schema"], body.get("props", body))
        after = body.get("after")            # 이 행(id) 바로 뒤에 넣기. 없으면 맨 끝
        sort_order = None
        if after is not None:
            cur.execute("SELECT sort_order FROM items WHERE id = %s AND collection_id = %s",
                        (int(after), cid))
            row = cur.fetchone()
            if row:
                sort_order = row[0] + 1
                cur.execute("""UPDATE items SET sort_order = sort_order + 1
                               WHERE collection_id = %s AND sort_order >= %s""", (cid, sort_order))
        iid, _seq = add_item(cur, pid, cid, props, sort_order=sort_order, user_id=user["id"])
        item, _ = load_item(cur, iid)
        return public_item(item)


@app.put("/api/items/{iid}")
def update_item(iid: int, body: dict, user: dict = Depends(current_user)):
    """준 속성만 덮어쓴다. 스키마에 없는 key 는 무시."""
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_write(cur, c["project_id"], user)
        patch = validate_props(c["schema"], body.get("props", body))
        if not patch:
            raise HTTPException(400, "바꿀 속성이 없습니다")
        old = item["props"] or {}
        check_relation_cycles(cur, c, item, patch)
        props = {**old, **patch}
        cur.execute("UPDATE items SET props = %s, updated_at = now() WHERE id = %s",
                    (json.dumps(props, ensure_ascii=False), iid))
        # 이력은 "고친 기록"이다. 내용이 실제로 달라졌고, 비어 있던 칸을 처음 채운 게 아닐 때만 남긴다
        for key, after in patch.items():
            before = old.get(key)
            if norm(before) == norm(after) or is_blank(before):
                continue
            record_event(cur, iid, user["id"], key, before, after)
        item, _ = load_item(cur, iid)
        return public_item(item)


@app.delete("/api/items/{iid}", status_code=204)
def delete_item(iid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_write(cur, c["project_id"], user)
        cur.execute("DELETE FROM items WHERE id = %s", (iid,))


ITEM_EVENT_KEEP = 20        # 행마다 남기는 이력 개수. 넘으면 오래된 것부터 지운다


EVENT_MERGE_MIN = 10        # 같은 사람이 같은 칸을 이 시간 안에 다시 고치면 한 기록으로 합친다


def is_blank(v) -> bool:
    """비어 있는 값(처음 채우는 경우)인지. 이력을 남기지 않는 기준."""
    return v is None or v == "" or v == [] or v is False


def norm(v):
    """'내용이 같다' 를 판단하는 꼴. 앞뒤 공백·줄바꿈만 다른 글, 비움의 여러 표현은 같은 것으로 본다."""
    if isinstance(v, str):
        v = v.strip()
    return None if is_blank(v) else v


def record_event(cur, iid: int, uid: int, prop: str, before, after) -> None:
    """변경 기록 하나. 같은 사람이 같은 칸을 잇달아 고치면(오타 수정·아이콘 눌러 보기) 한 기록으로 합치고,
    합친 결과 처음 값으로 돌아왔으면 바뀐 게 없으니 기록을 지운다."""
    cur.execute("""SELECT id, before FROM item_events
                   WHERE item_id = %s AND prop = %s AND user_id = %s
                     AND at > now() - make_interval(mins => %s)
                   ORDER BY at DESC, id DESC LIMIT 1""", (iid, prop, uid, EVENT_MERGE_MIN))
    row = cur.fetchone()
    if row:
        eid, first = row
        if norm(first) == norm(after):
            cur.execute("DELETE FROM item_events WHERE id = %s", (eid,))
        else:
            cur.execute("UPDATE item_events SET after = %s, at = now() WHERE id = %s",
                        (json.dumps(after, ensure_ascii=False), eid))
        return
    cur.execute("""INSERT INTO item_events (item_id, user_id, prop, before, after)
                   VALUES (%s, %s, %s, %s, %s)""",
                (iid, uid, prop, json.dumps(before, ensure_ascii=False),
                 json.dumps(after, ensure_ascii=False)))
    trim_events(cur, iid)


def trim_events(cur, iid: int) -> None:
    cur.execute("""DELETE FROM item_events WHERE item_id = %s AND id NOT IN (
                       SELECT id FROM item_events WHERE item_id = %s
                       ORDER BY at DESC, id DESC LIMIT %s)""",
                (iid, iid, ITEM_EVENT_KEEP))


@app.get("/api/items/{iid}/events")
def list_item_events(iid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    """행의 변경 이력. 최근 것부터 100개."""
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_access(cur, c["project_id"], user, share)
        cur.execute("""SELECT e.id, e.prop, e.before, e.after, e.at, u.display_name AS username
                       FROM item_events e LEFT JOIN users u ON u.id = e.user_id
                       WHERE e.item_id = %s ORDER BY e.at DESC, e.id DESC LIMIT %s""",
                    (iid, ITEM_EVENT_KEEP))
        return rows_to_dicts(cur)


@app.delete("/api/items/{iid}/events/{eid}", status_code=204)
def delete_item_event(iid: int, eid: int, user: dict = Depends(current_user)):
    """이력 하나를 지운다 — 편집자 이상."""
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_write(cur, c["project_id"], user)
        cur.execute("DELETE FROM item_events WHERE id = %s AND item_id = %s", (eid, iid))
        if cur.rowcount == 0:
            raise HTTPException(404, "그 이력이 없습니다")


def like_pattern(q: str) -> str:
    """ILIKE 의 % _ \\ 를 글자 그대로 찾게 감싼다."""
    esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{esc}%"


@app.get("/api/projects/{pid}/items")
def search_items(pid: str, q: str = "", collection: str = "", share: str | None = None,
                 user: dict | None = Depends(opt_user)):
    """프로젝트의 행을 값 부분 일치(대소문자 무시)나 번호로 찾는다. 최대 200개.
    props::text 의 trigram 인덱스(items_props_trgm_idx)를 탄다."""
    q = (q or "").strip()
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("""SELECT i.id, i.seq, i.props, c.key AS collection
                       FROM items i JOIN collections c ON c.id = i.collection_id
                       WHERE i.project_id = %s
                         AND (%s = '' OR c.key = %s)
                         AND (%s = '' OR i.props::text ILIKE %s OR i.seq::text = %s)
                       ORDER BY c.sort_order, c.id, i.sort_order, i.id LIMIT 200""",
                    (pid, collection, collection, q, like_pattern(q), q))
        return rows_to_dicts(cur)


def item_by_seq(pid: str, seq: int, user: dict | None = None, share: str | None = None):
    """번호로 행 하나와 그 표를. MCP 의 get_item·update_item 이 쓴다 (UNIQUE (project_id, seq) 한 번 조회)."""
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("""SELECT id, seq, props, sort_order, created_at, updated_at, created_by, collection_id
                       FROM items WHERE project_id = %s AND seq = %s""", (pid, seq))
        rows = rows_to_dicts(cur)
        if not rows:
            return None
        it = rows[0]
        return it, public_collection(load_collection(cur, it.pop("collection_id")))


@app.post("/api/items/{iid}/move")
def move_item(iid: int, body: dict, user: dict = Depends(current_user)):
    """같은 표 안에서 한 칸 위(-1)·아래(+1). 노드의 ▲▼ 와 같은 방식."""
    direction = int(body.get("dir", 0))
    if direction not in (-1, 1):
        raise HTTPException(400, "dir 은 -1 또는 1")
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_write(cur, c["project_id"], user)
        cur.execute("SELECT id FROM items WHERE collection_id = %s ORDER BY sort_order, id",
                    (c["id"],))
        ids = [r[0] for r in cur.fetchall()]
        i = ids.index(iid)
        j = i + direction
        if j < 0 or j >= len(ids):
            return {"moved": False}
        ids[i], ids[j] = ids[j], ids[i]
        for order, item_id in enumerate(ids):          # 순서를 0..n-1 로 다시 매긴다
            cur.execute("UPDATE items SET sort_order = %s WHERE id = %s", (order, item_id))
    return {"moved": True}


# ---------- prd ----------
class PrdIn(BaseModel):
    content: str


@app.get("/api/projects/{pid}/prd")
def get_prd(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
        return {"content": cur.fetchone()[0]}


@app.put("/api/projects/{pid}/prd")
def put_prd(pid: str, body: PrdIn, share: str | None = None,
            user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
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
def list_nodes(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("SELECT * FROM nodes WHERE project_id = %s ORDER BY sort_order, id", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/nodes", status_code=201)
def create_node(pid: str, body: NodeIn, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
        if body.parent_id is not None and node_project(cur, body.parent_id) != pid:
            raise HTTPException(400, "다른 프로젝트의 항목 아래에는 추가할 수 없습니다")
        cur.execute(
            """INSERT INTO nodes (project_id, parent_id, title, sort_order, seq)
               VALUES (%s, %s, %s, (SELECT coalesce(max(sort_order), -1) + 1 FROM nodes
                                    WHERE project_id = %s
                                    AND parent_id IS NOT DISTINCT FROM %s), %s)
               RETURNING *""",
            (pid, body.parent_id, body.title, pid, body.parent_id, alloc_seq(cur, pid)))
        return rows_to_dicts(cur)[0]


@app.put("/api/nodes/{node_id}")
def update_node(node_id: int, body: NodeUpdate, share: str | None = None,
                user: dict | None = Depends(opt_user)):
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields")
    with pool.connection() as conn, conn.cursor() as cur:
        pid = node_project(cur, node_id)
        pid = check_write(cur, pid, user, share)
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
        check_write(cur, node_project(cur, node_id), user, share)
        cur.execute("DELETE FROM nodes WHERE id = %s", (node_id,))


# ---------- 용어 사전 ----------
TERM_RE = re.compile(r"`([^`\n]{1,60})`")


class TermIn(BaseModel):
    description: str | None = None
    note: str | None = None
    category_id: int | None = None
    sort_order: int | None = None


def sync_terms(cur, pid: int):
    """본문(PRD·기능 설명)에 있는 `용어` 를 훑어 없는 건 만들고, 안 쓰이는 건 지운다."""
    cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
    texts = [cur.fetchone()[0]]
    cur.execute("SELECT description FROM nodes WHERE project_id = %s"
                " ORDER BY sort_order, id", (pid,))
    texts += [r[0] for r in cur.fetchall()]
    # 컬렉션 행의 md 속성(정책 본문, PRD 섹션 등)도 본문이다 (PLAN 1.9)
    cur.execute("""SELECT i.props, c.schema FROM items i
                   JOIN collections c ON c.id = i.collection_id
                   WHERE i.project_id = %s ORDER BY c.sort_order, i.sort_order, i.id""", (pid,))
    for props, schema in cur.fetchall():
        for prop in schema or []:
            if prop.get("type") == "md":
                texts.append((props or {}).get(prop["key"]) or "")

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
def list_terms(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        sync_terms(cur, pid)
        cur.execute("""
            SELECT t.id, t.term, t.description, t.note, t.category_id, t.sort_order,
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
        check_write(cur, row[0], user, share)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise HTTPException(400, "no fields")
        sets = ", ".join(f"{k} = %s" for k in fields)
        cur.execute(f"UPDATE terms SET {sets} WHERE id = %s"
                    " RETURNING id, term, description, note, category_id, sort_order",
                    (*fields.values(), tid))
        return rows_to_dicts(cur)[0]


class CategoryIn(BaseModel):
    name: str


@app.get("/api/projects/{pid}/term-categories")
def list_categories(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_access(cur, pid, user, share)
        cur.execute("SELECT id, name FROM term_categories WHERE project_id = %s ORDER BY id", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/term-categories", status_code=201)
def create_category(pid: str, body: CategoryIn, share: str | None = None,
                    user: dict | None = Depends(opt_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "카테고리 이름이 필요합니다")
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
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
        check_write(cur, row[0], user, share)
        cur.execute("DELETE FROM term_categories WHERE id = %s", (cid,))


# ---------- versions (PRD + 기능명세서 스냅샷) ----------
NODE_FIELDS = ("id", "parent_id", "title", "description", "status", "importance", "sort_order", "seq")


@app.post("/api/projects/{pid}/versions", status_code=201)
def save_version(pid: str, share: str | None = None, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
        cur.execute(f"SELECT {', '.join(NODE_FIELDS)} FROM nodes WHERE project_id = %s"
                    " ORDER BY sort_order, id", (pid,))
        snapshot = rows_to_dicts(cur)
        cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
        prd = cur.fetchone()[0]
        # 컬렉션과 행. id·seq 를 그대로 담아 복원 때 링크가 안 깨지게 한다 (PLAN 1.8)
        cur.execute(f"SELECT {COLL_COLS} FROM collections WHERE project_id = %s ORDER BY sort_order, id",
                    (pid,))
        colls = rows_to_dicts(cur)
        for c in colls:
            c.pop("project_id", None)
            cur.execute("""SELECT id, seq, props, sort_order FROM items
                           WHERE collection_id = %s ORDER BY sort_order, id""", (c["id"],))
            c["items"] = rows_to_dicts(cur)
        item_count = sum(len(c["items"]) for c in colls)
        cur.execute("""INSERT INTO versions (project_id, user_id, username, data, prd, collections)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, created_at""",
                    (pid, user["id"], user["display_name"], json.dumps(snapshot), prd,
                     json.dumps(colls, ensure_ascii=False, default=str)))
        vid, created = cur.fetchone()
    return {"id": vid, "created_at": created, "username": user["display_name"],
            "node_count": len(snapshot), "item_count": item_count}


@app.get("/api/projects/{pid}/versions")
def list_versions(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
        cur.execute("""SELECT id, username, created_at, jsonb_array_length(data) AS node_count,
                              (SELECT coalesce(sum(jsonb_array_length(c->'items')), 0)::int
                                 FROM jsonb_array_elements(coalesce(collections, '[]'::jsonb)) c) AS item_count
                       FROM versions WHERE project_id = %s ORDER BY created_at DESC""", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/versions/{vid}/restore")
def restore_version(vid: int, share: str | None = None, user: dict = Depends(current_user)):
    """PRD 와 기능 트리를 그 시점으로 되돌린다. 살아남는 항목은 id 를 유지해 코멘트가 보존된다."""
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id, data, prd, collections FROM versions WHERE id = %s", (vid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        pid, snapshot, prd, colls = row
        pid = check_write(cur, pid, user, share)
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
                                   status, importance, sort_order, seq)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    parent_id = EXCLUDED.parent_id, title = EXCLUDED.title,
                    description = EXCLUDED.description, status = EXCLUDED.status,
                    importance = EXCLUDED.importance, sort_order = EXCLUDED.sort_order,
                    seq = COALESCE(EXCLUDED.seq, nodes.seq)
                WHERE nodes.project_id = EXCLUDED.project_id""",
                (n["id"], pid, n["parent_id"], n["title"], n["description"],
                 n["status"], n["importance"], n["sort_order"], n.get("seq")))
        cur.execute("""SELECT setval(pg_get_serial_sequence('nodes', 'id'),
                       GREATEST((SELECT coalesce(max(id), 1) FROM nodes), 1))""")
        # 옛 스냅샷(seq 없음)에서 살아난 노드에 번호를 준다
        cur.execute("SELECT id FROM nodes WHERE project_id = %s AND seq IS NULL ORDER BY id", (pid,))
        for (nid,) in cur.fetchall():
            cur.execute("UPDATE nodes SET seq = %s WHERE id = %s", (alloc_seq(cur, pid), nid))

        # 컬렉션·행. 스냅샷에 없는 것은 지우고, 있는 것은 id·seq 를 지켜 UPSERT (PLAN 1.8)
        restored_items = 0
        if colls is not None:
            keep_c = [c["id"] for c in colls] or [0]
            cur.execute("DELETE FROM collections WHERE project_id = %s AND NOT (id = ANY(%s))",
                        (pid, keep_c))
            keep_i = [it["id"] for c in colls for it in c.get("items", [])] or [0]
            cur.execute("DELETE FROM items WHERE project_id = %s AND NOT (id = ANY(%s))", (pid, keep_i))
            for c in colls:
                cur.execute("""
                    INSERT INTO collections (id, project_id, key, title, view, board_by, schema,
                                             sort_order, builtin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        key = EXCLUDED.key, title = EXCLUDED.title, view = EXCLUDED.view,
                        board_by = EXCLUDED.board_by, schema = EXCLUDED.schema,
                        sort_order = EXCLUDED.sort_order, builtin = EXCLUDED.builtin
                    WHERE collections.project_id = EXCLUDED.project_id""",
                    (c["id"], pid, c["key"], c["title"], c.get("view", "table"), c.get("board_by"),
                     json.dumps(c.get("schema") or [], ensure_ascii=False),
                     c.get("sort_order", 0), bool(c.get("builtin"))))
                for it in c.get("items", []):
                    cur.execute("""
                        INSERT INTO items (id, project_id, collection_id, seq, props, sort_order)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id) DO UPDATE SET
                            collection_id = EXCLUDED.collection_id, seq = EXCLUDED.seq,
                            props = EXCLUDED.props, sort_order = EXCLUDED.sort_order,
                            updated_at = now()
                        WHERE items.project_id = EXCLUDED.project_id""",
                        (it["id"], pid, c["id"], it["seq"],
                         json.dumps(it.get("props") or {}, ensure_ascii=False), it.get("sort_order", 0)))
                    restored_items += 1
            cur.execute("""SELECT setval(pg_get_serial_sequence('collections', 'id'),
                           GREATEST((SELECT coalesce(max(id), 1) FROM collections), 1))""")
            cur.execute("""SELECT setval(pg_get_serial_sequence('items', 'id'),
                           GREATEST((SELECT coalesce(max(id), 1) FROM items), 1))""")
        # 번호 카운터는 되살린 최대 번호 이상이어야 한다
        cur.execute("""UPDATE projects p SET next_seq = GREATEST(p.next_seq,
                         coalesce((SELECT max(seq) FROM nodes n WHERE n.project_id = p.id), 0),
                         coalesce((SELECT max(seq) FROM items i WHERE i.project_id = p.id), 0))
                       WHERE p.id = %s""", (pid,))
    return {"restored": len(snapshot), "items": restored_items}


@app.delete("/api/versions/{vid}", status_code=204)
def delete_version(vid: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT project_id FROM versions WHERE id = %s", (vid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "버전을 찾을 수 없습니다")
        check_write(cur, row[0], user)
        cur.execute("DELETE FROM versions WHERE id = %s", (vid,))


# ---------- images ----------
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# Content-Type 헤더는 클라이언트가 정하는 값이라 믿을 수 없다. 실제 앞바이트로 확인한다.
# SVG 는 스크립트를 품을 수 있어 아예 받지 않는다 (같은 출처로 서빙되므로 곧 XSS 가 된다)
IMAGE_MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}


def sniff_image(mime: str, data: bytes) -> str:
    """허용 목록에 있고 앞바이트가 맞는 MIME 만 돌려준다."""
    mime = mime.split(";")[0].strip().lower()
    sigs = IMAGE_MAGIC.get(mime)
    if not sigs:
        raise HTTPException(400, "PNG · JPEG · GIF · WebP 만 올릴 수 있습니다")
    if not any(data.startswith(sig) for sig in sigs):
        raise HTTPException(400, "파일 내용이 이미지가 아닙니다")
    if mime == "image/webp" and data[8:12] != b"WEBP":
        raise HTTPException(400, "파일 내용이 이미지가 아닙니다")
    return mime


@app.post("/api/projects/{pid}/images", status_code=201)
async def upload_image(pid: str, request: Request, share: str | None = None,
                       user: dict | None = Depends(opt_user)):
    data = await request.body()
    if not data:
        raise HTTPException(400, "빈 파일입니다")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "이미지는 5MB 이하만 올릴 수 있습니다")
    mime = sniff_image(request.headers.get("content-type", ""), data)
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
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
                    (img_id, pid, mime, data))
    return {"url": f"/api/images/{img_id}"}


class ImageIds(BaseModel):
    ids: list[str]


@app.get("/api/projects/{pid}/images")
def list_images(pid: str, share: str | None = None, user: dict | None = Depends(opt_user)):
    """앨범 목록. used = 본문(PRD·기능 설명)에서 링크로 쓰이는 중인지."""
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
        cur.execute("""
            SELECT i.id, i.mime, i.created_at, length(i.data) AS bytes,
                   (EXISTS (SELECT 1 FROM projects p
                            WHERE p.id = i.project_id
                              AND position('/api/images/' || i.id in p.prd) > 0)
                    OR EXISTS (SELECT 1 FROM nodes n
                               WHERE n.project_id = i.project_id
                                 AND position('/api/images/' || i.id in n.description) > 0)
                    OR EXISTS (SELECT 1 FROM items it
                               WHERE it.project_id = i.project_id
                                 AND position('/api/images/' || i.id in it.props::text) > 0)) AS used
            FROM images i WHERE i.project_id = %s
            ORDER BY i.created_at DESC, i.id""", (pid,))
        return rows_to_dicts(cur)


@app.post("/api/projects/{pid}/images/delete")
def delete_images(pid: str, body: ImageIds, share: str | None = None,
                  user: dict = Depends(current_user)):
    if not body.ids:
        raise HTTPException(400, "선택된 이미지가 없습니다")
    with pool.connection() as conn, conn.cursor() as cur:
        pid = check_write(cur, pid, user, share)
        cur.execute("DELETE FROM images WHERE project_id = %s AND id = ANY(%s)"
                    " RETURNING id, length(data)", (pid, body.ids))
        rows = cur.fetchall()
        gone = [r[0] for r in rows]
        sizes = [r[1] for r in rows]
        cleaned = strip_image_refs(cur, pid, gone)
    return {"deleted": len(sizes), "bytes": sum(sizes), "cleaned": cleaned}


def strip_image_refs(cur, pid: int, img_ids: list[str]) -> int:
    """지운 이미지를 가리키던 `![](…/api/images/<id>)` 를 본문에서 걷어낸다.

    이미지는 FK 없이 텍스트로만 이어져 있어서(ERD 의 "문자열로만 연결된 참조"),
    행을 지워도 본문에는 남아 깨진 그림이 된다. 여기서 같이 치운다.
    주소는 절대·상대 둘 다 쓰이므로 id 만 보고 지운다.
    """
    if not img_ids:
        return 0
    ids = "|".join(re.escape(i) for i in img_ids)
    pattern = r"!@[[^@]]*@]@([^)]*/api/images/(?:" + ids + r")[^)]*@)"
    pattern = pattern.replace("@", chr(92))
    changed = 0

    cur.execute("""SELECT id, description FROM nodes
                   WHERE project_id = %s AND description ~ %s""", (pid, pattern))
    for nid, text in cur.fetchall():
        cur.execute("UPDATE nodes SET description = %s WHERE id = %s",
                    (re.sub(pattern, "", text), nid))
        changed += 1

    cur.execute("SELECT prd FROM projects WHERE id = %s", (pid,))
    prd = cur.fetchone()[0] or ""
    if re.search(pattern, prd):
        cur.execute("UPDATE projects SET prd = %s WHERE id = %s",
                    (re.sub(pattern, "", prd), pid))
        changed += 1

    cur.execute("""SELECT i.id, i.props, c.schema FROM items i
                   JOIN collections c ON c.id = i.collection_id
                   WHERE i.project_id = %s AND i.props::text ~ %s""", (pid, pattern))
    for iid, props, schema in cur.fetchall():
        props = props or {}
        hit = False
        for prop in schema or []:
            if prop["type"] != "md":
                continue
            val = props.get(prop["key"])
            if isinstance(val, str) and re.search(pattern, val):
                props[prop["key"]] = re.sub(pattern, "", val)
                hit = True
        if hit:
            cur.execute("UPDATE items SET props = %s WHERE id = %s",
                        (json.dumps(props, ensure_ascii=False), iid))
            changed += 1
    return changed


@app.get("/api/images/{img_id}")
def get_image(img_id: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT mime, data FROM images WHERE id = %s", (img_id,))
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "이미지를 찾을 수 없습니다")
    mime = row[0] if row[0] in IMAGE_MAGIC else "application/octet-stream"
    return Response(content=bytes(row[1]), media_type=mime,
                    headers={"Cache-Control": "public, max-age=31536000",
                             "X-Content-Type-Options": "nosniff"})


# ---------- comments ----------
class CommentIn(BaseModel):
    content: str


@app.get("/api/nodes/{node_id}/comments")
def list_comments(node_id: int, share: str | None = None,
                  user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        check_access(cur, node_project(cur, node_id), user, share)
        cur.execute("""SELECT c.id, c.node_id, c.user_id, u.display_name AS username,
                              u.avatar, c.content, c.created_at
                       FROM comments c JOIN users u ON u.id = c.user_id
                       WHERE c.node_id = %s ORDER BY c.created_at""", (node_id,))
        return rows_to_dicts(cur)


@app.post("/api/nodes/{node_id}/comments", status_code=201)
def create_comment(node_id: int, body: CommentIn, share: str | None = None,
                   user: dict = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "empty comment")
    with pool.connection() as conn, conn.cursor() as cur:
        check_comment(cur, node_project(cur, node_id), user, share)
        cur.execute("""INSERT INTO comments (node_id, user_id, content)
                       VALUES (%s, %s, %s) RETURNING id, node_id, content, created_at""",
                    (node_id, user["id"], body.content.strip()))
        return {**rows_to_dicts(cur)[0], "user_id": user["id"],
                "username": user["display_name"]}


@app.get("/api/items/{iid}/comments")
def list_item_comments(iid: int, share: str | None = None, user: dict | None = Depends(opt_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_access(cur, c["project_id"], user, share)
        cur.execute("""SELECT c.id, c.item_id, c.user_id, u.display_name AS username,
                              u.avatar, c.content, c.created_at
                       FROM comments c JOIN users u ON u.id = c.user_id
                       WHERE c.item_id = %s ORDER BY c.created_at""", (iid,))
        return rows_to_dicts(cur)


@app.post("/api/items/{iid}/comments", status_code=201)
def create_item_comment(iid: int, body: CommentIn, share: str | None = None,
                        user: dict = Depends(current_user)):
    if not body.content.strip():
        raise HTTPException(400, "empty comment")
    with pool.connection() as conn, conn.cursor() as cur:
        item, c = load_item(cur, iid)
        check_comment(cur, c["project_id"], user, share)
        cur.execute("""INSERT INTO comments (item_id, user_id, content)
                       VALUES (%s, %s, %s) RETURNING id, item_id, content, created_at""",
                    (iid, user["id"], body.content.strip()))
        return {**rows_to_dicts(cur)[0], "user_id": user["id"],
                "username": user["display_name"]}


@app.delete("/api/comments/{comment_id}", status_code=204)
def delete_comment(comment_id: int, user: dict = Depends(current_user)):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM comments WHERE id = %s AND user_id = %s",
                    (comment_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(404, "본인 코멘트만 삭제할 수 있습니다")


# ---------- OAuth 승인 화면 ----------
def oauth_login_page(request_id: str, client_name: str, error: str = "", status: int = 200):
    safe_request = html.escape(request_id, quote=True)
    safe_client = html.escape(client_name or "ChatGPT / Codex")
    error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
    body = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Olgae 연결</title>
<link rel="icon" type="image/png" href="/favicon.png"><style>
body{{margin:0;background:#f4f5f7;color:#202124;font-family:system-ui,sans-serif}}
main{{max-width:420px;margin:10vh auto;padding:28px;background:white;border:1px solid #ddd;border-radius:16px}}
h1{{font-size:24px;margin:0 0 10px}} p{{line-height:1.55;color:#666}}
label{{display:block;margin:16px 0 6px;font-weight:650}} input{{box-sizing:border-box;width:100%;padding:12px;border:1px solid #bbb;border-radius:9px;font-size:16px}}
button{{width:100%;margin-top:22px;padding:12px;border:0;border-radius:9px;background:#242424;color:white;font-size:16px;font-weight:700;cursor:pointer}}
.client{{color:#202124;font-weight:700}} .error{{padding:10px;border-radius:8px;background:#fff0ef;color:#b42318}}
small{{display:block;margin-top:14px;color:#777;line-height:1.45}}
</style></head><body><main><h1>얼개 플래너 연결</h1>
<p><span class="client">{safe_client}</span>에서 내 프로젝트를 읽고 편집하도록 승인합니다.</p>
{error_html}<form method="post" action="/oauth/login">
<input type="hidden" name="request_id" value="{safe_request}">
<label for="login_id">아이디</label><input id="login_id" name="login_id" autocomplete="username" required maxlength="200">
<label for="password">비밀번호</label><input id="password" name="password" type="password" autocomplete="current-password" required maxlength="1000">
<button type="submit">로그인하고 연결 승인</button></form>
<small>비밀번호는 얼개 플래너에서만 확인하며 ChatGPT나 Codex에 전달하지 않습니다.</small>
</main></body></html>"""
    return HTMLResponse(body, status_code=status, headers={
        "Cache-Control": "no-store", "Pragma": "no-cache",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://chatgpt.com; base-uri 'none'; frame-ancestors 'none'",
        "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    })


@app.get("/oauth/login")
async def oauth_login_form(request: str):
    pending = await mcp_app.provider.pending_info(request)
    if not pending:
        return oauth_login_page("", "", "승인 요청이 만료되었거나 올바르지 않습니다.", 410)
    return oauth_login_page(request, pending["client_name"])


@app.post("/oauth/login")
async def oauth_login_submit(request: Request):
    form = await request.form()
    request_id = str(form.get("request_id", ""))[:300]
    login_id = str(form.get("login_id", ""))[:200]
    password = str(form.get("password", ""))[:1000]
    pending = await mcp_app.provider.pending_info(request_id)
    if not pending:
        return oauth_login_page("", "", "승인 요청이 만료되었거나 올바르지 않습니다.", 410)
    try:
        user = authenticate_user(login_id, password, request)
    except HTTPException as exc:
        return oauth_login_page(request_id, pending["client_name"], str(exc.detail), exc.status_code)
    redirect_url = await mcp_app.provider.complete_authorization(request_id, user["id"])
    if not redirect_url:
        return oauth_login_page("", "", "승인 요청이 만료되었습니다. 연결을 다시 시작하세요.", 410)
    return RedirectResponse(redirect_url, status_code=302, headers={"Cache-Control": "no-store"})


# ---------- MCP (/mcp) ----------
# 위 핸들러들을 재사용하므로 정의가 끝난 이 자리에서 import 한다.
import mcp_app  # noqa: E402

app.mount("/oauth-server", mcp_app.asgi_app())
