# 얼개 플래너 (olgae-planner)

제품 PRD 문서와 기능명세서(계층형 기능 트리)를 웹에서 **수정·추가·삭제**할 수 있는 데모 서비스입니다.
기능명세서는 **트리 뷰**(가로형 마인드맵, 곡선 연결선)와 **디렉토리 뷰**(목록 + 문서 상세) 두 가지로 볼 수 있습니다.

## 주요 기능

- **PRD 탭**: 마크다운 문서 보기/저장. 본문을 **더블클릭**하면 클릭한 위치에 커서를 둔 편집 화면으로 전환
- **기능명세서 탭**
  - 트리 뷰: PRD 루트에서 대분류 → 상세 기능으로 뻗는 마인드맵, 대분류별 색상 구분
  - 디렉토리 뷰: 좌측 번호 목록 + 우측 문서형 상세
  - 헤더는 아이콘 버튼(문서/홈/트리 뷰/디렉토리 뷰)으로 구성
  - 대분류 추가는 트리 끝에 연결된 반투명 `＋ 대분류 추가` 가지(디렉토리 뷰는 목록 하단 줄)를 클릭
  - 하위 항목 추가는 카드의 `＋`, 제목·설명은 **더블클릭**하면 그 자리에서 편집(마크다운), 삭제는 두 번 클릭 확인
  - 디렉토리 뷰도 `▼/▶` 로 접기·펼치기(트리 뷰와 상태 공유), 콘텐츠 좌측 상단에 `전체 접기`/`전체 펼치기`
  - **드래그 & 드롭**: 카드를 다른 카드 박스 위에 드롭 → 그 하위로 이동. 트리 뷰의 `PRD` 루트 카드(또는 디렉토리 뷰 목록 빈 곳)에 드롭 → 대분류로 승격. 자기 하위로의 순환 이동은 차단
  - **▲▼ 버튼**: 같은 부모 안에서 순서 변경
- **사용자 / 코멘트**
  - 로그인 ID + 표시 이름 + 8자 이상 비밀번호로 회원가입, 로그인 ID + 비밀번호로 로그인
    (PBKDF2 해시, DB 세션 토큰 — 발급 30일 지난 세션은 기동 시 정리)
  - MCP·플러그인은 별도의 **계정별 API 토큰**(`olg_…`)을 씁니다 — 로그아웃해도 유지
  - 로그인한 사용자는 각 기능 항목에 코멘트 작성 가능, 본인 코멘트만 삭제 가능
  - **가입 승인제**: 첫 계정은 곧바로 관리자, 이후 가입은 `pending` 으로 대기하며 관리자 승인 후 로그인
  - **로그인 시도 제한**: 같은 IP 에서 한 계정에 5회, 또는 한 IP 에서 총 20회 실패하면 잠김.
    잠금이 반복될수록 **30초 → 1분 → 3분 → 5분 → 10분 → 30분** 으로 길어지고, 24시간 조용하면 처음으로 돌아감
    (로그인 ID만으로 잠그지 않아 남의 아이디를 잠글 수 없음. 성공·비밀번호 변경 시 해제)
  - **등급별 프로젝트 한도**: `admin` 무제한 · `pro` 5개 · `member` 3개 · `guest` 1개
  - **내 계정 창**: 헤더의 사용자 아이콘을 누르면 프로필 이미지 등록, 등급,
    남은 프로젝트 수·이미지 용량 게이지, 비밀번호 변경이 한 창에 뜸
  - **등급별 이미지 총량**: `admin` 무제한 · `pro` 500MB · `member` 200MB · `guest` 50MB
    (한 장 5MB 상한은 그대로. 총량은 프로젝트 소유자 몫에서 차감되어, 공유 링크로 올려도 소유자 기준)
