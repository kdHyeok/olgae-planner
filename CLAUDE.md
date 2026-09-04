# CLAUDE.md

얼개 플래너 — PRD & 기능명세서 관리 서비스. Docker Compose 로 `frontend`(nginx + `index.html` 하나) ·
`backend`(FastAPI + `main.py` 하나) · `db`(PostgreSQL 16) 를 띄운다.

- 기능·API 목록: [`README.md`](README.md)
- DB 구조: [`doc/ERD.md`](doc/ERD.md)
- 문서 내용 작성 규칙: [`plugin/skills/olgae-planner/SKILL.md`](plugin/skills/olgae-planner/SKILL.md)
  — PRD·기능명세서 본문을 쓰거나 고칠 때(MCP 툴 사용 포함) 이 규칙을 따른다.

## DB 를 바꿀 때

1. **먼저 [`doc/ERD.md`](doc/ERD.md) 를 읽는다.**
2. `init_db()` 는 기동마다 실행되니 **멱등**하게 쓴다 —
   `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`.
   컬럼 삭제·타입 변경은 이 방식으로 안 되니 조건부로 쓰고 이유를 문서에 남긴다.
3. **바꾼 뒤 같은 작업 안에서 [`doc/ERD.md`](doc/ERD.md) 를 갱신한다.**
   관계도 · 삭제 규칙 · 테이블 상세 표 · 문자열 참조 · 인덱스. 새 컬럼에는 한글 이름을 붙이고,
   행(데이터) 값은 적지 않는다. API 필드가 바뀌면 `README.md` 의 API 표와
   `backend/mcp_app.py`(핸들러를 재사용하는 /mcp MCP 서버)도 함께 확인한다.

4. 실제 DB 와 문서가 맞는지 확인한다:
   `docker compose exec -T db psql -U app -d app -c "\dt" -c "\d+ <테이블>"`

본문 문법(용어 백틱·링크·이미지)이나 툴 구성을 바꾸면
`plugin/skills/olgae-planner/SKILL.md` 도 함께 고친다.

FK 없이 본문 텍스트로만 이어지는 관계(이미지 `![](/api/images/<id>)`, 용어 `` `용어` ``)가 있다.
관련 로직을 바꿀 때 함께 확인한다.

## 작업 규칙

- 배포: `docker compose up -d --build <service>` → 브라우저에서 직접 확인. 프론트는 빌드 없는 정적 파일.
- 검증용 데이터(노드·이미지·용어·버전·프로젝트)는 끝나면 원복한다.
  실제 사용 중인 프로젝트에서 파괴적 동작(정리·복원·삭제)을 시험하지 않는다.
- `alert`/`confirm`/`prompt` 금지 — 안내는 `toast()`, 확인은 두 번 클릭(`twoStep`).
- 커밋·푸시는 요청받을 때만 한다.
