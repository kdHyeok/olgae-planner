# 얼개 플래너 (olgae-planner)

PRD · 기능명세서 · 작업을 **번호 하나로 잇는** 기획 관리 도구(브랜드 Olgae). PRD 는 정책·요구사항 같은 표(컬렉션)로,
기능명세서는 트리로, 작업은 칸반으로 다루고, 셋이 `[[P1-14]]` 링크로 서로를 가리킵니다. AI 에이전트는 MCP 로 같은 데이터를 읽고 고칩니다.

## 주요 기능

- **PRD 탭 = 표(컬렉션)의 모음**. 기본 `PRD` 표는 섹션 문서(제목 + 마크다운), 그 밖의 표는
  속성(`text` · `md` · `select` · `checkbox` · `relation`)이 열. 왼쪽 목차로 오가고, `+ 표 추가` 로
  템플릿(정책·NFR·미결정·테스트·액터·흐름·타겟 사용자·기기·도메인)이나 빈 표를 만든다.
  표의 `설정` 에서 이름·보기(문서/표/칸반)·속성을 직접 편집(`prd`·`tasks` 는 지울 수 없음).
  셀·본문은 **더블클릭**으로 그 자리에서 편집(Ctrl+Enter 저장 · Esc 취소), ▲▼ 순서, 추가 버튼은 표 아래.
- **기능명세서 탭** — 최대 4단계 트리. **트리 뷰**(마인드맵)와 **디렉토리 뷰**(목록 + 상세).
  카드 `＋` 로 하위 추가, 드래그로 이동·대분류 승격(순환 차단), ▲▼, 접기/펼치기, 상태·MoSCoW 중요도.
- **번호와 링크** — 기능·표 행·작업이 프로젝트 안 **하나의 번호**를 공유하고 `P1-14` 로 표기.
  키(`P1`)는 자동 부여되며 목록의 `키` 버튼으로 바꿀 수 있고(같은 계정 안 중복은 409), 링크는 번호 기준이라 안 깨진다.
  - 본문의 `[[P1-14]]` 는 **링크 칩**(기능 파랑 · 행 초록 · 없는 번호 빗금). 누르면 탭을 바꿔 이동
  - `관련`(relation) 속성은 `＋` 로 검색해 연결. 대상을 특정 표나 `기능명세서 만` 으로 제한 가능
  - **역참조** — "이 기능을 가리키는 항목" 줄, `참조 N` 배지, 표의 `추적표` 보기. 손으로 쓰는 추적표가 필요 없다
- **작업판(칸반)** — `tasks` 표는 상태(할일·진행중·완료)가 열. 카드를 끌어 상태 변경, 종류(`● 작업` · `◈ 에픽` · `! 이슈`)는
  맨 위 아이콘으로. **상위 작업**을 정하면 상대에 **하위 작업**으로 자동 반영, 서로 상위가 되는 고리는 차단.
  카드의 행 상세 = 내용 · **이력**(내용이 실제로 바뀐 저장만, 10분 안 되돌리면 사라짐, 하나씩 삭제 가능) · 코멘트.
- **버전 기록** — 헤더 저장 아이콘 한 번으로 PRD 섹션·모든 표·기능 트리를 스냅샷. 복원해도 id·번호가 유지되어 링크·코멘트가 안 깨진다.
- **내보내기** — 헤더 `⋯` → PRD 섹션 → 표 → 작업(상태별) → 기능명세서 순의 `<프로젝트명>.md` 한 파일.
  `[[P1-14]]` 와 관련 값은 문서 안 앵커 링크로.
- **이미지** — 편집 중 붙여넣기·끌어놓기·버튼. DB 저장, 본문엔 `![](/api/images/<id>)`. 한 장 5MB.
  **이미지 앨범**에서 사용중 표시·선택 삭제. 지우면 본문의 참조도 함께 정리.
- **용어 사전** — 본문의 `` `용어` `` 를 자동 수집해 표로(안 쓰이면 자동 삭제). 마우스를 올리면 설명 말풍선,
  사용처로 이동, 카테고리 분류.
- **마크다운** — 제목 `#`~`######` · `**굵게**` `*기울임*` · 불릿/번호/중첩 목록 · 표(정렬 지정 가능) · 인용 `>` ·
  코드 블록 · `---` · 링크(주소만 써도 자동, 새 탭, `javascript:`·`data:` 차단) · 이미지.