- **이미지**
  - 기능 설명·PRD 편집 중 이미지 붙여넣기(Ctrl+V), 끌어놓기, `이미지 추가` 버튼 지원
  - 이미지는 DB(`images` 테이블)에 저장되고 `![](/api/images/<id>)` 마크다운으로 본문에 삽입됨
  - 헤더 메뉴 → **이미지 앨범**(우측 사이드 탭): 추가 날짜별로 묶여 최근 순으로 표시
  - 본문에서 사용 중인 이미지는 파란 테두리, 미사용은 테두리 없음
  - 이미지 **우클릭 → 마크다운 링크 복사**(`![](…)`), 클립보드가 막히면 직접 복사할 수 있는 창 표시
  - 사진을 **좌클릭하면 선택**(회색 표시). `전체 선택` / `전체 해제` 버튼은 항상 표시
  - 선택이 있으면 우측 상단 **휴지통이 빨갛게 변하고 좌측 위에 선택 개수 배지**가 뜨며, 누르면 삭제
- **용어 사전**
  - 본문(PRD·기능 설명)에서 백틱으로 감싼 텍스트(`` `TCE` ``)는 용어 링크로 표시됨
  - 헤더 좌측 `[abc]` 아이콘 → 용어 | 설명 표. 설명은 클릭해서 마크다운으로 작성
  - 본문에 새 용어가 생기면 자동으로 행 생성, 어느 문서에서도 쓰이지 않으면 자동 삭제
  - 본문의 용어에 마우스를 올리면 설명이 말풍선으로 표시됨(말풍선 안 링크도 클릭 가능)
  - 각 용어의 **사용처 버튼**(PRD·기능 항목)을 누르면 그 위치로 바로 이동
  - 기본 정렬은 등록된 순서(본문 등장 순서), 표의 ▲▼ 로 변경 가능
  - `카테고리로 분류` 토글 → 카테고리별 그룹 보기, 카테고리 추가/삭제 및 용어별 카테고리 지정
  - 카테고리를 삭제해도 속해 있던 용어는 미분류로 남음
- **마크다운 문법** (PRD·기능 설명·용어 설명 공통)
  - 표: `| 머리 | 글 |` + `|---|---|` (구분선에 `:---`·`---:`·`:---:` 로 정렬 지정, 줄 사이 빈 줄 허용)
  - 강조: `**굵게**`, `*기울임*`, `_기울임_`
  - 제목 `#`~`###`, 불릿 `- `, 이미지 `![](url)`
  - `[표시이름](https://...)` → 하이퍼링크
  - 주소만 적어도 자동 링크(`[url](url)` 과 동일). 스킴 없는 `localhost:3000/...`·`example.com/...` 도 인식
  - 링크는 항상 새 탭에서 열림. `javascript:`·`data:` 같은 주소는 링크로 만들지 않음
- **버전 기록 (PRD + 기능명세서)**
  - 헤더의 **저장 아이콘**(용어 사전 옆) 한 번으로 현재 PRD와 기능 트리를 함께 스냅샷 저장
  - 헤더 메뉴 → `버전 기록`에서 목록 확인 · 저장 · 복원
  - 목록에 **저장 일시 · 저장한 사용자 · 항목 수** 표시, `불러오기`로 그 시점으로 복원(두 번 클릭 확인)
  - 복원하면 PRD 본문도 그 시점으로 되돌아감. 살아남는 항목은 id 를 유지해 해당 항목의 코멘트가 보존됨
  - `prd` 컬럼 추가 이전에 저장된 버전은 컬럼이 생기는 기동 때의 PRD 로 채워짐
- **내보내기**
  - 헤더 `⋯` 메뉴의 **마크다운으로 내보내기** → PRD + 기능명세서 전체를 `<프로젝트명>.md` 파일로 저장
  - 기능은 번호가 매겨진 헤딩(`### 1`, `#### 1.1`)과 상태·중요도 목록으로 출력, 이미지 주소는 절대경로로 변환
