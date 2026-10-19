# 새 운영 도메인 OAuth·플러그인 연동 계획

> Feature: `custom-domain-oauth`
>
> Version: 1.0.0 | Date: 2026-10-19 | Status: Approved for design
>
> Level: Dynamic

## 1. 개요

### 1.1 목적

서비스의 정식 운영 origin을 `https://prd.donhse.duckdns.org`에서
`https://prd.donyk.link`로 전환하고, 웹 Google 로그인과 ChatGPT·Codex·Claude용
MCP OAuth 2.1 연결이 새 도메인을 하나의 신뢰 기준으로 사용하도록 맞춘다.

### 1.2 현재 상태

- `https://prd.donyk.link/`는 HTTPS로 200을 반환해 DNS·TLS·리버스 프록시는 연결돼 있다.
- 실행 중 백엔드의 `PUBLIC_URL`과 `MCP_ALLOWED_HOSTS`는 이전 도메인이다.
- 새 도메인에서 읽은 OAuth discovery도 이전 `resource`, `issuer`, endpoint를 광고한다.
- Google 로그인 허용 origin은 코드에서 이전 운영 도메인과 localhost만 허용한다.
- 플러그인 기본 MCP URL, 샘플 환경변수, 테스트와 문서에 이전 도메인이 남아 있다.
- DB에는 DCR 클라이언트 3개와 이전 resource에 묶인 OAuth 토큰 6개가 있다.

## 2. 목표

### 2.1 주요 목표

- [ ] `https://prd.donyk.link`를 유일한 운영 `PUBLIC_URL`로 사용한다.
- [ ] MCP resource를 `https://prd.donyk.link/mcp`로 고정한다.
- [ ] 보호 리소스·OAuth discovery·401 challenge가 모두 새 도메인을 광고한다.
- [ ] Google OAuth callback을 `https://prd.donyk.link/api/auth/google/callback`로 사용한다.
- [ ] ChatGPT/Codex 플러그인 기본 MCP URL을 새 도메인으로 바꾼다.
- [ ] DCR + Authorization Code + PKCE(S256) + refresh/revoke 흐름을 회귀 검증한다.
- [ ] 기존 연결이 왜 재인증되어야 하는지 운영 절차에 명시한다.

### 2.2 비목표

- Sign in with ChatGPT 도입 또는 Google 외 신규 IdP 추가
- OAuth 토큰 형식이나 DB 스키마 변경
- 여러 운영 도메인을 동시에 issuer/resource로 제공하는 멀티테넌트 구조
- API 토큰(`olg_…`) 폐기 또는 재발급
- 리버스 프록시 제품 교체

## 3. 범위

### 3.1 코드·설정

- `backend/main.py`: 운영 origin 검증과 Google callback 계산
- `backend/mcp_app.py`: `PUBLIC_URL` 기반 issuer/resource/discovery 일관성 확인
- `.env.example`, `docker-compose.yml`: 새 운영값과 배포 지침
- `plugin/.mcp.json`, `plugin/.claude-plugin/plugin.json`: 기본 MCP URL 변경
- `backend/test_google_auth.py`, `backend/test_oauth.py`, `frontend/test_auth_modal.mjs`: 회귀 테스트
- `README.md`, `plugin/README.md`: 설치·재연결·검증 절차

### 3.2 운영

- 배포 서버 `.env`의 `PUBLIC_URL`과 `MCP_ALLOWED_HOSTS` 변경
- Google Cloud Console의 정확한 callback 등록 상태 확인
- 백엔드 재생성 후 discovery 및 전체 OAuth smoke test
- ChatGPT 플러그인/MCP 서버 URL을 새 도메인으로 갱신하고 OAuth 재연결
- 기존 도메인은 OAuth issuer/resource로 더 이상 광고하지 않음

## 4. 요구사항

### 4.1 기능 요구사항

| ID | 요구사항 |
|---|---|
| FR-01 | 모든 외부 OAuth URL은 검증된 `PUBLIC_URL`에서 파생한다. |
| FR-02 | 새 Host에서 Google 로그인을 시작하면 새 callback URI를 Google에 전달한다. |
| FR-03 | 임의 Host/Origin은 Google callback 생성에 사용할 수 없다. |
| FR-04 | MCP 비인증 응답은 새 도메인의 protected-resource metadata URL을 광고한다. |
| FR-05 | protected-resource metadata의 `resource`와 `authorization_servers`는 각각 새 MCP URL과 새 issuer여야 한다. |
| FR-06 | OAuth metadata의 issuer와 authorize/token/register/revoke endpoint는 새 도메인이어야 한다. |
| FR-07 | `resource`는 authorization·token·refresh 과정에서 정확히 일치해야 한다. |
| FR-08 | 플러그인 기본 설치는 별도 환경변수 없이 새 MCP URL을 사용한다. |
| FR-09 | 이전 도메인 OAuth 토큰은 새 resource에서 인증되지 않아야 한다. |

