# PRD & 기능명세서 관리 데모

제품 PRD 문서와 기능명세서(계층형 기능 트리)를 웹에서 **수정·추가·삭제**할 수 있는 데모 서비스입니다.
기능명세서는 **트리 뷰**(가로형 마인드맵, 곡선 연결선)와 **디렉토리 뷰**(목록 + 문서 상세) 두 가지로 볼 수 있습니다.

## 주요 기능

- **PRD 탭**: 마크다운 문서 보기/편집/저장
- **기능명세서 탭**
  - 트리 뷰: PRD 루트에서 대분류 → 상세 기능으로 뻗는 마인드맵, 대분류별 색상 구분
  - 디렉토리 뷰: 좌측 번호 목록 + 우측 문서형 상세
  - 헤더는 아이콘 버튼(문서/홈/트리 뷰/디렉토리 뷰)으로 구성
  - 대분류 추가는 트리 끝에 연결된 반투명 `＋ 대분류 추가` 가지(디렉토리 뷰는 목록 하단 줄)를 클릭
  - 하위 항목 추가는 카드의 `＋`, 제목·설명은 클릭 후 그 자리에서 편집(마크다운), 삭제는 두 번 클릭 확인
  - **드래그 & 드롭**: 카드를 다른 카드 박스 위에 드롭 → 그 하위로 이동. 트리 뷰의 `PRD` 루트 카드(또는 디렉토리 뷰 목록 빈 곳)에 드롭 → 대분류로 승격. 자기 하위로의 순환 이동은 차단
  - **▲▼ 버튼**: 같은 부모 안에서 순서 변경
- **사용자 / 코멘트**
  - 사용자 이름 + 비밀번호로 회원가입/로그인 (PBKDF2 해시, DB 세션 토큰)
  - 로그인한 사용자는 각 기능 항목에 코멘트 작성 가능, 본인 코멘트만 삭제 가능
- **이미지**
  - 기능 설명·PRD 편집 중 이미지 붙여넣기(Ctrl+V), 끌어놓기, `이미지 추가` 버튼 지원
  - 이미지는 DB(`images` 테이블)에 저장되고 `![](/api/images/<id>)` 마크다운으로 본문에 삽입됨
  - 헤더 `⋯` 메뉴의 **미사용 이미지 정리**로 본문에서 참조하지 않는 이미지 삭제 (업로드 후 1시간 이내 이미지는 보호)
- **버전 기록 (기능명세서)**
  - 헤더 메뉴 → `기능명세서 버전 기록`에서 현재 트리 상태를 스냅샷으로 저장
  - 목록에 **저장 일시 · 저장한 사용자 · 항목 수** 표시, `불러오기`로 그 시점으로 복원(두 번 클릭 확인)
  - 복원 시 살아남는 항목은 id 를 유지해 해당 항목의 코멘트가 보존됨
- **내보내기**
  - 헤더 `⋯` 메뉴의 **마크다운으로 내보내기** → PRD + 기능명세서 전체를 `<프로젝트명>.md` 파일로 저장
  - 기능은 번호가 매겨진 헤딩(`### 1`, `#### 1.1`)과 상태·중요도 목록으로 출력, 이미지 주소는 절대경로로 변환
- **프로젝트**
  - 사용자별로 여러 프로젝트 생성/이름 변경/삭제 (PRD와 기능 트리는 프로젝트 단위)
  - 프로젝트 소유자만 접근 가능. 소유자가 **공유 링크**(`/?share=<token>`)를 생성하면 링크를 아는 누구나 열람·편집 가능, 링크 해제 시 즉시 차단
  - 구버전 DB(프로젝트 개념 이전 데이터)는 첫 기동 시 "기본 프로젝트"로 자동 마이그레이션

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
git clone <this-repo-url>
cd <repo-dir>
docker compose up --build -d
```

브라우저에서 **http://localhost:3000** 접속. 끝.

- 첫 기동 시 백엔드가 테이블을 만들고 샘플 PRD/기능 트리를 자동 시드합니다.
- 데이터는 `dbdata` 볼륨에 저장되어 컨테이너를 재시작해도 유지됩니다.

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
- DB 접속 정보: `docker-compose.yml`의 `POSTGRES_*` 환경변수와 `backend.environment.DATABASE_URL`을 함께 수정

## API

콘텐츠 API는 소유자 로그인(`Authorization: Bearer <token>`) 또는 유효한 공유 토큰(`?share=<token>`)이 필요합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / POST | `/api/projects` | 내 프로젝트 목록 / 생성 (`{name}`) — 로그인 필요 |
| PUT / DELETE | `/api/projects/{pid}` | 이름 변경 / 삭제 — 소유자만 |
| POST / DELETE | `/api/projects/{pid}/share` | 공유 링크 생성 / 해제 — 소유자만 |
| GET | `/api/shared/{token}` | 공유 토큰 → 프로젝트 정보 (공개) |
| GET / PUT | `/api/projects/{pid}/prd` | PRD 문서 조회/저장 (`{content}`) |
| GET / POST | `/api/projects/{pid}/nodes` | 기능 노드 목록 / 생성 (`{parent_id, title}`) |
| PUT | `/api/nodes/{id}` | 부분 수정 (`title/description/status/importance/sort_order/parent_id`) — 순환 이동·타 프로젝트 이동은 400 |
| DELETE | `/api/nodes/{id}` | 삭제 (하위 노드 연쇄 삭제) |
| POST | `/api/projects/{pid}/images` | 이미지 업로드 (원본 바이트 + `Content-Type: image/*`, 5MB 이하) → `{url}` |
| GET | `/api/images/{id}` | 업로드된 이미지 조회 |
| GET / POST | `/api/projects/{pid}/versions` | 버전 목록 / 현재 기능명세서 스냅샷 저장 (로그인 필요) |
| POST | `/api/versions/{vid}/restore` | 해당 버전으로 복원 (로그인 필요) |
| DELETE | `/api/versions/{vid}` | 버전 삭제 — 소유자만 |
| POST | `/api/projects/{pid}/images/cleanup` | 미참조 이미지 삭제 — 소유자만, 1시간 이내 업로드분 제외 → `{deleted, bytes}` |
| POST | `/api/auth/register` | 회원가입 (`{username, password}` → `{token, username}`) |
| POST | `/api/auth/login` | 로그인 (→ `{token, username}`) |
| POST | `/api/auth/logout` | 로그아웃 (Bearer 토큰) |
| GET | `/api/nodes/{id}/comments` | 노드 코멘트 목록 |
| POST | `/api/nodes/{id}/comments` | 코멘트 작성 (로그인 필요, `Authorization: Bearer <token>`) |
| DELETE | `/api/comments/{id}` | 본인 코멘트 삭제 (로그인 필요) |

## 프로젝트 구조

```
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py          # FastAPI 전체 (스키마 생성 + 시드 + API)
└── frontend/
    ├── Dockerfile
    ├── nginx.conf       # 정적 서빙 + /api 프록시
    └── index.html       # SPA 전체 (빌드 도구 없음)
```

## 주의

데모 용도입니다. 인증/권한, HTTPS, DB 백업이 없으므로 외부 공개 환경에 그대로 두지 마세요.