- **관리자 페이지** (헤더 메뉴 → `관리자`, admin 등급만)
  - 계정 목록: 계정 정보(로그인 ID·이름·비밀번호)·등급 변경, 프로젝트 수/한도 확인, 계정 완전 삭제
  - 계정별 프로젝트 목록에서 개별 프로젝트 삭제
  - 신규 가입: 허용/차단 토글, 가입 신청 목록, 등급을 골라 승인, 거절
  - 마지막 관리자 계정은 강등·삭제가 차단되고, 자기 계정은 삭제할 수 없음
- **주소(라우팅)**
  - `/` 내 프로젝트 · `/project/<slug>` 프로젝트 · `/admin` 관리자
  - 프로젝트는 순번이 아니라 **랜덤 키(slug)** 로 가리킵니다 — 주소·API 모두
    (`/project/k7mQ2xR9vBnP`, `/api/projects/k7mQ2xR9vBnP/prd`). 숫자 id 는 DB 내부에만 남습니다
  - 보고 있는 화면이 쿼리로 남습니다 — `?tab=spec`(기능명세서 탭) · `&view=dir`(디렉토리 뷰).
    없으면 각각 PRD 탭 · 트리 뷰가 기본
  - 공유 링크도 같은 규칙 — `/?share=<토큰>&tab=spec&view=dir`. 프로젝트 id 는 주소에 드러나지 않음
  - 새로고침·뒤로 가기·주소 복사가 그대로 동작(뒤로 가기는 탭·뷰까지 되돌림)
  - nginx 가 `try_files $uri /index.html` 로 모든 경로를 앱 셸로 넘깁니다(SPA)
  - `/admin` 은 앱 셸만 공개되고 데이터는 없습니다. `robots.txt` 로 `Disallow`,
    응답에 `X-Robots-Tag: noindex, nofollow` 를 붙여 색인을 막습니다
- **프로젝트 / 멤버**
  - 사용자별로 여러 프로젝트 생성/이름 변경/삭제 (PRD와 기능 트리는 프로젝트 단위)
  - **공유 링크는 읽기 전용**입니다. 링크가 유출되어도 내용이 바뀌지 않습니다
  - 공유 링크로 들어온 로그인 사용자는 헤더의 **참여 요청** 버튼으로 참여를 신청
  - 소유자·공동 소유자는 `멤버 관리`에서 승인/거절, 권한 변경, 멤버 제외
  - 권한 5단계:

    | 등급 | 할 수 있는 일 |
    |---|---|
    | 공유 링크 · 비로그인 | 읽기, 마크다운 내보내기 |
    | 공유 링크 · 로그인(미승인) | 위 + 코멘트 |
    | **편집자** | 위 + 내용 수정, 이미지 앨범, 버전 기록, MCP·플러그인으로 조회 |
    | **공동 소유자** | 위 + 공유 링크 관리, 멤버 관리, 이름 변경 |
    | 소유자 | 위 + 프로젝트 삭제 |

  - 참여중인 프로젝트는 `내 프로젝트` 목록에 **소유자 이름과 권한**이 함께 표시되고,
    권한에 따라 버튼이 달라집니다
  - 프로젝트 소유자만 접근 가능. 소유자가 **공유 링크**(`/?share=<token>`)를 생성하면 링크를 아는 누구나 열람·편집 가능, 링크 해제 시 즉시 차단
  - 구버전 DB(프로젝트 개념 이전 데이터)는 첫 기동 시 "기본 프로젝트"로 자동 마이그레이션 후 레거시 `prd` 테이블 제거

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
| GET / PUT | `/api/projects/{pid}/prd` | PRD 문서 조회/저장 (`{content}`) |
| GET / POST | `/api/projects/{pid}/nodes` | 기능 노드 목록 / 생성 (`{parent_id, title}`) |
| PUT | `/api/nodes/{id}` | 부분 수정 (`title/description/status/importance/sort_order/parent_id`) — 순환 이동·타 프로젝트 이동은 400 |
| DELETE | `/api/nodes/{id}` | 삭제 (하위 노드 연쇄 삭제) |
| POST | `/api/projects/{pid}/images` | 이미지 업로드 (원본 바이트 + `Content-Type: image/*`, 5MB 이하) → `{url}` |
| GET | `/api/images/{id}` | 업로드된 이미지 조회 |
| GET | `/api/projects/{pid}/terms` | 용어 목록 (호출 시 본문을 스캔해 자동 생성·삭제) |
| PUT | `/api/terms/{tid}` | 용어 수정 (`{description?, note?, category_id?, sort_order?}`) |
| GET / POST | `/api/projects/{pid}/term-categories` | 카테고리 목록 / 추가 (`{name}`) |
| DELETE | `/api/term-categories/{cid}` | 카테고리 삭제 (용어는 미분류로 남음) |
| GET / POST | `/api/projects/{pid}/versions` | 버전 목록 / 현재 PRD + 기능명세서 스냅샷 저장 (로그인 필요) |
| POST | `/api/versions/{vid}/restore` | 해당 버전으로 복원 — PRD 도 함께 (로그인 필요) |
| DELETE | `/api/versions/{vid}` | 버전 삭제 — 소유자만 |
| GET | `/api/projects/{pid}/images` | 앨범 목록 (`id, created_at, bytes, used`) |
| POST | `/api/projects/{pid}/images/delete` | 선택 이미지 삭제 (`{ids: [...]}`) → `{deleted, bytes}` |
| GET | `/api/auth/id-available?login_id=...` | 로그인 ID 중복 확인 (`{available}`) |
| POST | `/api/auth/register` | 회원가입 (`{login_id, display_name, password}`·비밀번호 8자 이상) |
| POST | `/api/auth/login` | 로그인 (`{login_id, password}`) |
| POST | `/api/auth/logout` | 로그아웃 (Bearer 토큰) |
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