- **사용자** — 로그인 ID + 표시 이름 + 8자 이상 비밀번호. **가입 승인제**(첫 계정이 관리자).
  로그인 실패 잠금: IP+계정 5회 또는 IP 20회 → 30초부터 30분까지 단계적, 24시간 조용하면 초기화.
  등급별 한도: 프로젝트 `admin` ∞ · `pro` 5 · `member` 3 · `guest` 1 / 이미지 총량 ∞ · 500MB · 200MB · 50MB(소유자 기준 차감).
  헤더 사용자 아이콘 → 프로필 이미지 · 등급 · 남은 한도 · 비밀번호 변경.
- **프로젝트 / 멤버** — 여러 프로젝트. **공유 링크는 읽기 전용**이고, 링크로 들어온 로그인 사용자는 **참여 요청**,
  소유자·공동 소유자가 `멤버 관리` 에서 승인·권한 변경·제외. 참여중인 프로젝트는 내 목록에 소유자 이름·권한과 함께.

  | 등급 | 할 수 있는 일 |
  |---|---|
  | 공유 링크 · 비로그인 | 읽기, 마크다운 내보내기 |
  | 공유 링크 · 로그인(미승인) | 위 + 코멘트 |
  | **편집자** | 위 + 내용 수정, 이미지 앨범, 버전 기록, MCP·플러그인으로 조회 |
  | **공동 소유자** | 위 + 공유 링크 관리, 멤버 관리, 이름 변경 |
  | 소유자 | 위 + 프로젝트 삭제 |

- **관리자 페이지**(`/admin`, admin 만) — 계정 정보·등급 변경·삭제, 계정별 프로젝트 삭제, 가입 허용 토글과 승인·거절.
  마지막 관리자는 강등·삭제 불가.
- **주소** — `/` 내 프로젝트 · `/project/<slug>` · `/admin`. 프로젝트는 순번 대신 **랜덤 slug** 로 가리킨다(API 도 같음).
  화면 상태는 쿼리로 — `?tab=spec|tasks` · `&view=dir` · `?item=<번호>` · `?node=<번호>` · 공유는 `/?share=<토큰>`.
  새로고침·뒤로 가기가 그대로 동작. `/admin` 은 `robots.txt` 와 `X-Robots-Tag: noindex` 로 색인 차단.
- 기존 마크다운 PRD 안의 표(정책·NFR·미결정·테스트)는 `backend/migrate_prd_tables.py` 로 행으로 옮길 수 있다(원래 ID 는 `legacy_id` 로 보존).

## 구성

| 서비스 | 스택 | 역할 |
|---|---|---|
| `frontend` | nginx + 정적 HTML/JS (빌드 없음) | UI 서빙, `/api` 프록시 |
| `backend` | Python FastAPI + psycopg | REST API |
| `db` | PostgreSQL 16 | 데이터 저장 (named volume) |

```
frontend (nginx :80 → 호스트 :3000)
   └─ /api/* 프록시 → backend (uvicorn :8000)
                         └─ db (postgres :5432, volume: dbdata)
```

## 배포 방법

요구사항: Docker + Docker Compose v2 (그 외 아무것도 설치할 필요 없음)

```bash
git clone https://github.com/kdHyeok/olgae-planner.git
cd olgae-planner
cp .env.example .env          # POSTGRES_PASSWORD 를 반드시 채운다
docker compose up --build -d
```

`.env` 에 `POSTGRES_PASSWORD` 가 없으면 compose 가 기동을 거부합니다(기본 비밀번호를 쓰지 않도록).
`.env` 는 git 에 올라가지 않습니다.

브라우저에서 **http://localhost:3000** 접속. 끝.

- 첫 기동 시 백엔드가 테이블을 만들고 샘플 PRD/기능 트리를 자동 시드합니다.
- 데이터는 `dbdata` 볼륨에 저장되어 컨테이너를 재시작해도 유지됩니다.
- **처음 가입한 계정이 관리자**가 됩니다. 그 뒤의 가입은 관리자 승인을 받아야 로그인됩니다.
- 옛 마크다운 PRD 의 표를 행으로 옮기려면(선택) `docker compose exec -T backend python migrate_prd_tables.py <slug>` (DRY RUN → `--apply` / `--undo`).

### 운영 명령

```bash
# 중지
docker compose down

# 데이터까지 초기화(시드 재생성)
docker compose down -v

# 코드 수정 후 재배포
docker compose up -d --build
```

