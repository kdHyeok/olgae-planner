# 계획: PRD 구조화 · 커스텀 표(컬렉션) · 작업판

> **이 문서의 용도** — PRD 구조화 작업의 **설계 기록**. 계획은 2026-09-06 에 전부 끝났다.
> 결정(D1~D14)·데이터 모델·링크/내보내기 규칙은 지금도 유효하며 코드 주석이 이 문서의 절·항목 번호를 가리킨다.
> 결정을 바꾸면 [결정 사항](#3-결정-사항)에 새 번호로 이유를 적고, 큰 후속 작업은 [진행 상태](#진행-상태)에 한 줄 남긴다.

- 관련 문서: [ERD.md](ERD.md)(현재 DB), [../README.md](../README.md)(기능·API), [../plugin/skills/olgae-planner/SKILL.md](../plugin/skills/olgae-planner/SKILL.md)(본문 규칙)
- 작업 규칙은 [../CLAUDE.md](../CLAUDE.md) 를 따른다 — DB 를 바꾸면 같은 작업 안에서 ERD 를 갱신, 커밋은 요청받을 때만.

---

## 1. 왜 하나

PRD 가 마크다운 한 덩어리라 **기능명세서에서 "어떤 정책·요구를 위해 만든 기능인지" 가리킬 수 없다.**
실측(프로젝트 `플래닛토리`, 2026-09-06):

| 항목 | 개수 | 비고 |
|---|---|---|
| 핵심 정책 POL | 20 | PRD 2장, 마크다운 표 |
| 비기능 요구사항 NFR | 15 | 6장 (처음 17로 적었던 것은 다른 곳의 `NFR-` 언급까지 센 값 — 1.10 에서 정정) |
| 미결정 사항 DEC | 23 | 8장 |
| 검수 시나리오 AT | 41 | 부록 A |
| 기능 노드 | 20 | 기능명세서 |

- PRD 9장에 **정책 추적표**가 손으로 유지되고 있다 — 정책 ↔ 기능 ID(`HOME-03`, `RES-02~05`) ↔ 검수(`AT-03~05`).
- 그런데 그 기능 ID 는 기능명세서 노드 어디에도 없다(노드 설명에 `POL-` 언급 0건). PRD 안에서만 도는 ID 다.
- 화면의 노드 ID `N-0014` 는 `nodes.id`(서비스 전체 일련번호)를 0 채움한 것. 프로젝트 순번을 slug 로 감춘 결정과 어긋난다.

목표: **PRD 의 표 항목·작업·기능 모두에 프로젝트 안 고유 번호를 주고, 서로 `[[번호]]` 로 링크되게 한다.
표는 노션처럼 필요할 때 만들 수 있고, 작업은 칸반으로 관리하며, 플러그인이 작업을 찾아 갱신할 수 있다.**

---

## 2. 기준 상태 (시작 시점)

- 커밋 `ddee60a` (master). 작업 트리 클린.
- 테이블 17개: `api_tokens, comments, images, login_attempts, nodes, oauth_clients, oauth_codes, oauth_requests, oauth_tokens, project_members, projects, sessions, settings, term_categories, terms, users, versions`
- `projects(id, owner_id, name, prd, share_token, slug)` · `nodes(id, parent_id, title, description, status, importance, sort_order, project_id)` · `comments(id, node_id, user_id, content, created_at)`
- 크기: `frontend/index.html` 2,607줄 · `backend/main.py` 1,649줄 · `backend/mcp_app.py` 437줄
- 탭: **PRD** · **기능명세서**. 뷰: 트리 · 디렉토리. 편집 방식: 미리보기 기본, 더블클릭으로 그 자리 편집(폼 입력창 UI 금지 — 사용자가 거부한 방향).

---

## 3. 결정 사항

번호는 바꾸지 않는다. 뒤집으려면 새 번호로 "D-n 을 대체" 라고 적는다.

| # | 결정 | 이유 |
|---|---|---|
| **D1** | 프로젝트마다 **짧은 키**(2~5자 대문자, 예 `PLNT`)를 두고, 기능·표 행·작업이 **하나의 번호 시퀀스**를 공유한다. 표시는 `PLNT-14`. | 표를 자유롭게 만들수록 표별 접두어(`POL-07`) 관리가 마찰이 된다. 해석기가 하나면 된다. 지라·Linear·GitHub 방식. 종류는 칩 색으로 보인다. 기능이 대분류를 옮겨도 번호가 안 바뀐다. |
| **D2** | 번호 발급은 `UPDATE projects SET next_seq = next_seq + 1 RETURNING next_seq`. | 원자적. `max+1` 은 동시 요청에서 겹친다. |
| **D3** | 노드에도 `seq` 를 준다. 화면 `N-0014` → `PLNT-14`. | 링크는 양쪽에 주소가 있어야 양방향이 된다. 정책 옆 "쓰는 기능 N개"와 추적표 자동 생성이 여기에 달려 있다. 노드의 다른 동작(트리·드래그·중요도)은 건드리지 않는다. |
| **D4** | 표는 **`collections`(정의) + `items`(행)** 두 테이블. 속성은 `schema jsonb`, 값은 `props jsonb`. | 사용자가 표와 속성을 만들 수 있어야 한다(노션형). 행은 jsonb 배열이 아니라 **진짜 행** — 순서·개별 삭제·참조 카운트가 필요. |
| **D5** | 속성 타입은 처음엔 `text · md · select · checkbox · relation` 다섯. `list` 타입은 없다. | 숫자·날짜는 필요할 때. list 는 md 불릿이나 select 로 충분. |
| **D6** | **고정**: 프로젝트·멤버·권한·**기능명세서 트리**·코멘트·이미지·용어·버전. **자유(컬렉션)**: PRD 서술 섹션, 정책·NFR·결정·테스트·액터·흐름, **작업**. | 기능 트리는 계층·드래그·MoSCoW·가상 스크롤이 붙어 있어 일반화하면 다 깨진다. 나머지는 프로젝트마다 있을 수도 없을 수도 있다. |
| **D7** | PRD 서술도 컬렉션이다 — `view='document'` 인 `prd` 컬렉션, 행 하나 = 섹션 하나(`title`, `body` md). **기존 `projects.prd` 는 첫 행 "기존 PRD" 의 body 로 옮긴다.** 컬럼은 당장 지우지 않는다. | 별도 테이블이 필요 없다. 데이터 유실 없이 legacy 를 보존한다. |
| **D8** | 작업판은 전용 테이블이 아니라 **builtin 컬렉션 `tasks`** + `board` 보기. | 담당자·기한을 붙일 때 속성 추가로 끝난다. MCP 툴이 컬렉션 공통 하나로 된다. |
| **D9** | 링크는 두 형태, 해석기 하나. `relation` 속성 = seq 배열(조회 가능). md 본문 `[[PLNT-14]]` = 인라인 언급. 역참조는 텍스트 스캔(이미지 `used`·용어와 같은 방식). 느려지면 그때 물질화. | 코드베이스의 "FK 없이 텍스트로 이어지는 관계" 패턴을 따른다. |
| **D10** | 탭은 **PRD · 기능명세서 · 작업** 셋. 정책·NFR 등 다른 컬렉션은 PRD 탭 안 섹션으로 놓인다(순서 조정 가능). | 작업판은 매일 여는 화면. 다른 컬렉션은 문서 맥락에 있어야 한다. 탭을 더 늘리면 "이건 어디?" 판단이 매번 생긴다. |
| **D11** | 프로젝트 생성 시 `prd`(서술 섹션)와 `tasks` 만 심는다. 정책·NFR·결정·테스트·액터·흐름은 **"+ 표 추가 → 템플릿"** 으로 원할 때. | 안 쓰는 프로젝트에 빈 표가 없다. |
| **D12** | 기존 PRD 의 POL 20·NFR 17·DEC 23·AT 41 은 **일회성 스크립트로 컬렉션 행으로 옮긴다.** | 안 옮기면 링크 대상이 없어 2단계가 빈 껍데기다. 표 형식이 규칙적이다(§7). |
| **D13** | 내보내기는 계속 지원한다. **가져오기(md → DB)는 목표에서 뺀다.** | 사용자가 손으로 고친 md 를 구조로 되돌리는 건 다른 크기의 문제. |
| **D14** | `[[ID]]` 문법. `` `용어` `` 와 겹치지 않고 `#` 처럼 제목과 충돌하지 않는다. | 정규식 한 줄. 위키 관례. |

---

## 4. 데이터 모델

`init_db()` 는 기동마다 실행되므로 전부 멱등으로 쓴다.

```sql
ALTER TABLE projects ADD COLUMN IF NOT EXISTS key text;        -- 'PLNT'. 전역 UNIQUE 는 두지 않는다(다른 소유자가 같은 키를 쓸 수 있음)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS next_seq int NOT NULL DEFAULT 0;
ALTER TABLE nodes    ADD COLUMN IF NOT EXISTS seq int;         -- 백필로 채운다. 고유성은 next_seq 발급으로 보장(items 와 번호 공유라 DB UNIQUE 로 못 건다)
CREATE INDEX IF NOT EXISTS nodes_project_seq_idx ON nodes (project_id, seq);

CREATE TABLE IF NOT EXISTS collections (
    id          serial PRIMARY KEY,
    project_id  int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key         text NOT NULL,                 -- 'prd' · 'tasks' · 'policies' … 내보내기·MCP 에서 쓰는 안정 키
    title       text NOT NULL,                 -- 화면 이름. 바꿔도 key 는 유지
    view        text NOT NULL DEFAULT 'table', -- 'document' | 'table' | 'board'
    board_by    text,                          -- board 일 때 그룹 기준 select 속성 key
    schema      jsonb NOT NULL DEFAULT '[]',   -- [{key, label, type, options?, target?}]
    sort_order  int NOT NULL DEFAULT 0,
    builtin     bool NOT NULL DEFAULT false,   -- 템플릿에서 왔는지. 삭제 대신 숨김 권장
    UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS items (
    id            serial PRIMARY KEY,
    project_id    int NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    collection_id int NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    seq           int NOT NULL,                -- PLNT-<seq>. 노드와 번호 공유
    props         jsonb NOT NULL DEFAULT '{}', -- {속성key: 값}
    sort_order    int NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    created_by    int REFERENCES users(id) ON DELETE SET NULL,
    UNIQUE (project_id, seq)
);
CREATE INDEX IF NOT EXISTS items_collection_idx ON items (collection_id, sort_order);

ALTER TABLE comments ADD COLUMN IF NOT EXISTS item_id int REFERENCES items(id) ON DELETE CASCADE;
-- node_id 를 NULL 허용으로 바꾸고(조건부 ALTER), CHECK (node_id IS NOT NULL OR item_id IS NOT NULL) 를 이름 붙여 조건부 추가

-- 2단계
CREATE TABLE IF NOT EXISTS item_events (
    id       serial PRIMARY KEY,
    item_id  int NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id  int REFERENCES users(id) ON DELETE SET NULL,
    at       timestamptz NOT NULL DEFAULT now(),
    prop     text NOT NULL,                    -- 바뀐 속성 key
    before   jsonb,
    after    jsonb
);
```

### 속성 정의 (`schema` 원소)

```json
{ "key": "status", "label": "상태", "type": "select", "options": ["할일", "진행중", "완료"] }
{ "key": "parent", "label": "상위", "type": "relation", "target": "tasks" }
{ "key": "body",   "label": "내용", "type": "md" }
```

`target` 을 생략한 relation 은 아무것(노드 포함)을 가리킬 수 있다.
`props` 값 형태: `text`·`md` → 문자열, `select` → 문자열(옵션 중 하나), `checkbox` → bool, `relation` → `[seq, …]`.
**검증은 API 에서** 한다(jsonb 는 DB 제약이 없다). 스키마에 없는 key 는 버리고, select 는 옵션 밖 값을 거부한다.

### 백필 (init_db 끝에서, 파이썬)

1. `projects.key` 가 NULL 인 행: `P` + 프로젝트 id 를 36진수 대문자(예 `P1`, `PA`). 사용자가 나중에 바꿀 수 있다. 바꾸면 화면 표기만 바뀌고 링크는 seq 기준이라 안 깨진다.
2. `nodes.seq` 가 NULL 인 행: 프로젝트별 `id` 순으로 1부터. 끝나면 `next_seq` 를 그 최대값으로.
3. 컬렉션이 없는 프로젝트: `prd`·`tasks` 시드. `prd` 의 첫 행 body = `projects.prd`(비어 있지 않으면), title = "기존 PRD".

---

## 5. 기본 템플릿

### 항상 심는 것 (D11)

**`prd` — `view='document'`** · schema `[title:text, body:md]`
행(섹션) 기본값, 순서대로: `기존 PRD`(legacy, 있을 때만) · `한 줄 정의` · `제품 목표` · `배경` · `사용자 문제` · `해결 방안` · `차별점` · `타겟 사용자` · `사용자 시나리오` · `접근 기기`

**`tasks` — `view='board'`, `board_by='status'`**

| key | label | type | options / target |
|---|---|---|---|
| title | 제목 | text | |
| status | 상태 | select | 할일 · 진행중 · 완료 |
| kind | 종류 | select | 에픽 · 작업 · 이슈 |
| parent | 상위 | relation | tasks |
| related | 관련 | relation | (아무것) |
| body | 내용 | md | |

에픽 카드에는 하위(`parent` 가 나를 가리키는 행) 완료 수 `3/7` 을 계산해 표시한다. 깊이는 고정하지 않는다.

### "+ 표 추가 → 템플릿" 목록 (D11 · UI 는 3단계, 시드 함수는 1단계에서 만든다)

| key | title | view | schema |
|---|---|---|---|
| policies | 핵심 정책 | table | policy:md |
| nfr | 비기능 요구사항 | table | area:text, requirement:md |
| decisions | 미결정 사항 | board(status) | topic:text, status:select[미결정·결정], default:md, decision:md |
| tests | 테스트 시나리오 | table | scenario:md, expected:md, related:relation |
| actors | 객체(액터) | table | actor:text, role:md |
| flows | 전체 흐름 | table | acting:text, scenario:md |
| target_users | 타겟 사용자 | table | user:text, purpose:md |
| devices | 접근 기기 | table | value:text |
| domains | 도메인 | table | value:text |
| (빈 표) | 사용자 지정 | table | title:text |

`tests` 는 논의에서 "기능에 붙어야 한다"고 봤지만, **1단계에서는 컬렉션으로 두고 `related` relation 으로 기능을 가리킨다.** 노드 하위 속성으로 옮기는 건 실제 사용을 보고 결정(§열린 질문).

---

## 6. ID · 링크 규칙

- 표기: `<projects.key>-<seq>` → `PLNT-14`. 대소문자 무관하게 해석.
- 해석: `seq` 로 `nodes` 와 `items` 를 둘 다 조회. 결과 `{kind: 'node'|'item', collection_key?, title, url}`.
- URL: 노드 → `/project/<slug>?tab=spec&node=<seq>` · 컬렉션 행 → `/project/<slug>?tab=prd&item=<seq>` · 작업 → `?tab=tasks&item=<seq>`.
- 인라인: md 안 `[[PLNT-14]]`. 렌더는 칩(종류별 색) — 호버 미리보기, 클릭 이동. **해석 실패는 빗금 칩**(조용히 사라지지 않게).
- 구조: `relation` 속성 = `[14, 37]`(seq 배열). 화면은 칩 목록 + 추가(검색) + 제거.
- 역참조("이걸 가리키는 것"): `nodes.description` · `items.props` 의 md 값 · relation 배열을 스캔. 정책 행 옆 "쓰는 기능 N개", 노드 상세 상단 "관련 PRD" 칩 줄. **삭제 시 참조 수를 보여주고 두 번 클릭 확인.**
- 정책 추적표(PRD 9장)는 저장하지 않고 **이 역참조로 계산해 보여주는 뷰**다.

---

## 7. 마이그레이션: 기존 PRD 표 → 컬렉션 (D12)

일회성 스크립트 `backend/migrate_prd_tables.py`(저장소에 두되 `init_db` 에서 부르지 않는다. `docker compose exec -T backend python migrate_prd_tables.py <slug> [--apply]`).

소스 형식(실측). 각 표는 `| ID | … |` 헤더, `|---|` 구분선, 그 다음 행들:

| 섹션 제목 | 헤더 | → 컬렉션 · 속성 |
|---|---|---|
| `## 2. 핵심 정책 (POL)` | `\| ID \| 정책 \|` | policies · policy |
| `## 6. 비기능 요구사항 (NFR)` | `\| ID \| 분야 \| 요구사항 \|` | nfr · area, requirement |
| `## 8. 미결정 사항 (DEC)` | `\| ID \| 항목 \| 현재 기본안 \|` | decisions · topic, default (status=미결정) |
| `## 부록 A. 통합 검수 시나리오` | `\| ID \| 시나리오 \| 기대 결과 \|` | tests · scenario, expected |

규칙:
- 원래 ID(`POL-07`)는 **`props.legacy_id` 에 보존**하고 새 seq 를 발급한다. 화면엔 `PLNT-nn` 옆에 작게 `POL-07` 을 보여줄 수 있다(선택).
- 옮긴 표 블록은 `prd` 첫 행 body 에서 **제거하지 않는다**(원본 보존). 대신 그 행 title 을 "기존 PRD (표는 컬렉션으로 옮겨짐)" 로 바꾼다.
- **DRY RUN 이 기본**(`--apply` 없으면 몇 행을 어디로 옮길지만 출력). 실행 전 버전 저장.
- 셀 안 `` `용어` `` 는 그대로 둔다 — `sync_terms` 가 items 를 스캔하면 자동으로 사전에 잡힌다.

---

## 8. 기존 지점 영향

| 지점 | 지금 | 바뀌는 것 | 왜 |
|---|---|---|---|
| `nodes` | 전역 일련번호 | `seq` 열, 화면 `PLNT-14` | 정책→기능 방향 링크·추적표 자동화 |
| `projects` | 이름·slug | `key`, `next_seq` | 번호 앞부분·발급 |
| `versions` | `data`(노드) + `prd`(md) | `collections`·`items` 도 스냅샷. **복원 시 item id·seq 보존**(노드 복원이 id 를 지키는 것과 같은 UPSERT) | 번호가 바뀌면 링크가 다른 걸 가리킨다 |
| `sync_terms` | `projects.prd` + 노드 설명 | `items.props` 의 md 값도 | 정책 본문의 용어가 사전에 잡히게 |
| 이미지 `used` | prd + 노드 설명 검색 | items md 값도 | 정책에 붙인 이미지가 "미사용"으로 뜨지 않게 |
| `comments` | node_id | `item_id` 추가, 둘 중 하나 | 작업 카드에 코멘트 |
| 마크다운 내보내기 | prd + 트리 | 컬렉션 규칙(§9). `[[…]]` → 앵커 링크 | |
| MCP `get_spec`·`set_prd` | prd 문자열 | `prd` 는 legacy 로 유지, 컬렉션 공통 툴 5개 추가 | |
| `SKILL.md` | 본문 규칙 | `[[ID]]` 문법, 작업 처리 규칙 | CLAUDE.md 규칙 |
| `ERD.md`·`README.md` | — | 테이블 2~3개, 문자열 참조 절에 `[[ID]]`·relation | CLAUDE.md 규칙 |
| 라우팅 | `?tab=prd\|spec&view=…` | `tab=tasks`, `item=<seq>`, `node=<seq>` | 링크 클릭 이동 |

---

## 9. 마크다운 내보내기 규칙

한 파일, 순서: PRD 컬렉션들 → 작업 → 기능명세서(기존 그대로).

- `document` 컬렉션(prd): 행마다 `## {title}` + body.
- 그 밖의 컬렉션: **md 속성이 하나라도 있으면** 행마다 `### {KEY}-{seq} · {첫 text 속성}` + `- 라벨: 값` 줄들 + md 본문. **전부 스칼라면** 마크다운 표.
- 작업: 상태별 `### 할일 / 진행중 / 완료` 로 묶고 위 규칙.
- `[[PLNT-14]]` 와 relation → `[PLNT-14 제목](#plnt-14)`. 각 행·노드 제목에 `<a id="plnt-14"></a>` 앵커.
- 가져오기는 하지 않는다(D13).

---

## 10. 작업 계획

전부 완료. 항목 번호(`1.5` · `2.6` …)는 코드 주석이 참조하므로 그대로 둔다.

### 1단계 — 그릇 (데이터 모양이 굳는다. 가장 신중하게)

- [x] **1.1 스키마·백필** — `backend/main.py` `init_db()`: §4 DDL, §4 백필 3개. `docs/ERD.md` 갱신(관계도·삭제 규칙·상세 표·인덱스·문자열 참조).
- [x] **1.2 번호 발급·해석 API** — `alloc_seq(cur, pid)` 헬퍼, `GET /api/projects/{slug}/resolve/{seq}` (노드·행 공통 해석, §6 형태), `PUT /api/projects/{slug}/key` (공동 소유자 이상). `create_node` 가 seq 부여. `create_project` 가 `project_key()` 로 키 부여 + `seed_collections()`.
- [x] **1.3 컬렉션·행 API** — `GET/POST /api/projects/{slug}/collections`, `PUT/DELETE /api/collections/{cid}`(스키마·제목·보기·board_by·순서), `GET/POST /api/collections/{cid}/items`(`after` 로 위치 지정), `PUT/DELETE /api/items/{iid}`, `POST /api/items/{iid}/move`(`{dir:±1}`, 노드 ▲▼ 와 같은 방식). `validate_schema`·`validate_props` 가 §4 규칙 검증. 권한: 읽기 `check_access`, 쓰기 `check_write`. 요청 본문은 pydantic 모델 대신 `dict`(속성 이름 `schema` 가 pydantic 예약어라).
- [x] **1.4 노드 화면 ID** — `detailBody()` 의 `N-0014` → `${project.key}-${n.seq}` (title 에 `[[P1-14]]` 링크 힌트). `GET /api/projects` 와 `/api/shared` 응답에 `key` 포함(1.2 에서).
- [x] **1.5 PRD 탭 = 컬렉션 렌더** — `document` 보기(섹션 카드, 더블클릭 편집, 순서 ▲▼, 섹션 추가/삭제) · `table` 보기(속성 타입별 인라인 편집: text 입력, md 미리보기/더블클릭, select 드롭다운, checkbox; relation 은 1단계에서 `P1-14, 37` 식 번호 입력) · 좌측 목차(컬렉션 순서). 읽기 전용(reader/commenter)이면 편집 진입 차단(기존 `needEdit()` 패턴). 옛 `renderPrd`·`prdClickEdit`·`savePrd` 는 삭제. `prdContent` 는 내보내기(1.7)까지만 남김. board 보기는 2.5 까지 표로 보인다.
- [x] **1.6 작업 탭 (table 보기까지)** — 탭 추가, 라우팅 `tab=tasks`(`viewParams`/`readViewParams`), `renderTasks(c)` 가 `tasks` 컬렉션을 `collectionHTML` 로 표시(board 도 지금은 표). board 는 2단계.
- [x] **1.7 내보내기** — `exportMarkdown()` 을 §9 규칙으로 재작성(`resolveLocal`·`itemTitle` 헬퍼). document 컬렉션은 섹션이 `##`, 그 외는 md 속성 있으면 `### P1-14 · 제목` 블록·없으면 표, 작업은 상태별 `###` 묶음, `[[P1-14]]`·relation → `[P1-14 제목](#p1-14)`, 행·노드마다 `<a id="p1-14"></a>`, 노드에 `- ID: P1-14`. `openProjectData()` 의 legacy `/prd` 요청 제거(`prdContent` 미사용).
- [x] **1.8 버전 스냅샷·복원** — `versions.collections jsonb` 컬럼 추가. `save_version` 이 컬렉션+행(id·seq·props·sort_order)을 담고 `item_count` 반환, `list_versions` 도 `item_count`. `restore_version` 은 스냅샷에 없는 컬렉션·행을 지운 뒤 UPSERT 로 id·seq 보존, 노드 UPSERT 에 `seq` 포함(옛 스냅샷의 seq 없는 노드는 `alloc_seq` 로 채움), 끝에 `next_seq` 를 최대 번호 이상으로. `NODE_FIELDS` 에 `seq`. 프런트 버전 목록에 "표 행 N개". `versions.prd` 는 legacy 로 유지.
- [x] **1.9 부수 스캔 확장** — `sync_terms` 가 컬렉션 행의 md 속성 값을 본문으로 훑고, `list_images` 의 `used` 가 `items.props::text` 도 검색.
- [x] **1.10 기존 PRD 표 이전** — `backend/migrate_prd_tables.py` (§7). 헤더 첫 셀 `ID` 인 표만 보고 행 ID 접두어로 대상을 정한다. DRY RUN 기본, `--apply`, `--undo`. 같은 표에 `legacy_id` 행이 있으면 건너뛴다(멱등).
- [x] **1.11 문서** — `README.md`(기능 블록·주소 규칙·내보내기·버전·API 표 8행·마이그레이션 안내), `ERD.md`(`versions.collections`, `data` 에 `seq`, 복원 규칙). `backend/Dockerfile` 에 `migrate_prd_tables.py` COPY.

### 2단계 — 연결과 판

- [x] **2.1 `[[ID]]` 렌더** — `inline()` 에 `[[KEY-n]]` → 칩(`refChip`). 해석은 `seqMap`(노드 + 모든 컬렉션 행)을 클라이언트에서 lazy 하게 만들고 `setNodes`·`loadCollections`·`reloadItems` 에서 무효화. **번호만 보고 찾으므로 앞의 키가 달라도 해석**. 기능=파란 칩 / 표 행=초록 칩 / 못 찾으면 빗금 칩(클릭 불가). 클릭하면 `gotoSeq()` 가 탭까지 바꿔 이동하고 행은 노란 플래시. 미리보기는 `title` 속성(종류 · 제목)으로 — 호버 카드는 만들지 않았다. relation 셀도 같은 칩을 쓴다.
- [x] **2.2 relation 편집기** — 셀의 `＋` 버튼 → 모달 피커(`openRelPicker`). 현재 연결은 칩 + `✕` 로 해제, 아래 검색창(번호·제목·라벨)으로 후보를 걸러 클릭하면 연결. `target` 있으면 그 표만, 없으면 기능 + 모든 표 행. 후보는 60개까지.
- [x] **2.3 역참조** — **서버 엔드포인트 대신 클라이언트에서 계산**(`backrefs(seq)`) — 프로젝트의 노드·행이 이미 전부 메모리에 있어 왕복이 불필요하다. 노드 설명·행의 md 값의 `[[…-seq]]` 와 relation 배열을 함께 훑는다. 노드 상세 "이 기능을 가리키는 항목" 칩 줄, 문서 섹션 아래 같은 줄, 표 행 번호 아래 "참조 N" 배지(누르면 목록 모달), 삭제 버튼에 `✕N` + 참조 수 툴팁.
  _데이터가 커지면 서버로 옮긴다(코드에 `ponytail:` 주석). 2026-09-06 확인: tests 행이 `[[P1-1]]` 을 relation 으로 가리키자 `backrefs(1)` 에 잡히고 노드 상세에 "이 기능을 가리키는 항목 1 P1-95 …" 표시._
- [x] **2.4 추적표 뷰** — 표 카드 헤더의 `추적표` 토글(`traceOn` Set). 행마다 번호·내용·**가리키는 항목** 칩. 저장하지 않고 그때그때 계산.
- [x] **2.5 board 보기** — `boardHTML`: `board_by` select 옵션이 열, 값 없는 카드는 "미지정" 열(비면 숨김). 카드 드래그로 상태 변경(`boardDragStart`/`boardOver`/`boardDrop`), 열마다 `+ 추가`(그 열의 값이 preset), 에픽 카드에 `하위 1/2`(`childProgress`, `parent` relation 이 자기 표를 가리키는 행을 셈). `decisions` 도 board 로 뜬다. 카드 클릭 → 행 상세 모달.
- [x] **2.6 `item_events`** — `item_events` 테이블. `update_item` 이 **값이 실제로 달라진 속성만** 기록. `GET /api/items/{iid}/events`(최근 100). 행 상세 모달의 "이력" 탭.
- [x] **2.7 코멘트 확장** — `GET/POST /api/items/{iid}/comments`(권한은 그 행이 속한 프로젝트 기준, 쓰기는 `check_comment`). 행 상세 모달의 "코멘트" 탭. 삭제는 기존 `/api/comments/{id}` 재사용.
- [x] **2.8 라우팅** — `?item=<seq>` / `?node=<seq>` 로 열면 그 항목으로 이동(탭 전환 + 스크롤 + 강조). 없는 번호는 토스트.
  강조는 DOM 에 class 를 얹으면 다음 렌더에 지워져서 **상태(`flashSeq`)로 관리**하도록 바꿨다.
- [x] **2.9 문서** — ERD(`item_events` 표·관계도·삭제 규칙·인덱스, 테이블 20개), README(링크·칸반 기능 블록, API 2행). 오래된 README 서술 3곳 정리 — 맨 위 "PRD 탭: 마크다운 문서 보기/저장", 라우팅 블록의 어긋난 줄 순서, "공유 링크로 누구나 열람·편집 가능"(읽기 전용 정책과 모순).

### 3단계 — 자유도

- [x] **3.1 스키마 편집 UI** — 표 헤더의 `설정` → 모달. 이름 · 보기(문서/표/칸반) · 칸반 열 기준 · 속성 추가/이름/타입/옵션(select)/대상 표(relation)/순서 ▲▼/삭제. 속성 key 는 라벨에서 자동 생성하고 이후 불변(이름만 바뀜). `prd`·`tasks` 는 표 삭제 버튼 대신 안내.
- [x] **3.2 "+ 표 추가"** — 좌측 목차 맨 아래 링크 → 모달. 템플릿 9개(이미 있으면 흐리게 "이미 있음") + **빈 표**(이름만 받고 바로 설정 모달을 연다).
- [x] **3.3 MCP 공통 툴** — `list_collections` · `search_items(query, collection?)` · `get_item(seq)` · `create_item(collection, props)` · `update_item(seq, props)`. 기존 13개 유지(총 18개). 서버 instructions 에 작업 처리 절차 추가.
- [x] **3.4 SKILL.md** — 데이터 구조를 3가지(트리·표·작업)로 다시 씀. `[[번호]]` 링크와 relation, **"정책·요구사항을 근거로 기능을 고치면 `[[번호]]` 로 근거를 남긴다"**, 작업 지시 처리 5단계, 안전 규칙(스키마 key 확인·표/속성 삭제는 화면에서), 하지 말 것 3줄 추가. frontmatter description 갱신.
- [x] **3.5 프로젝트 키 편집 UI** — 프로젝트 목록의 `키 ○○` 버튼 → 모달. 소문자 입력도 대문자로 정규화.
- [x] **3.6 문서** — README(표 설정·표 추가·키 변경 기능, MCP 툴 표에 5개 + 작업 처리 설명, API 표에 키 변경).

### 각 단계 끝의 공통 확인

- `docker compose up -d --build backend frontend` 후 브라우저 실사용 확인(CLAUDE.md).
- `docs/ERD.md` 와 `\dt` · `\d+` 대조.
- 검증용 데이터(행·작업·프로젝트) 원복. **실제 프로젝트에서 파괴적 동작 시험 금지.**
- 커밋·푸시는 사용자가 요청할 때만.

---

## 진행 상태

| 날짜 | 단계 | 내용 |
|---|---|---|
| 2026-09-06 | — | 결정 D1~D14 확정. 이 문서 작성. 구현 시작 전. |
| 2026-09-06 | 1.1 · 1.2 | 스키마·백필·템플릿 헬퍼(`COLLECTION_TEMPLATES`, `seed_collections`, `alloc_seq`, `project_key`) · `/resolve/{seq}` · `PUT /key` · 응답 `key`. ERD 갱신. 실제 DB 로 검증. 미커밋. |
| 2026-09-06 | 1.3 · 1.4 · 1.5 | 컬렉션·행 API 11개(`validate_schema`/`validate_props`) · 노드 상세 `P1-14` · PRD 탭을 컬렉션 문서/표 렌더로 교체(`renderCollections`, `editItemProp` 등). API·브라우저·읽기 전용 모두 검증. 미커밋. |
| 2026-09-06 | 1.6 ~ 1.10 | 작업 탭(표) · 내보내기 §9 · 버전 스냅샷/복원(컬렉션·행·노드 seq) · 용어/이미지 스캔 확장 · `migrate_prd_tables.py` 로 99행 이전(POL 20·NFR 15·DEC 23·AT 41). 전부 브라우저·API 검증. 미커밋. |
| 2026-09-06 | 1.11 | README·ERD 갱신, Dockerfile COPY. **1단계 완료.** 미커밋 — 사용자에게 커밋 여부 확인 필요. |
| 2026-09-06 | 2.1 ~ 2.9 | 링크 칩·relation 편집기·역참조·추적표·칸반·이력·행 코멘트·`?item=` 라우팅·문서. **2단계 완료.** 미커밋. |
| 2026-09-06 | 3.1 ~ 3.6 | 스키마 편집 UI · 표 추가 · MCP 공통 툴 5개 · SKILL.md · 프로젝트 키 편집 · 문서. **3단계 완료 = 이 계획 전체 완료.** |
| 2026-09-07 | 후속 | 이력: 정규화 비교 · 10분 안 연속 편집 합침 · 순변화 없으면 삭제 · 개별 삭제 API. 행/섹션 추가 버튼을 표 아래로, 추가 뒤 자동 스크롤 제거. DB: `pg_trgm` + `items_props_trgm_idx`, 군더더기 `(project_id)` 인덱스 제거, MCP `search_items`·`get_item` 을 SQL 한 번으로(전체 적재 → 인덱스 조회). |

**다음 할 일**: 없음. 이 계획은 끝났다. 새 작업은 새 계획 문서로 시작한다.

### 남겨 둔 것 (필요해지면)

- `tests` 를 노드 하위 속성으로 옮길지 — 실제로 써 보고 판단(§5·열린 질문).
- 역참조를 서버에서 계산하기 — 지금은 프로젝트 전체가 메모리에 있어 클라이언트에서 센다. 데이터가 커지면 옮긴다.
- 컬렉션 순서 바꾸기 UI — API(`PUT /api/collections/{cid} {sort_order}`)는 있고 화면은 없다.
- `builtin` 표 숨김/복원 — 계획에는 있었지만 삭제로 충분해 만들지 않았다.
- md 가져오기 · 컬렉션 간 조인/수식 · 저장된 필터 뷰 · 알림 (원래 범위 밖, D13).

### 2단계에서 배운 것 (다음 세션 참고)

- **전체 리렌더 앱에서 DOM 에 직접 얹은 class 는 다음 렌더에 사라진다.** 강조 같은 일시 상태도 `flashSeq` 처럼 상태로 두고 마크업에서 반영해야 한다.
- **첫 렌더의 `syncUrl()` 이 주소의 일회성 파라미터(`?item=`)를 지운다.** 그런 값은 스크립트 로드 시점에 잡아 두어야 한다.
- **HTML 속성 안에 `JSON.stringify()` 를 넣지 말 것** — 큰따옴표가 속성을 깨뜨린다. `dataset` 을 경유한다.
- 브라우저 검증 시 도구 호출 지연이 수십 초라 **1~2초짜리 애니메이션은 관찰할 수 없다.** 탭 전환·선택처럼 남는 상태로 확인한다.

---

## 열린 질문 (결정 필요 시 사용자에게)

- `tests` 를 컬렉션으로 둘지 노드 하위 속성으로 옮길지 — 1단계 사용 후 판단(§5).
- `매칭 업무 규칙`(PRD 4장)과 `핵심 정책`(2장)을 합칠지 — 사용자 답 대기. 합치면 `policies` 에 `area:text` 속성 추가로 해결.
- `projects.key` 를 바꾼 뒤 옛 표기(`PLNT-14`)가 남은 외부 문서 — seq 기준이라 서비스 안 링크는 안 깨지지만, 내보낸 md 텍스트는 낡는다. 안내만 한다.

## 하지 않는 것

- md 가져오기(D13) · 컬렉션 간 조인/수식 · 저장된 필터 뷰 · 알림. 필요해지면 새 계획으로.

---

## 이어서 손댈 때

결정을 뒤집으면 §3 에 새 번호로, DB 를 바꾸면 같은 작업에서 [ERD.md](ERD.md) 갱신(CLAUDE.md), 큰 후속은 진행 상태에 한 줄.
