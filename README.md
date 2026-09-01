# PRD & 기능명세서 관리 데모

제품 PRD 문서와 기능명세서(계층형 기능 트리)를 웹에서 **수정·추가·삭제**할 수 있는 데모 서비스입니다.
기능명세서는 **트리 뷰**(가로형 마인드맵, 곡선 연결선)와 **디렉토리 뷰**(목록 + 문서 상세) 두 가지로 볼 수 있습니다.

## 주요 기능

- **PRD 탭**: 마크다운 문서 보기/편집/저장
- **기능명세서 탭**
  - 트리 뷰: PRD 루트에서 대분류 → 상세 기능으로 뻗는 마인드맵, 대분류별 색상 구분
  - 디렉토리 뷰: 좌측 번호 목록 + 우측 문서형 상세
  - 항목 추가(대분류/하위), 제목·상태·중요도·설명(마크다운) 편집, 삭제(하위 포함 연쇄 삭제)
  - **드래그 & 드롭**: 카드를 다른 카드 박스 위에 드롭 → 그 하위로 이동. 트리 뷰의 `PRD` 루트 카드(또는 디렉토리 뷰 목록 빈 곳)에 드롭 → 대분류로 승격. 자기 하위로의 순환 이동은 차단
  - **▲▼ 버튼**: 같은 부모 안에서 순서 변경

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

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET / PUT | `/api/prd` | PRD 문서 조회/저장 (`{content}`) |
| GET | `/api/nodes` | 전체 기능 노드 목록 (flat, 프론트에서 트리 구성) |
| POST | `/api/nodes` | 노드 생성 (`{parent_id, title}`) |
| PUT | `/api/nodes/{id}` | 부분 수정 (`title/description/status/importance/sort_order/parent_id`) — `parent_id` 변경 시 순환 이동은 400 |
| DELETE | `/api/nodes/{id}` | 삭제 (하위 노드 연쇄 삭제) |

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