### 포트/설정 변경

- 서비스 포트: `docker-compose.yml`의 `frontend.ports`(`"3000:80"`) 수정
- OAuth 공개 주소: `PUBLIC_URL` (기본값 `http://localhost:3000`). 외부에 배포하면
  `.env`에 `PUBLIC_URL=https://실제-도메인`을 반드시 지정합니다. HTTPS 주소와 `/mcp` 외부 경로가 실제 접속 주소와 같아야 합니다
- DB 계정/비밀번호: `.env` 의 `POSTGRES_USER`·`POSTGRES_PASSWORD`·`POSTGRES_DB`
  (`DATABASE_URL` 은 compose 가 이 값들로 조립합니다. 기존 볼륨의 비밀번호는 최초 생성 시점에 정해지므로,
  바꾸려면 `docker compose down -v` 로 초기화해야 합니다)

## API

콘텐츠 API는 소유자 로그인(`Authorization: Bearer <token>`) 또는 유효한 공유 토큰(`?share=<token>`)이 필요합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/projects` | 내 프로젝트 목록 / 생성 (`{name}`) — 로그인 필요 |
| PUT / DELETE | `/api/projects/{pid}` | 이름 변경 / 삭제 — 소유자만 |
| POST / DELETE | `/api/projects/{pid}/share` | 공유 링크 생성 / 해제 — 소유자만 |
| GET | `/api/shared/{token}` | 공유 토큰으로 프로젝트 확인 — 소유자 이름·내 참여 상태 포함 (공개) |
| POST | `/api/projects/{pid}/join` | 참여 요청 (로그인 + 유효한 `share` 필요) |
| GET | `/api/projects/{pid}/members` | 멤버·참여 요청 목록 — 공동 소유자 이상 |
| POST | `/api/projects/{pid}/members/{uid}/approve` | 승인 (`{role}`: `editor`·`coowner`) — 공동 소유자 이상 |
| PUT | `/api/projects/{pid}/members/{uid}/role` | 권한 변경 (`{role}`) — 공동 소유자 이상 |
| DELETE | `/api/projects/{pid}/members/{uid}` | 거절·멤버 제외 — 공동 소유자 이상 |
| GET / PUT | `/api/projects/{pid}/prd` | PRD 마크다운 조회/저장 (`{content}`) — legacy. 화면은 `prd` 컬렉션을 씀 |
| GET / POST | `/api/projects/{pid}/collections` | 표 목록 / 표 추가 (`{key}` 만 주면 템플릿, 아니면 `{key, title, view, schema}`) — 편집자 이상 |
| PUT / DELETE | `/api/collections/{cid}` | 표 이름·보기·`board_by`·속성 정의·순서 변경 / 삭제(행 CASCADE) — 편집자 이상 |
| GET / POST | `/api/collections/{cid}/items` | 행 목록 / 행 추가 (`{props, after?}`) — 번호(seq) 자동 발급 |
| PUT / DELETE | `/api/items/{iid}` | 행 속성 부분 수정 (`{props}`, 스키마에 없는 key 무시·타입 검증) / 삭제 |
| POST | `/api/items/{iid}/move` | 같은 표 안에서 한 칸 위·아래 (`{dir}` = -1 또는 1) |
| GET | `/api/items/{iid}/events` | 행 변경 이력 (최근 20). 내용이 실제로 달라진 저장만, 같은 사람의 10분 안 연속 편집은 한 기록으로, 되돌아오면 기록 없음 |
| DELETE | `/api/items/{iid}/events/{eid}` | 이력 하나 삭제 — 편집자 이상 |
| GET | `/api/projects/{pid}/items` | 행 검색 `?q=&collection=` — 값 부분 일치(대소문자 무시) 또는 번호, 최대 200. `pg_trgm` 인덱스를 탄다 |
| GET / POST | `/api/items/{iid}/comments` | 행 코멘트 목록 / 작성 (`{content}`) |
| GET | `/api/projects/{pid}/resolve/{seq}` | 번호 → 기능 노드 또는 표 행 (`{kind, id, title, collection?, label}`) |
| PUT | `/api/projects/{pid}/key` | 번호 앞부분 변경 (`{key}`, 대문자 2~5자) — 공동 소유자 이상 |
| GET / POST | `/api/projects/{pid}/nodes` | 기능 노드 목록 / 생성 (`{parent_id, title}`) |
| PUT | `/api/nodes/{id}` | 부분 수정 (`title/description/status/importance/sort_order/parent_id`) — 순환 이동·타 프로젝트 이동은 400 |
| DELETE | `/api/nodes/{id}` | 삭제 (하위 노드 연쇄 삭제) |
| POST | `/api/projects/{pid}/images` | 이미지 업로드 (원본 바이트 + `Content-Type: image/*`, 5MB 이하) → `{url}` |
| GET | `/api/images/{id}` | 업로드된 이미지 조회 |
| GET | `/api/projects/{pid}/terms` | 용어 목록 (호출 시 본문을 스캔해 자동 생성·삭제) |
| PUT | `/api/terms/{tid}` | 용어 수정 (`{description?, note?, category_id?, sort_order?}`) |
| GET / POST | `/api/projects/{pid}/term-categories` | 카테고리 목록 / 추가 (`{name}`) |
| DELETE | `/api/term-categories/{cid}` | 카테고리 삭제 (용어는 미분류로 남음) |
| GET / POST | `/api/projects/{pid}/versions` | 버전 목록(`node_count`·`item_count`) / PRD 섹션·표·기능명세서 스냅샷 저장 — 편집자 이상 |
| POST | `/api/versions/{vid}/restore` | 해당 버전으로 복원 — 표·행·노드의 id·번호 유지 — 편집자 이상 |
| DELETE | `/api/versions/{vid}` | 버전 삭제 — 편집자 이상 |
| GET | `/api/projects/{pid}/images` | 앨범 목록 (`id, created_at, bytes, used`) |
| POST | `/api/projects/{pid}/images/delete` | 선택 이미지 삭제 (`{ids: [...]}`) → `{deleted, bytes}` |
| GET | `/api/auth/id-available?login_id=...` | 로그인 ID 중복 확인 (`{available}`) |
| POST | `/api/auth/register` | 회원가입 (`{login_id, display_name, password}`·비밀번호 8자 이상) |
| POST | `/api/auth/login` | 로그인 (`{login_id, password}`) |
| POST | `/api/auth/logout` | 로그아웃 (Bearer 토큰) |
| GET / POST | `/oauth/login` | OAuth 승인 화면 — ChatGPT 연결 때 아이디·비밀번호로 로그인하고 승인 (`main.py`) |
| — | `/authorize` · `/token` · `/register` · `/revoke` · `/.well-known/oauth-*` | OAuth 2.1 서버 (`mcp_app.py`, MCP SDK) — DCR · PKCE · 토큰 회전 · discovery |
| GET | `/api/me` | 내 등급·프로젝트 수·이미지 사용량과 한도·프로필 이미지 |
| PUT | `/api/me/display-name` | 내 표시 이름 변경 (`{display_name}`) |
| GET / POST | `/api/me/tokens` | MCP·플러그인 토큰 목록(마스킹) / 발급 (계정당 10개) |
| DELETE | `/api/me/tokens/{id}` | 토큰 폐기 |
| PUT | `/api/me/avatar` | 프로필 이미지 등록/삭제 (`{avatar}` data URL 또는 null) |
| PUT | `/api/me/password` | 내 비밀번호 변경 (`{current, password}`, 새 비밀번호 8자 이상, 새 토큰 반환) |
| GET | `/api/signup-open` | 신규 가입 허용 여부 (공개) |
| GET | `/api/admin/users` | 계정 목록 (등급·상태·프로젝트 수·이미지 사용량·한도) — admin |
| PUT | `/api/admin/users/{uid}/role` | 등급 변경 (`{role}`) — admin |
| PUT | `/api/admin/users/{uid}/login-id` | 로그인 ID 변경(중복 불가) — admin |
| PUT | `/api/admin/users/{uid}/display-name` | 표시 이름 변경 — admin |
| PUT | `/api/admin/users/{uid}/password` | 비밀번호 변경 (8자 이상, 세션·잠금 해제) — admin |
| DELETE | `/api/admin/users/{uid}` | 계정 완전 삭제 (연관 데이터 CASCADE) — admin |
| GET | `/api/admin/users/{uid}/projects` | 그 계정의 프로젝트 목록 — admin |
| DELETE | `/api/admin/projects/{pid}` | 프로젝트 삭제 — admin |
| GET | `/api/admin/signups` | 가입 신청 목록 — admin |
| POST | `/api/admin/signups/{uid}/approve` | 승인 (`{role}`) — admin |
| POST | `/api/admin/signups/{uid}/reject` | 거절(계정 삭제) — admin |
| GET / PUT | `/api/admin/settings` | 가입 허용 여부 조회/변경 (`{signup_open}`) — admin |
| GET | `/api/nodes/{id}/comments` | 노드 코멘트 목록 |
| POST | `/api/nodes/{id}/comments` | 코멘트 작성 (로그인 필요, `Authorization: Bearer <token>`) |
| DELETE | `/api/comments/{id}` | 본인 코멘트 삭제 (로그인 필요) |

## MCP 서버 (배포 서버가 제공)

백엔드가 `/mcp` 에 HTTP MCP 를 함께 제공합니다. ChatGPT 는 **OAuth 2.1(PKCE)**, Claude/Codex 는
**계정별 API 토큰**(`olg_…`)으로 붙습니다. 권한은 REST 와 같은 코드(`access_level`)로 판정하고,
보이는 것은 그 계정이 만든 프로젝트 + 멤버로 참여중인 프로젝트입니다.

### ChatGPT 연결

1. 새 플러그인의 서버 URL 에 `<PUBLIC_URL>/mcp` 입력, 인증은 **OAuth**.
2. 처음 툴을 쓸 때 열리는 화면에서 아이디·비밀번호로 로그인하고 승인.

DCR 로 공개 클라이언트가 등록되고, access 1시간 · refresh 30일(갱신 때 둘 다 회전), DB 에는 해시만 저장.
discovery 는 `/.well-known/oauth-protected-resource/mcp` · `/.well-known/oauth-authorization-server`.

### API 토큰 방식

앱 헤더 메뉴 → **플러그인 설치** → `+ 새 토큰 발급`. 전체 값은 그때 한 번만 보이고, 계정당 10개,
로그아웃해도 유지되며 관리자가 비밀번호를 재설정하면 끊깁니다.

```bash
claude mcp add --transport http olgae-planner https://<호스트>/mcp -H "Authorization: Bearer olg_..."
```

Cursor·Claude Desktop 은 같은 창의 JSON(`{"mcpServers": {"olgae-planner": {"type": "http", "url": …, "headers": …}}}`)을 설정 파일에 붙입니다.

`/mcp` 는 Host 검사로 DNS 리바인딩을 막습니다 — 배포하면 `.env` 의 `MCP_ALLOWED_HOSTS` 에 도메인을 콤마로 추가합니다
(빈 값이면 검사가 꺼집니다).

### 플러그인 (MCP + 작성 규칙 스킬)

`plugin/` 에 Claude Code · Codex 매니페스트와 스킬 `olgae-planner` 가 있습니다. 주소·토큰은 환경변수로 받아
한 플러그인으로 여러 서버를 씁니다.

```bash
export OLGAE_URL=https://<호스트>/mcp
export OLGAE_TOKEN=olg_...
claude plugin marketplace add kdHyeok/olgae-planner
claude plugin install olgae-planner@olgae-planner
```

로컬 경로 ↔ GitHub 소스 전환, `claude mcp add` 와 이름이 겹칠 때, Codex 설정은 [plugin/README.md](plugin/README.md) 에.
스킬 규칙(용어 백틱 · 첨부 URL 확인 · 명세에 있는 것만으로 산출물 · `[[번호]]` 로 근거 · 작업판 갱신)은
[SKILL.md](plugin/skills/olgae-planner/SKILL.md) 에.

### 로컬 테스트

```bash
docker compose up -d --build
docker compose exec -T backend python test_oauth.py  # OAuth 스모크 테스트
SESS=$(curl -s -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" -d '{"login_id":"<아이디>","password":"<비밀번호>"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
TOK=$(curl -s -X POST http://localhost:3000/api/me/tokens \
  -H "Authorization: Bearer $SESS" -H "Content-Type: application/json" -d '{"name":"local"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
claude mcp add --transport http olgae-planner http://localhost:3000/mcp -s local -H "Authorization: Bearer $TOK"
```

`/mcp` 목록에 `Connected` 로 떠도 토큰 검사를 통과한 것은 아니니 `list_projects` 를 한 번 호출해 봅니다.

| 툴 | 설명 |
|---|---|
| `list_projects` | 내 프로젝트 목록 (project_id 확인) |
| `get_spec` | PRD 본문 + 기능 트리 한 번에. 화면과 같은 계층 번호(`1`, `1.1`) 포함 |
| `set_prd` | PRD 본문 전체 덮어쓰기 |
| `create_node` / `update_node` / `delete_node` | 기능 항목 추가 / 부분 수정 / 삭제(하위 포함) |
| `list_terms` / `set_term` | 용어 목록(호출 시 자동 동기화) / 설명·비고·카테고리·순서 수정 |
| `save_version` / `list_versions` / `restore_version` | 스냅샷 저장 / 목록 / 복원 |
| `list_comments` / `add_comment` | 코멘트 조회 / 작성 |
| `list_collections` | 표 목록과 속성 정의(schema) — 어떤 표가 있는지 먼저 확인 |
| `search_items` | 표의 행 검색 (`query` 부분 일치, `collection` 으로 표 지정) |
| `get_item` / `create_item` / `update_item` | 번호로 행 조회 / 추가 / 속성 부분 수정 |

프로젝트 생성·삭제, 공유 링크, 이미지, **표·속성 삭제**는 툴로 열지 않았습니다(웹 UI 에서).

## 프로젝트 구조

```
├── docker-compose.yml
├── CLAUDE.md            # 작업 규칙 (DB 변경 시 docs/ERD.md 갱신 등)
├── docs/
│   ├── ERD.md           # DB 스키마 문서 (관계도 · 컬럼 · 키 · 삭제 규칙)
│   └── PLAN-collections.md  # PRD 구조화 · 커스텀 표 · 작업판 설계와 진행 상태
├── plugin/              # Claude/Codex 플러그인 (MCP 연결 + olgae-planner 스킬)
│   ├── .claude-plugin/plugin.json
│   ├── .codex-plugin/plugin.json
│   ├── .mcp.json
│   └── skills/olgae-planner/SKILL.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py          # FastAPI 전체 (스키마 생성 + 마이그레이션 + API·OAuth 로그인 화면)
│   ├── mcp_app.py       # /mcp HTTP MCP + OAuth 2.1 서버 (main 의 핸들러를 재사용)
│   ├── migrate_prd_tables.py  # 옛 마크다운 PRD 의 표를 컬렉션 행으로 (일회성, 선택)
│   └── test_oauth.py    # DCR·PKCE·MCP·refresh·revoke 스모크 테스트
└── frontend/
    ├── Dockerfile
    ├── nginx.conf       # 정적 서빙 + /api·/mcp 프록시 + 보안 헤더
    ├── logo.png · favicon.png
    └── index.html       # SPA 전체 (빌드 도구 없음)
```

DB 구조는 [`docs/ERD.md`](docs/ERD.md) 에 관계도와 컬럼 설명이 있습니다.

## 주의

데모 용도입니다. 외부에 공개하려면 최소한 아래를 먼저 확인하세요.

- `.env` 의 `POSTGRES_PASSWORD` 를 강한 값으로 (기본값 사용 금지)
- 앞단에 HTTPS 종료(리버스 프록시) — 세션 토큰이 평문으로 흐르지 않게
- 프록시를 더 앞에 둔다면 nginx 의 `X-Real-IP` 가 실제 클라이언트 IP 가 되게 맞출 것
  (아니면 로그인 잠금이 프록시 IP 하나로 뭉쳐 모든 사용자가 함께 잠깁니다)
- 신규 가입은 승인제를 유지하거나 관리자 페이지에서 차단
- `MCP_ALLOWED_HOSTS` 에 배포 도메인 지정 (비우면 Host 검사가 꺼집니다)
- `PUBLIC_URL` 이 실제 외부 HTTPS 주소와 일치하는지 확인 (`.env` 에서 지정, 기본값은 localhost 라 배포 시 반드시 바꾼다)
- 이미지는 URL 을 알면 인증 없이 열립니다(`/api/images/<id>`, id 는 128비트 난수)
- 업로드는 PNG·JPEG·GIF·WebP 만 받고 앞바이트로 검증합니다(SVG 는 스크립트를 품을 수 있어 거부).
  프로필 이미지(data URL)도 base64 이미지 형식만 허용합니다
- nginx 가 `X-Content-Type-Options: nosniff` · `X-Frame-Options: DENY` ·
  `Referrer-Policy: no-referrer` 를 붙입니다. CSP 는 인라인 핸들러가 많아 아직 없습니다
- DB 백업 없음
