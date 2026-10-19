# custom-domain-oauth 설계 대비 검증

> 2026-10-19 | 코드 구현 완료, 운영 검증 중 | PDCA Check

계획의 FR-01~FR-09는 코드에 모두 반영했다(9/9). Google 인증 시작은 실제 서버에서 통과했다.
실제 계정 로그인 완료 및 ChatGPT 연결 재승인은 남아 있어 전체 완료로 표시하지 않는다.

| 요구사항 | 구현·검증 |
|---|---|
| FR-01 단일 공개 origin | `normalize_public_url`로 HTTPS·host·포트·경로·userinfo 검증, canonical 값 파생 |
| FR-02 새 Google callback | 새 Host 및 기본 443 포트에서 새 callback 생성, 외부 Google 요청값 확인 |
| FR-03 Host·Origin 방어 | 잘못된 Host, Origin, 임의 포트, 이전 운영 Host 거부 검사 통과 |
| FR-04 MCP 401 discovery | 공개 HTTPS에서 새 `resource_metadata` URL 확인 |
| FR-05 protected resource | 두 well-known 경로 모두 새 resource·authorization server 반환 |
| FR-06 OAuth issuer·endpoint | issuer 및 authorize/token/register/revoke가 새 도메인임을 확인 |
| FR-07 resource 검증 | code 조회·교환과 refresh 조회·교환에 current resource 필터, 이전 토큰 거부 |
| FR-08 플러그인 기본 URL | Claude/Codex 매니페스트·테스트·문서 변경, plugin patch version 0.1.2 |
| FR-09 이전 토큰 거부 | 이전 access 조회 실패 및 이전 refresh 교환 `invalid_grant` 확인 |

## 테스트 결과

- Python 문법 검사와 `git diff --check`: 통과.
- `node --test frontend/test_auth_modal.mjs`: 통과.
- 격리 DB `test_google_auth.py`: Google 계정 연결·가입 승인·세션 저장 검사 통과.
- 격리 DB `test_domain_oauth.py`: 3개 테스트 통과. Google 외부 token 응답 및 서명 검증만 mock하고,
  실제 state·nonce·PKCE·DB·세션·Google 웹 callback·중첩 MCP callback 처리를 검증했다.
- 격리 nginx 경로 `test_oauth.py`: DCR→PKCE→MCP initialize/tools/list_projects→refresh→revoke 통과.
- 공개 `https://prd.donyk.link` 경로 `test_oauth.py`: 같은 전체 흐름 및 이전 resource 거부 통과.
- 실제 Chrome으로 새 도메인 앱 렌더링 확인.
- PostgreSQL dump 생성, 별도 `restorecheck` DB에 복원 성공.

## 외부 설정으로 남은 사항

1. 최초 실제 Google 인증 요청은 `400 redirect_uri_mismatch`였으나, 사용자의 등록 확인 후 재검증에서
   새 callback `https://prd.donyk.link/api/auth/google/callback`이 허용되고 Google 로그인 페이지를
   정상 표시했다. 설정 전파 지연 가능성이 있으나 원인은 단정하지 않는다.
   실제 Google 계정 선택·동의 및 최종 callback 수신은 사용자 브라우저에서 확인해야 한다.
2. 기존 연결된 Olgae-PRD 플러그인 `list_projects` 호출은 connector internal error로 실패했다.
   새 공개 도메인에서 독립 MCP 호출은 성공한다. 저장된 연결을 새 URL로 갱신하고 재승인한 다음 재검증한다.
   기존 연결 오류의 내부 원인은 connector가 공개하지 않아 단정하지 않는다.

## 설계에서 보완한 내용

- 인증 코드도 이전 resource의 교환을 거부하도록 보강했다.
- MCP `allowed_origins`는 Host 문자열 대신 scheme이 있는 Origin으로 구성한다.
  새 도메인의 Origin 헤더를 포함한 실제 MCP 요청으로 통과를 확인했다.
- 공개 테스트에서 urllib 기본 User-Agent는 Cloudflare `403 / 1010`을 받았다.
  서비스에서 이미 사용하는 httpx로 테스트를 실행해 전체 흐름을 확인했다. WAF 정책은 변경하지 않았다.

## 기존 코드에서 확인한 별도 문제

빈 DB 기동 시 기존 `init_db`가 `projects` 생성 전에 참조해 실패한다.
이번 운영 DB는 기존 스키마가 있어 영향이 없으며, 격리 테스트에는 운영 스키마만 복제했다.
이 문제를 고친 것으로 간주하지 않는다.

## 다음 검증

- Google 인증 시작은 통과했으며 실제 Google 계정 로그인 완료 및 callback 확인이 남았다.
- 새 MCP URL로 ChatGPT 연결을 재승인한 뒤 실제 플러그인 `list_projects` 확인.
- 위 두 조건이 충족되기 전까지 PDCA Check를 완료하지 않는다.