### 4.2 비기능 요구사항

- 운영 origin은 HTTPS만 허용하고 경로·쿼리·fragment·userinfo를 허용하지 않는다.
- OAuth callback, issuer, resource 비교는 문자열 exact match를 유지한다.
- PKCE는 `S256`만 광고하고 공개 클라이언트의 token auth method는 `none`을 유지한다.
- Client secret과 실제 `.env`는 저장소에 커밋하지 않는다.
- DB 데이터와 프로젝트 콘텐츠는 도메인 전환 중 보존한다.
- 실패 시 이전 이미지와 이전 `.env`로 복구할 수 있어야 한다.

## 5. 성공 기준

- [ ] 새 도메인 앱과 OAuth well-known endpoint가 모두 HTTP 200이다.
- [ ] `/mcp` 비인증 호출은 HTTP 401이며 challenge URL이 새 도메인이다.
- [ ] 두 discovery 문서 어디에도 이전 도메인이 나타나지 않는다.
- [ ] Google 로그인 요청의 `redirect_uri`가 등록된 새 callback과 정확히 일치한다.
- [ ] DCR, 승인, code 교환, MCP initialize/tools, refresh, revoke smoke test가 통과한다.
- [ ] ChatGPT에서 새 플러그인 연결 후 `list_projects`가 성공한다.
- [ ] Codex/Claude 플러그인 기본 설정이 새 MCP URL을 사용한다.
- [ ] API 토큰 기반 MCP 연결은 그대로 작동한다.
- [ ] 백엔드·nginx 로그에 5xx와 OAuth 오류가 없다.

## 6. 실행 순서

| 단계 | 내용 | 중단 조건 |
|---|---|---|
| 1 | 코드·테스트·문서에서 canonical origin 단일화 | 단위/정적 테스트 실패 |
| 2 | 새 도메인 discovery를 로컬 Compose에서 검증 | issuer/resource 불일치 |
| 3 | DB 백업 후 `.env` 운영값 변경 | 백업 실패 |
| 4 | 백엔드·프론트 재배포 및 HTTP smoke test | 5xx 또는 health 실패 |
| 5 | Google 로그인과 MCP OAuth 전체 흐름 검증 | callback/PKCE/token 실패 |
| 6 | ChatGPT 플러그인 서버 URL 갱신·재연결 | 스캔 또는 연결 실패 |
| 7 | 이전 도메인 광고 제거 확인 및 관찰 | 오류율 증가 |

## 7. 사용자·운영자 작업

1. Google Cloud Console에 `https://prd.donyk.link/api/auth/google/callback`가 정확히 등록됐는지 재확인한다.
2. 배포 서버 `.env`를 새 도메인으로 변경한다. 비밀값은 바꾸거나 출력하지 않는다.
3. ChatGPT의 MCP 서버/플러그인 등록 URL을 `https://prd.donyk.link/mcp`로 바꾸고 연결을 다시 승인한다.
4. 기존 OAuth 연결은 옛 resource에 묶여 있으므로 재연결한다. API 토큰 연결은 유지 가능하다.

## 8. 위험과 완화

| 위험 | 영향 | 완화 |
|---|---|---|
| metadata가 이전 도메인을 계속 광고 | ChatGPT callback 또는 token 교환 실패 | 배포 전후 well-known JSON exact 검증 |
| 기존 refresh token이 옛 resource를 재발급 | 잘못된 audience 유지 | 새 resource에서 이전 토큰 거부, 사용자 재연결 |
| Google callback 불일치 | Google 400 `redirect_uri_mismatch` | 코드·Google Console 값을 exact match로 검증 |
| Host allowlist 누락 | MCP 400/403 또는 DNS rebinding 검사 실패 | `MCP_ALLOWED_HOSTS`에 새 host와 로컬 테스트 host 지정 |
| 기존 플러그인 연결 캐시 | 새 manifest 배포 후에도 옛 URL 사용 | 연결 삭제/재생성 또는 새 MCP 등록 후 재승인 |
| 롤백 시 issuer/resource 재변경 | 새 토큰이 즉시 무효화 | 롤백을 짧게 제한하고 재연결 공지, DB 삭제는 하지 않음 |

## 9. 참고

- [OpenAI Plugins authentication](https://developers.openai.com/plugins/build/auth)
- [OpenAI plugin MCP packaging](https://developers.openai.com/plugins/build/plugins)
- `README.md`의 MCP 서버·Google 로그인 운영 지침
- `docs/ERD.md`의 OAuth client/request/code/token 구조
