# DB 스키마 (ERD)

PRD & 기능명세서 서비스의 PostgreSQL 스키마 문서입니다.
스키마는 별도 마이그레이션 도구 없이 [`backend/main.py`](../backend/main.py)의 `init_db()`가
기동 시 `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 로 맞춥니다.
**DB 구조를 바꾸면 이 문서도 함께 고칩니다** (규칙은 [`CLAUDE.md`](../CLAUDE.md) 참고).

- 테이블 17개
- 모든 콘텐츠(기능 트리·PRD·이미지·용어·버전)는 **프로젝트(`projects`) 단위**로 소속됩니다.

## 관계도

```mermaid
erDiagram
    users ||--o{ sessions : "user_id · 로그인 세션"
    users ||--o{ oauth_codes : "user_id · 승인한 사용자"
    users ||--o{ oauth_tokens : "user_id · 연결 계정"
    users |o--o{ projects : "owner_id · 소유자"
    users ||--o{ comments : "user_id · 작성자"
    users |o--o{ versions : "user_id · 저장한 사람"
    oauth_clients ||--o{ oauth_requests : "client_id · 승인 요청"
    oauth_clients ||--o{ oauth_codes : "client_id · 인증 코드"
    oauth_clients ||--o{ oauth_tokens : "client_id · 발급 토큰"

    projects ||--o{ nodes : "project_id"
    projects ||--o{ versions : "project_id"
    projects ||--o{ term_categories : "project_id"
    projects ||--o{ terms : "project_id"
    projects ||--o{ images : "project_id"

    nodes |o--o{ nodes : "parent_id · 상위 항목"
    nodes ||--o{ comments : "node_id"
    term_categories |o--o{ terms : "category_id · SET NULL"

    users {
        serial id PK "사용자 ID"
        text username UK "이전 버전 호환용 로그인 ID"
        text login_id UK "로그인 ID(고유)"
        text display_name "표시 이름"
        text password "비밀번호 해시(salt$pbkdf2)"
        text role "등급 admin·pro·member·guest"
        text status "상태 active·pending(가입 승인 대기)"
        timestamptz created_at "가입 신청 시각"
        text avatar "프로필 이미지(data URL)"
    }
    project_members {
        int project_id PK_FK "프로젝트"
        int user_id PK_FK "참여자"
        text role "권한 editor·coowner"
        text status "상태 pending·active"
        timestamptz created_at "요청 시각"
    }
    api_tokens {
        text token PK "MCP·플러그인 토큰 (olg_…)"
        serial id UK "목록·삭제용 번호"
        int user_id FK "소유 계정"
        text name "토큰 이름"
        timestamptz created_at "발급 시각"
        timestamptz last_used_at "마지막 사용 시각"
    }
    oauth_clients {
        text client_id PK "동적 등록 클라이언트 ID"
        jsonb client_info "DCR 클라이언트 메타데이터"
        timestamptz created_at "등록 시각"
    }
    oauth_requests {
        text request_hash PK "승인 요청 토큰 해시"
        text client_id FK "OAuth 클라이언트"
        text state "클라이언트 상태값"
        jsonb scopes "요청 scope"
        text code_challenge "PKCE S256 challenge"
        text redirect_uri "허용된 callback"
        boolean redirect_uri_provided_explicitly "callback 명시 여부"
        text resource "MCP audience"
        timestamptz expires_at "만료 시각"
    }
    oauth_codes {
        text code_hash PK "인증 코드 해시"
        text client_id FK "OAuth 클라이언트"
        int user_id FK "승인 사용자"
        jsonb scopes "승인 scope"
        text code_challenge "PKCE S256 challenge"
        text redirect_uri "callback"
        boolean redirect_uri_provided_explicitly "callback 명시 여부"
        text resource "MCP audience"
        timestamptz expires_at "만료 시각"
    }
    oauth_tokens {
        text access_token_hash PK "access token 해시"
        text refresh_token_hash UK "refresh token 해시"
        text client_id FK "OAuth 클라이언트"
        int user_id FK "연결 사용자"
        jsonb scopes "발급 scope"
        text resource "MCP audience"
        timestamptz access_expires_at "access 만료"
        timestamptz refresh_expires_at "refresh 만료"
        timestamptz created_at "발급 시각"
        timestamptz last_used_at "마지막 사용 시각"
    }
    settings {
        text key PK "설정 키 (signup_open)"
        text value "설정 값 (1·0)"
    }
    login_attempts {
        text key PK "잠금 키 u:이름@IP 또는 ip:IP"
        int fails "연속 실패 횟수"
        int locks "잠긴 횟수(잠금 시간 단계)"
        timestamptz locked_until "잠금 해제 시각"
        timestamptz last_fail "마지막 실패 시각"
    }
    sessions {
        text token PK "세션 토큰"
        int user_id FK "사용자"
        timestamptz created_at "발급 시각"
    }
    projects {
        serial id PK "프로젝트 ID(내부용)"
        text slug UK "주소·API 에 쓰는 랜덤 키"
        int owner_id FK "소유자(사용자)"
        text name "프로젝트 이름"
        text prd "PRD 본문(마크다운)"
        text share_token "공유 링크 토큰(없으면 NULL)"
    }
    nodes {
        serial id PK "기능 항목 ID"
        int project_id FK "소속 프로젝트"
        int parent_id FK "상위 항목(대분류면 NULL)"
        text title "제목"
        text description "설명(마크다운)"
        text status "진행 상태"
        int importance "중요도 1~4 (MoSCoW)"
        int sort_order "형제 간 순서"
    }
    comments {
        serial id PK "코멘트 ID"
        int node_id FK "대상 기능 항목"
        int user_id FK "작성자"
        text content "내용"
        timestamptz created_at "작성 시각"
    }
    versions {
        serial id PK "버전 ID"
        int project_id FK "소속 프로젝트"
        int user_id FK "저장한 사용자(탈퇴 시 NULL)"
        text username "저장 당시 사용자 이름"
        timestamptz created_at "저장 시각"
        jsonb data "기능 트리 스냅샷"
        text prd "그 시점의 PRD 본문"
    }
    term_categories {
        serial id PK "카테고리 ID"
        int project_id FK "소속 프로젝트"
        text name "카테고리 이름(프로젝트 안 고유)"
    }
    terms {
        serial id PK "용어 ID"
        int project_id FK "소속 프로젝트"
        text term "용어(프로젝트 안 고유)"
        text description "설명(마크다운)"
        text note "비고(마크다운)"
        int sort_order "표시 순서"
        int category_id FK "카테고리(없으면 NULL)"
    }
    images {
        text id PK "이미지 ID(난수 토큰)"
        int project_id FK "소속 프로젝트"
        text mime "MIME 타입"
        bytea data "이미지 바이너리"
        timestamptz created_at "업로드 시각"
    }
```

> 표기: `||--o{` = 1 : 0..N, `|o--o{` = 0..1 : 0..N.
> 선 위 글자는 자식 쪽의 FK 컬럼입니다.

## 삭제 규칙 (ON DELETE)

| 부모를 지우면 | 자식은 |
|---|---|
| `users` → `sessions`, `oauth_codes`, `oauth_tokens`, `projects`, `comments` | **함께 삭제** (CASCADE) |
| `oauth_clients` → `oauth_requests`, `oauth_codes`, `oauth_tokens` | **함께 삭제** (CASCADE) |
| `users` → `versions.user_id` | **NULL 로 바뀜** (SET NULL) — 기록은 `username` 으로 남음 |
| `projects` → `nodes`, `versions`, `terms`, `term_categories`, `images` | **함께 삭제** (CASCADE) |
| `nodes` → 하위 `nodes` | **함께 삭제** (CASCADE) — 부모를 지우면 하위 트리 전체가 사라짐 |
| `nodes` → `comments` | **함께 삭제** (CASCADE) |
| `term_categories` → `terms.category_id` | **NULL 로 바뀜** (SET NULL) — 용어는 미분류로 남음 |

## 테이블 상세

`PK` 기본키 · `FK` 외래키 · `UK` 고유 · `NN` NOT NULL. 기본값이 없는 칸은 비워 두었습니다.

### users — 사용자

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 사용자 ID | serial | PK | 자동 증가 | |
| `username` | 이전 로그인 ID | text | UK, NN | | 이전 버전 호환용. 새 계정은 `login_id`와 같은 값으로 저장 |
| `login_id` | 로그인 ID | text | UK (`users_login_id_idx`), NN | | 로그인과 중복 확인에 사용 |
| `display_name` | 표시 이름 | text | NN | | 화면에 표시. 중복 허용 |
| `password` | 비밀번호 해시 | text | NN | | `salt$hash` 형식(PBKDF2-SHA256, 10만 회). 원문 저장 안 함 |
| `role` | 등급 | text | NN | `'member'` | `admin`(무제한·관리자 페이지) · `pro`(5) · `member`(3) · `guest`(1). 프로젝트 수와 이미지 총량 한도를 정함 |
| `status` | 상태 | text | NN | `'pending'` | `active` 로그인 가능 · `pending` 가입 승인 대기. 첫 계정만 곧바로 `admin`/`active` |
| `created_at` | 가입 신청 시각 | timestamptz | NN | `now()` | 가입 신청 목록 정렬 기준 |
| `avatar` | 프로필 이미지 | text | | | 128px 정사각형 data URL. 프런트에서 줄여 보내며 상한 200,000자 |

### project_members — 프로젝트 참여자

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `project_id` | 프로젝트 | int | PK, FK → projects(id) CASCADE, NN | | |
| `user_id` | 참여자 | int | PK, FK → users(id) CASCADE, NN | | |
| `role` | 권한 | text | NN | `'editor'` | `editor` 편집자 · `coowner` 공동 소유자. 예전 `viewer` 행은 기동 시 `editor` 로 올림 |
| `status` | 상태 | text | NN | `'pending'` | `pending` 승인 대기(아무 권한 없음) · `active` 멤버 |
| `created_at` | 요청 시각 | timestamptz | NN | `now()` | 참여 요청 목록 정렬 기준 |

권한은 5단계입니다. `access_level()` 한 곳에서 판정하고 `require()` 가 필요 등급과 비교합니다 —
소유자 → `owner`, `status='active'` 인 멤버 → 그 `role`, 유효한 공유 토큰 → 로그인했으면
`commenter` 아니면 `reader`, 그 밖 → 권한 없음.

| 등급 | 읽기·내보내기 | 코멘트 | 내용 수정 · 앨범 · 버전 · MCP | 공유 링크 · 멤버 · 이름 변경 | 프로젝트 삭제 |
|---|---|---|---|---|---|
| `reader` (공유 링크 · 비로그인) | O | | | | |
| `commenter` (공유 링크 · 로그인) | O | O | | | |
| `editor` 편집자 | O | O | O | | |
| `coowner` 공동 소유자 | O | O | O | O | |
| `owner` 소유자 | O | O | O | O | O |

### api_tokens — MCP·플러그인 토큰

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `token` | 토큰 | text | PK | | `olg_` + `secrets.token_urlsafe(24)`. 접두어로 세션 토큰과 구분 |
| `id` | 번호 | serial | UK | 자동 증가 | 목록·삭제에 쓰는 값. 토큰 자체를 다시 내보내지 않으려고 둠 |
| `user_id` | 소유 계정 | int | FK → users(id) CASCADE, NN | | |
| `name` | 토큰 이름 | text | NN | `'플러그인'` | 기기·용도 구분용 |
| `created_at` | 발급 시각 | timestamptz | NN | `now()` | |
| `last_used_at` | 마지막 사용 | timestamptz | | | 요청마다 쓰지 않고 **한 시간에 한 번만** 갱신 |

`opt_user()` 가 `Bearer` 값의 접두어를 보고 `api_tokens`(olg_…), `oauth_tokens`(olgo_…),
`sessions` 중 어디를 볼지 고릅니다.
브라우저 로그아웃은 `sessions` 만 지우므로 플러그인은 계속 동작하고,
관리자 비밀번호 재설정은 두 테이블을 함께 지웁니다.

### oauth_clients — OAuth 동적 클라이언트

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `client_id` | 클라이언트 ID | text | PK | | DCR 시 MCP SDK가 생성. 연결이 유지되는 동안 재사용 |
| `client_info` | 클라이언트 정보 | jsonb | NN | | callback·이름·grant·인증 방식. `none` 공개 클라이언트만 허용 |
| `created_at` | 등록 시각 | timestamptz | NN | `now()` | |

### oauth_requests — OAuth 로그인 승인 요청

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `request_hash` | 승인 요청 해시 | text | PK | | 원문은 브라우저에만 전달하고 DB에는 SHA-256 해시 저장 |
| `client_id` | 클라이언트 | text | FK → oauth_clients(client_id) CASCADE, NN | | |
| `state` | 상태값 | text | | | callback 시 클라이언트에 그대로 반환 |
| `scopes` | 요청 권한 | jsonb | NN | | 현재 `mcp` 하나 |
| `code_challenge` | PKCE 챌린지 | text | NN | | S256만 허용 |
| `redirect_uri` | callback 주소 | text | NN | | DCR에 등록된 주소와 정확히 일치 |
| `redirect_uri_provided_explicitly` | callback 명시 여부 | boolean | NN | | 토큰 교환 시 동일 주소 검증에 사용 |
| `resource` | 보호 리소스 | text | NN | | `PUBLIC_URL/mcp`; 토큰 audience로 이어짐 |
| `expires_at` | 만료 시각 | timestamptz | NN | | 10분 |

### oauth_codes — 일회용 인증 코드

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `code_hash` | 인증 코드 해시 | text | PK | | 원문 저장 안 함. 교환 성공 시 즉시 삭제 |
| `client_id` | 클라이언트 | text | FK → oauth_clients(client_id) CASCADE, NN | | |
| `user_id` | 승인 사용자 | int | FK → users(id) CASCADE, NN | | |
| `scopes` | 승인 권한 | jsonb | NN | | |
| `code_challenge` | PKCE 챌린지 | text | NN | | token 요청의 verifier와 S256 비교 |
| `redirect_uri` | callback 주소 | text | NN | | |
| `redirect_uri_provided_explicitly` | callback 명시 여부 | boolean | NN | | |
| `resource` | 보호 리소스 | text | NN | | |
| `expires_at` | 만료 시각 | timestamptz | NN | | 5분 |

### oauth_tokens — OAuth access·refresh 토큰

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `access_token_hash` | 액세스 토큰 해시 | text | PK | | `olgo_` 원문 대신 SHA-256 해시 저장 |
| `refresh_token_hash` | 갱신 토큰 해시 | text | UK, NN | | `olgr_` 원문 대신 SHA-256 해시 저장 |
| `client_id` | 클라이언트 | text | FK → oauth_clients(client_id) CASCADE, NN | | |
| `user_id` | 연결 사용자 | int | FK → users(id) CASCADE, NN | | |
| `scopes` | 발급 권한 | jsonb | NN | | 요청마다 `mcp` scope 확인 |
| `resource` | 보호 리소스 | text | NN | | 요청마다 현재 `PUBLIC_URL/mcp`와 비교 |
| `access_expires_at` | 액세스 만료 | timestamptz | NN | | 발급 후 1시간 |
| `refresh_expires_at` | 갱신 만료 | timestamptz | NN | | 발급 후 30일. 갱신 시 access·refresh 모두 회전 |
| `created_at` | 발급 시각 | timestamptz | NN | `now()` | |
| `last_used_at` | 마지막 사용 | timestamptz | | | 한 시간에 한 번만 갱신 |

OAuth 로그인은 기존 `users.login_id`·비밀번호와 `login_attempts` 잠금 정책을 그대로 사용합니다.
비밀번호 변경·관리자 재설정·계정 삭제 시 해당 사용자의 미사용 인증 코드와 OAuth 토큰도 폐기됩니다.

### settings — 서비스 설정

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `key` | 설정 키 | text | PK | | 현재 `signup_open` 하나 |
| `value` | 설정 값 | text | NN | | `1` 가입 허용 · `0` 차단 |

### login_attempts — 로그인 실패 기록

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `key` | 잠금 키 | text | PK | | `u:<이름>@<IP>` (그 IP 에서 그 계정) 또는 `ip:<IP>` (그 IP 전체) |
| `fails` | 연속 실패 횟수 | int | NN | `0` | 10분 안의 실패만 이어서 셈. 잠글 때 0 으로 되돌림 |
| `locks` | 잠긴 횟수 | int | NN | `0` | 잠금 시간 단계. 24시간 조용하면 0 으로 되돌림 |
| `locked_until` | 잠금 해제 시각 | timestamptz | | | 이 시각까지 로그인을 막음 |
| `last_fail` | 마지막 실패 시각 | timestamptz | NN | `now()` | 위 두 초기화 판단 기준 |

로그인 ID만으로 잠그면 남의 아이디를 잠글 수 있어 **IP 를 키에 함께** 넣습니다.
`u:` 키가 5회, `ip:` 키가 20회를 넘으면 잠그고, **반복될수록 잠금이 길어집니다** —
30초 → 1분 → 3분 → 5분 → 10분 → 30분(이후 유지). IP 는 nginx 가 넣는 `X-Real-IP` 를 씁니다.
로그인 성공·비밀번호 변경 시 해당 키를 지우고, 기동 시 24시간 지난 행을 정리합니다.

### sessions — 로그인 세션

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `token` | 세션 토큰 | text | PK | | `Authorization: Bearer <token>` 으로 전달 |
| `user_id` | 사용자 | int | FK → users(id) CASCADE, NN | | |
| `created_at` | 발급 시각 | timestamptz | NN | `now()` | 기동 시 30일 지난 세션을 정리하는 기준 |

세션은 로그아웃하거나, 발급 30일이 지나 백엔드가 다시 기동될 때 삭제됩니다(요청마다 만료 검사는 하지 않음).

### projects — 프로젝트

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 프로젝트 ID | serial | PK | 자동 증가 | **내부용**. 모든 FK 가 이 값을 참조하고 응답에는 내보내지 않음 |
| `slug` | 주소 키 | text | UK (`projects_slug_idx`) | | 주소·API 에 쓰는 랜덤 키(`secrets.token_urlsafe(9)`, 12자). 예전 행은 기동 시 채움. 순번을 감추기 위한 것이고 권한 검사를 대신하지 않음 |
| `owner_id` | 소유자 | int | FK → users(id) CASCADE | | NULL 허용 — 사용자가 없는 DB 를 이관할 때만 비게 됨 |
| `name` | 프로젝트 이름 | text | NN | | |
| `prd` | PRD 본문 | text | NN | `''` | 마크다운 전체. 별도 테이블이 아님 |
| `share_token` | 공유 토큰 | text | | | 값이 있으면 `/?share=<token>` 으로 비소유자 접근 허용 |

프로젝트를 가리키는 값은 **`slug` 하나**입니다 — 주소(`/project/<slug>`)·API(`/api/projects/<slug>/…`)·
MCP 툴의 `project_id` 모두 slug 를 씁니다. `find_project()` 가 slug 를 내부 `id` 로 바꾸고,
숫자를 주면 예전 id 로도 찾아 줍니다(오래된 북마크 호환).

### nodes — 기능명세서 항목 (트리)

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 항목 ID | serial | PK | 자동 증가 | |
| `project_id` | 소속 프로젝트 | int | FK → projects(id) CASCADE, NN | | |
| `parent_id` | 상위 항목 | int | FK → nodes(id) CASCADE | | NULL 이면 대분류(1단계). 최대 4단계 |
| `title` | 제목 | text | NN | | |
| `description` | 설명 | text | NN | `''` | 마크다운. `` `용어` `` · `![](…)` · `[이름](url)` 문법 사용 |
| `status` | 진행 상태 | text | NN | `'기획 작성중'` | 기획 작성중 / 기획 완료 / 개발 중 / 완료 |
| `importance` | 중요도 | int | NN | `2` | 1 필수(Must) · 2 권장(Should) · 3 선택(Could) · 4 보류(Won't) |
| `sort_order` | 순서 | int | NN | `0` | 같은 부모 안에서의 정렬 순서 |

순환 참조(자기 하위로 이동)는 DB 제약이 아니라 API 에서 재귀 CTE 로 검사해 막습니다.

### comments — 코멘트

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 코멘트 ID | serial | PK | 자동 증가 | |
| `node_id` | 대상 항목 | int | FK → nodes(id) CASCADE, NN | | |
| `user_id` | 작성자 | int | FK → users(id) CASCADE, NN | | 본인만 삭제 가능 |
| `content` | 내용 | text | NN | | |
| `created_at` | 작성 시각 | timestamptz | NN | `now()` | |

### versions — PRD + 기능명세서 버전(스냅샷)

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 버전 ID | serial | PK | 자동 증가 | |
| `project_id` | 소속 프로젝트 | int | FK → projects(id) CASCADE, NN | | |
| `user_id` | 저장한 사용자 | int | FK → users(id) SET NULL | | 사용자가 삭제되면 NULL |
| `username` | 저장 당시 이름 | text | NN | | 사용자 삭제 후에도 표시하기 위해 복사해 둠 |
| `created_at` | 저장 시각 | timestamptz | NN | `now()` | |
| `data` | 기능 트리 스냅샷 | jsonb | NN | | `nodes` 행 배열(`id, parent_id, title, description, status, importance, sort_order`) |
| `prd` | PRD 스냅샷 | text | | | 그 시점의 `projects.prd` 본문 |

복원 시 살아 있는 항목은 `id` 를 유지(UPSERT)하여 코멘트가 보존되고, `projects.prd` 는 스냅샷으로 덮어씁니다.

`prd` 는 나중에 추가한 컬럼이라 NULL 을 허용합니다. `prd` 열이 없던 시절의 버전은
컬럼을 추가하는 기동 때 **그 시점의 현재 PRD** 로 한 번 채워집니다(`UPDATE … WHERE prd IS NULL`, 멱등).

### term_categories — 용어 카테고리

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 카테고리 ID | serial | PK | 자동 증가 | |
| `project_id` | 소속 프로젝트 | int | FK → projects(id) CASCADE, NN | | |
| `name` | 카테고리 이름 | text | NN | | `(project_id, name)` UNIQUE |

### terms — 용어 사전

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 용어 ID | serial | PK | 자동 증가 | |
| `project_id` | 소속 프로젝트 | int | FK → projects(id) CASCADE, NN | | |
| `term` | 용어 | text | NN | | `(project_id, term)` UNIQUE. 본문의 `` `용어` `` 에서 자동 수집 |
| `description` | 설명 | text | NN | `''` | 마크다운 |
| `note` | 비고 | text | NN | `''` | 마크다운 |
| `sort_order` | 표시 순서 | int | NN | `0` | 기본값은 등록(본문 등장) 순서 |
| `category_id` | 카테고리 | int | FK → term_categories(id) SET NULL | | NULL 이면 미분류 |

행은 사용자가 직접 만들지 않습니다. `GET /api/projects/{pid}/terms` 호출 시 PRD·기능 설명을 스캔해
**새 용어는 INSERT, 어디에도 없는 용어는 DELETE** 합니다(설명도 함께 사라짐).

### images — 업로드 이미지

| 컬럼 | 한글 이름 | 타입 | 키/제약 | 기본값 | 설명 |
|---|---|---|---|---|---|
| `id` | 이미지 ID | text | PK | | URL-safe 난수 토큰. `/api/images/<id>` 로 서빙 |
| `project_id` | 소속 프로젝트 | int | FK → projects(id) CASCADE, NN | | |
| `mime` | MIME 타입 | text | NN | | `image/png` 등 |
| `data` | 바이너리 | bytea | NN | | 파일시스템이 아닌 DB 에 저장. 한 장 5MB, 계정 총량은 등급별(`admin` 무제한 · `pro` 500MB · `member` 200MB · `guest` 50MB). PNG·JPEG·GIF·WebP 만 받고 업로드 시 앞바이트로 검증 |
| `created_at` | 업로드 시각 | timestamptz | NN | `now()` | 앨범의 날짜 구분 기준 |

본문은 이미지를 `![](/api/images/<id>)` **문자열로만** 참조하므로 FK 가 없습니다.
"사용 중" 여부는 `projects.prd` 와 `nodes.description` 을 텍스트 검색해 계산합니다.

## 문자열로만 연결된 참조 (FK 없음)

ERD 선으로 보이지 않지만 애플리케이션이 텍스트를 스캔해 유지하는 관계입니다. 관련 로직을 바꿀 때 주의하세요.

| 출처 | 대상 | 방법 |
|---|---|---|
| `projects.prd`, `nodes.description` 의 `![](/api/images/<id>)` | `images.id` | 앨범의 사용 여부(`used`) 판정 |
| `projects.prd`, `nodes.description` 의 `` `용어` `` | `terms.term` | 용어 행 자동 생성·삭제, 사용처 이동 |

## 인덱스

PK / UNIQUE 인덱스 외에 **모든 FK 컬럼에 단일 인덱스**가 있습니다 (`<테이블>_<컬럼>_idx`).
프로젝트 단위 조회와 `ON DELETE CASCADE` 가 전부 이 컬럼들을 타기 때문입니다.

| 인덱스 | 대상 |
|---|---|
| `nodes_project_id_idx`, `nodes_parent_id_idx` | 트리 조회 · 하위 연쇄 삭제 |
| `comments_node_id_idx`, `comments_user_id_idx` | 항목별 코멘트 |
| `images_project_id_idx`, `terms_project_id_idx`, `terms_category_id_idx`, `term_categories_project_id_idx`, `versions_project_id_idx` | 프로젝트별 목록 |
| `users_login_id_idx` | 로그인 ID 중복 방지 |
| `sessions_user_id_idx`, `projects_owner_id_idx`, `oauth_codes_user_id_idx`, `oauth_tokens_user_id_idx` | 사용자 삭제 시 연쇄 |
| `oauth_requests_client_id_idx`, `oauth_codes_client_id_idx`, `oauth_tokens_client_id_idx` | OAuth 클라이언트 삭제 시 연쇄 |

## 레거시 정리 이력

- `prd` 테이블(프로젝트 도입 전 단일 PRD): 내용을 `projects.prd` 로 이관한 뒤 `init_db()` 에서 `DROP TABLE IF EXISTS prd` 로 제거. 구버전 볼륨도 첫 기동에 이관 → 삭제 순서로 처리됨.
- `nodes.project_id`, `images.project_id`: `ALTER … ADD COLUMN` 으로 늦게 추가되어 NULL 허용이었으나 이관 후 `SET NOT NULL` 로 승격.



## 현재 스키마 확인 방법

문서와 실제 DB 가 어긋났는지 확인할 때:

```bash
docker compose exec -T db psql -U app -d app -c "\dt"          # 테이블 목록
docker compose exec -T db psql -U app -d app -c "\d+ nodes"    # 컬럼 · 기본값 · 인덱스 · FK 한 번에
```