백엔드가 `/mcp` 에 HTTP MCP 엔드포인트를 함께 제공합니다. 사용자는 **설치 없이 명령 한 줄**로 등록합니다.

인증은 **계정별 API 토큰**(`olg_…`)으로 합니다. 브라우저 세션과 별개라 로그아웃해도 계속 쓸 수 있습니다.
앱에서 헤더 메뉴 → **플러그인 설치** 를 열어 `+ 새 토큰 발급` 을 누르면 됩니다
(발급 직후 한 번만 전체 값이 보이고, 목록에는 앞뒤만 남습니다. 유출됐으면 그 자리에서 삭제).

토큰으로 보이는 것은 **그 계정이 만든 프로젝트 + 멤버로 참여중인 프로젝트**이고,
할 수 있는 일은 화면에서와 똑같이 프로젝트별 권한(편집자·공동 소유자·소유자)을 따릅니다.
플러그인(마켓플레이스)으로 설치하는 방법이 기본이고, 아래 `claude mcp add` 는 플러그인 없이 MCP 만 붙일 때 씁니다.

```bash
claude mcp add --transport http olgae-planner https://<호스트>/mcp -H "Authorization: Bearer olg_..."
```

Cursor·Claude Desktop 등은 같은 창의 JSON 을 설정 파일에 붙여 넣습니다.

```json
{ "mcpServers": { "olgae-planner": { "type": "http", "url": "https://<호스트>/mcp",
  "headers": { "Authorization": "Bearer olg_..." } } } }
```

- 인증은 **요청마다 Authorization 헤더**로 하고, 권한 판정은 REST API 와 같은 코드
  (`opt_user` / `access_level` / `require`)를 그대로 씁니다. 계정별 권한 그대로 동작합니다.
- 토큰은 계정 하나에 최대 10개, 이름·발급일·마지막 사용 시각이 기록됩니다.
  로그아웃해도 살아 있고, **관리자가 비밀번호를 재설정하면** 세션과 함께 끊깁니다.
