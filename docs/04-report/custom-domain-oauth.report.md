# custom-domain-oauth 배포 기록

> 2026-10-19 | 상태: 서버 구현·배포 및 Google 인증 시작 검증 완료, 사용자 로그인·플러그인 재연결 대기

## 배포 내용

- 운영 origin: `https://prd.donyk.link`
- MCP resource: `https://prd.donyk.link/mcp`
- Google callback: `https://prd.donyk.link/api/auth/google/callback`
- `.env`의 `PUBLIC_URL`, `MCP_ALLOWED_HOSTS` 변경 후 backend/frontend 재생성.
- 요청 헤더를 Google callback 주소로 직접 사용하지 않도록 origin 검증 강화.
- 기존 domain의 인증 코드·access·refresh token을 새 resource에서 거부.
- 플러그인 기본 URL 변경, plugin version 0.1.2.
- DB 스키마와 기존 콘텐츠 데이터는 변경하지 않음. 테스트 사용자·DCR 등록값·임시 state는 정리.

## 검증

검증 근거 및 미완료 항목은 [설계 대비 검증](../03-analysis/custom-domain-oauth.analysis.md)에 기록했다.
자동 테스트는 Google 외부 token 응답을 mock한 callback 회귀 검사와 실제 공개 HTTPS MCP 전체 흐름을 포함한다.
실제 Google 서버는 최초 `redirect_uri_mismatch`를 반환했으나 등록 확인 후 재검증에서 로그인 페이지를
정상 표시했다. 실제 사용자 계정 로그인 완료까지 검증한 것으로 보고하지 않는다.
현재 설치된 ChatGPT 연결의 실제 도구 호출도 재승인 후 확인해야 한다.

## 백업과 복구

- 백업 경로: `.deployment-backups/donyk-20261019/`
- `database.dump`: PostgreSQL custom-format dump. 별도 DB에 실제 복원 확인.
- `env.before`: 이전 환경설정. 비밀값 포함 가능, 권한 600.
- 백업 디렉터리는 Git에서 제외했다. 원문 데이터·비밀값은 문서에 기록하지 않는다.
- 이전 이미지: `prd-spec-demo-backend:before-donyk-20261019`,
  `prd-spec-demo-frontend:before-donyk-20261019`.

롤백이 필요하면 `env.before`를 `.env`로 복원하고 이전 이미지 태그를 backend/frontend에 적용해 재생성한다.
스키마 변경이 없으므로 DB 복원은 필요하지 않다. 도메인 전환 시 OAuth 연결은 재승인이 필요하다.
보존된 이전 Google callback과 이전 OAuth 행은 이번 작업에서 삭제하지 않았다.

## 운영자가 마무리할 사항

1. Google 로그인 화면에서 계정 선택·동의를 완료하고 최종 callback이 정상 동작하는지 확인.
2. ChatGPT 플러그인의 MCP URL을 `https://prd.donyk.link/mcp`로 갱신하고 재승인.
   URL 수정이 지원되지 않으면 새 custom MCP 연결을 만든 뒤 검증한다.
3. Google 로그인과 실제 플러그인 도구 호출이 성공하면 PDCA Check를 완료한다.

운영 배포 후 별도 요청에 따라 새 도메인 코드·플러그인 설정·회귀 테스트·설계 및 검증 문서를
하나의 커밋으로 반영한다. 실제 `.env`, DB 백업, 로컬 bkit 실행 상태는 커밋에서 제외한다.