- `/mcp` 는 Host 검사로 DNS 리바인딩을 막습니다. `docker-compose.yml` 의 `MCP_ALLOWED_HOSTS` 가
  기본값으로 로컬 주소(`localhost:3000,127.0.0.1:3000`)만 허용하므로, **배포할 때는 도메인을 넘겨야 합니다**:

  ```bash
  MCP_ALLOWED_HOSTS=prd.example.com docker compose up -d
  ```

  콤마로 여러 개(`prd.example.com,localhost:3000`) 지정할 수 있고, 빈 값(`MCP_ALLOWED_HOSTS=`)이면 검사를 끕니다.

### 플러그인 (MCP + 작성 규칙 스킬)

`plugin/` 은 MCP 연결과 이 서비스의 작성 컨벤션 스킬을 함께 담은 플러그인입니다.
Claude Code 와 Codex 양쪽 매니페스트가 들어 있고, 토큰·주소는 환경변수로 받습니다.

```bash
export OLGAE_URL=https://<호스트>/mcp
export OLGAE_TOKEN=olg_...        # 앱 → 플러그인 설치 → + 새 토큰 발급
claude plugin marketplace add kdHyeok/olgae-planner   # 또는 클론한 저장소에서 ./
claude plugin install olgae-planner@olgae-planner
```

저장소가 public 이면 **누구나 위 두 줄로 설치**할 수 있습니다. 플러그인에는 주소도 토큰도
들어 있지 않고 `${OLGAE_URL}` · `${OLGAE_TOKEN}` 으로 받으므로, 각자 자기 서버·자기 토큰을
환경변수로 넣어 씁니다 — 한 플러그인으로 여러 배포 서버를 쓸 수 있습니다.

개발 중에 `./` 로 등록해 뒀다면 이름이 같아 GitHub 소스를 그냥 더할 수 없습니다.
지우고 다시 등록하세요(자세한 설명은 [plugin/README.md](plugin/README.md#소스-갈아타기-로컬-경로--github)):

```bash
claude plugin marketplace remove olgae-planner
claude plugin marketplace add kdHyeok/olgae-planner
claude plugin install olgae-planner@olgae-planner
```

이미 `claude mcp add olgae-planner` 으로 수동 등록해 뒀다면 이름이 겹쳐 플러그인 설정이 가려집니다
(`claude mcp remove olgae-planner` 후 사용).

스킬 `olgae-planner` 에 담긴 규칙: 용어는 백틱으로 감싸 사전에 등록(코드·파일명에는 쓰지 않음),
본문에 첨부된 URL 은 열어서 확인, **와이어프레임·유저플로우 등 산출물은 명세에 실제로 있는 내용만** 사용,
큰 수정 전 `save_version`. 자세한 내용은 [plugin/README.md](plugin/README.md) 와
[plugin/skills/olgae-planner/SKILL.md](plugin/skills/olgae-planner/SKILL.md) 를 보세요.

### 로컬 테스트

```bash
docker compose up -d --build
# 로그인해 세션 토큰을 받고, 그것으로 API 토큰을 발급받는다
SESS=$(curl -s -X POST http://localhost:3000/api/auth/login \
  -H "Content-Type: application/json" -d '{"login_id":"<아이디>","password":"<비밀번호>"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
TOK=$(curl -s -X POST http://localhost:3000/api/me/tokens \
  -H "Authorization: Bearer $SESS" -H "Content-Type: application/json" -d '{"name":"local"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['token'])")
# 등록 (-s local: 내 기기에만 저장)
claude mcp add --transport http olgae-planner http://localhost:3000/mcp -s local \
  -H "Authorization: Bearer $TOK"
```

등록 뒤 Claude Code 를 재시작하고 `/mcp` 로 연결 상태를 확인합니다.
목록에 `Connected` 로 떠도 토큰 검사를 통과한 것은 아니니 `list_projects` 를 한 번 호출해 보세요.
브라우저에서 로그인한 상태라면 **플러그인 설치** 창의 명령을 그대로 복사하는 것이 가장 빠릅니다.

| 툴 | 설명 |
|---|---|
| `list_projects` | 내 프로젝트 목록 (project_id 확인) |
| `get_spec` | PRD 본문 + 기능 트리 한 번에. 화면과 같은 계층 번호(`1`, `1.1`) 포함 |
| `set_prd` | PRD 본문 전체 덮어쓰기 |
| `create_node` / `update_node` / `delete_node` | 기능 항목 추가 / 부분 수정 / 삭제(하위 포함) |
| `list_terms` / `set_term` | 용어 목록(호출 시 자동 동기화) / 설명·비고·카테고리·순서 수정 |
| `save_version` / `list_versions` / `restore_version` | 스냅샷 저장 / 목록 / 복원 |
| `list_comments` / `add_comment` | 코멘트 조회 / 작성 |

프로젝트 생성·삭제, 공유 링크 관리, 이미지 업로드·삭제는 툴로 열지 않았습니다(웹 UI 에서 처리).
공유 링크 토큰만으로 접근하는 모드는 아직 지원하지 않습니다 — 그 경우 버전 저장·복원과 코멘트 작성이 API 에서 막힙니다.

## 프로젝트 구조

```
├── docker-compose.yml
├── CLAUDE.md            # 작업 규칙 (DB 변경 시 doc/ERD.md 갱신 등)
├── doc/
│   └── ERD.md           # DB 스키마 문서 (관계도 · 컬럼 · 키 · 삭제 규칙)
├── plugin/              # Claude/Codex 플러그인 (MCP 연결 + olgae-planner 스킬)
│   ├── .claude-plugin/plugin.json
│   ├── .codex-plugin/plugin.json
│   ├── .mcp.json
│   └── skills/olgae-planner/SKILL.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py          # FastAPI 전체 (스키마 생성 + 마이그레이션 + API)
│   └── mcp_app.py       # /mcp HTTP MCP 서버 (main 의 핸들러를 재사용)
└── frontend/
    ├── Dockerfile
    ├── nginx.conf       # 정적 서빙 + /api 프록시
    ├── logo.svg
    └── index.html       # SPA 전체 (빌드 도구 없음)
```

DB 구조는 [`doc/ERD.md`](doc/ERD.md) 에 관계도와 컬럼 설명이 있습니다.

## 주의

데모 용도입니다. 외부에 공개하려면 최소한 아래를 먼저 확인하세요.

- `.env` 의 `POSTGRES_PASSWORD` 를 강한 값으로 (기본값 사용 금지)
- 앞단에 HTTPS 종료(리버스 프록시) — 세션 토큰이 평문으로 흐르지 않게
- 프록시를 더 앞에 둔다면 nginx 의 `X-Real-IP` 가 실제 클라이언트 IP 가 되게 맞출 것
  (아니면 로그인 잠금이 프록시 IP 하나로 뭉쳐 모든 사용자가 함께 잠깁니다)
- 신규 가입은 승인제를 유지하거나 관리자 페이지에서 차단
- `MCP_ALLOWED_HOSTS` 에 배포 도메인 지정 (비우면 Host 검사가 꺼집니다)
- 이미지는 URL 을 알면 인증 없이 열립니다(`/api/images/<id>`, id 는 128비트 난수)
- 업로드는 PNG·JPEG·GIF·WebP 만 받고 앞바이트로 검증합니다(SVG 는 스크립트를 품을 수 있어 거부).
  프로필 이미지(data URL)도 base64 이미지 형식만 허용합니다
- nginx 가 `X-Content-Type-Options: nosniff` · `X-Frame-Options: DENY` ·
  `Referrer-Policy: no-referrer` 를 붙입니다. CSP 는 인라인 핸들러가 많아 아직 없습니다
- DB 백업 없음
