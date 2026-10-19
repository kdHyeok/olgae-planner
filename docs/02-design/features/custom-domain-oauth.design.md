# 새 운영 도메인 OAuth·플러그인 연동 설계

> Feature: `custom-domain-oauth`
>
> Version: 1.0.0 | Date: 2026-10-19 | Status: Ready for implementation
>
> Level: Dynamic
>
> Plan: [`custom-domain-oauth.plan.md`](../../01-plan/features/custom-domain-oauth.plan.md)

## 1. 설계 요약

### 1.1 목표

`https://prd.donyk.link`를 웹·Google 로그인·MCP OAuth의 단일 canonical origin으로 만든다.
외부 URL은 모두 검증된 `PUBLIC_URL`에서 파생하고, 플러그인 기본 URL과 운영 설정도 같은 값으로 맞춘다.

### 1.2 핵심 결정

| ID | 결정 |
|---|---|
| D-01 | 운영 issuer는 한 시점에 하나만 제공하며 새 도메인으로 hard cutover한다. |
| D-02 | `PUBLIC_URL`을 시작 시 검증·정규화하고 OAuth issuer/resource/endpoint 및 Google callback의 단일 기준으로 사용한다. |
| D-03 | 외부 요청의 Host를 그대로 callback으로 조립하지 않고 canonical origin과 일치할 때만 허용한다. |
| D-04 | MCP 클라이언트 등록은 현재 DCR 방식을 유지하고 PKCE `S256`, token auth `none`을 유지한다. |
| D-05 | RFC 9207의 `authorization_response_iss_parameter_supported`는 이번 범위에서 광고하지 않는다. 모든 성공·오류 응답에 `iss`를 보장하기 전에는 켜지 않는다. |
| D-06 | 이전 resource의 access/refresh token은 새 resource에서 거부하고 사용자에게 재연결을 요구한다. API 토큰은 유지한다. |
| D-07 | DB 스키마는 바꾸지 않고 이전 OAuth 행은 롤백 관찰 기간 동안 보존한다. |

## 2. 아키텍처

### 2.1 구성

```text
ChatGPT / Codex / Claude
        │ HTTPS: https://prd.donyk.link/mcp
        ▼
외부 TLS·reverse proxy
        │ 127.0.0.1:3000
        ▼
frontend nginx
  ├─ /mcp, /authorize, /token, /register, /revoke
  ├─ /.well-known/oauth-*
  ├─ /oauth/*
  └─ /api/auth/google/*
        ▼
FastAPI + MCP ASGI app
        │
        ├─ Google OAuth 2.0 / OIDC
        └─ PostgreSQL OAuth client/request/code/token
```

### 2.2 canonical origin

`PUBLIC_URL=https://prd.donyk.link`를 다음 규칙으로 검증한다.

- scheme은 운영에서 `https`여야 한다. 개발 예외는 `http://localhost:3000`과 `http://127.0.0.1:3000`만 허용한다.
- host가 반드시 있어야 하며 userinfo, query, fragment는 금지한다.
- path는 비어 있거나 `/`만 허용하고 내부 저장값은 trailing slash 없이 정규화한다.
- 파생값:
  - `PUBLIC_ORIGIN = https://prd.donyk.link`
  - `PUBLIC_HOST = prd.donyk.link`
  - `OAUTH_RESOURCE = https://prd.donyk.link/mcp`
  - `GOOGLE_CALLBACK = https://prd.donyk.link/api/auth/google/callback`

잘못된 값은 조용히 localhost로 fallback하지 않고 백엔드 시작을 실패시킨다.

### 2.3 Google 로그인 origin 판정

`google_redirect_uri(request)`는 아래 순서로 동작한다.

1. 요청 Host의 대소문자를 정규화하고 기본 HTTPS 포트 `:443`만 같은 origin으로 취급한다.
2. Host가 `PUBLIC_HOST`와 일치하면 `PUBLIC_ORIGIN + /api/auth/google/callback`을 반환한다.
3. 개발 환경에서 Host가 `localhost:3000`이면 localhost callback을 반환한다.
4. `Origin` 헤더가 있으면 위에서 선택한 origin과 exact match인지 추가 검증한다.
5. 그 외 Host, 임의 포트, forwarded host 조작은 HTTP 400으로 거부한다.

프록시는 기존처럼 원본 `Host`를 백엔드에 전달한다. `X-Forwarded-Host`는 신뢰 기준으로 사용하지 않는다.

### 2.4 MCP OAuth discovery

| 공개 경로 | 필수 값 |
|---|---|
| `GET /.well-known/oauth-protected-resource/mcp` | `resource=https://prd.donyk.link/mcp`, `authorization_servers=[https://prd.donyk.link]` |
| `GET /.well-known/oauth-protected-resource` | 위와 같은 문서 |
| `GET /.well-known/oauth-authorization-server` | 새 issuer와 아래 endpoint 목록 |
| `GET /mcp` (무인증) | 401 + 새 도메인의 `resource_metadata` challenge |

OAuth metadata endpoint는 다음 값을 `PUBLIC_ORIGIN`에서 파생한다.

```json
{
  "issuer": "https://prd.donyk.link",
  "authorization_endpoint": "https://prd.donyk.link/authorize",
  "token_endpoint": "https://prd.donyk.link/token",
  "registration_endpoint": "https://prd.donyk.link/register",
  "revocation_endpoint": "https://prd.donyk.link/revoke",
  "token_endpoint_auth_methods_supported": ["none"],
  "code_challenge_methods_supported": ["S256"],
  "scopes_supported": ["mcp"]
}
```

### 2.5 외부 MCP OAuth 흐름

```text
1. Host ─GET /mcp──────────────────────────────▶ 401 + resource_metadata
2. Host ─GET protected-resource metadata──────▶ resource + authorization server
3. Host ─GET authorization-server metadata────▶ endpoints + DCR + PKCE 정보
4. Host ─POST /register────────────────────────▶ public client_id
5. Host ─GET /authorize(resource, PKCE, state)─▶ /oauth/login?request=...
6. User ─Google 또는 로컬 로그인───────────────▶ 승인 완료
7. Server ─code,state──────────────────────────▶ DCR에 등록된 ChatGPT callback
8. Host ─POST /token(code, verifier, resource)─▶ access + refresh token
9. Host ─Bearer access token /mcp──────────────▶ MCP tool 호출
```

Google 로그인은 6번 안에서 실행되는 별도 OAuth 거래다. Google state/nonce/PKCE와 외부 MCP의
state/code challenge를 섞지 않는다.

## 3. 데이터와 마이그레이션

### 3.1 DB 스키마

변경 없음. 기존 `oauth_clients`, `oauth_requests`, `oauth_codes`, `oauth_tokens` 구조를 유지한다.
따라서 `docs/ERD.md` 구조 변경도 필요 없다.

### 3.2 기존 데이터 정책

| 데이터 | 전환 후 처리 |
|---|---|
| `oauth_clients` | 보존. 새 ChatGPT 연결은 DCR로 새 client를 만들 수 있다. |
| 만료 전 `oauth_requests` | 최대 10분 후 만료. 전환 시 완료를 보장하지 않는다. |
| 만료 전 `oauth_codes` | 최대 5분 후 만료. 전환 시 재시작한다. |
| 이전 resource의 access token | `lookup_token_user`의 resource exact match로 거부한다. |
| 이전 resource의 refresh token | 조회/교환 시 현재 `OAUTH_RESOURCE`와 일치하는 행만 허용하도록 강화한다. |
| API token `olg_…` | resource와 무관하므로 유지한다. |

이전 OAuth 행은 즉시 삭제하지 않는다. 배포 안정화와 롤백 관찰 기간 7일 후, DB 백업이 확인된 경우에만
별도 운영 작업으로 정리한다.

## 4. 파일별 변경 설계

| 파일 | 변경 |
|---|---|
| `backend/main.py` | `PUBLIC_URL` 검증·정규화, canonical host 파생, Google callback allowlist를 새 기준으로 구성 |
| `backend/mcp_app.py` | refresh token 조회/교환에 현재 resource exact match 추가, metadata 파생값 확인 |
| `backend/test_google_auth.py` | 새 운영 Host, `:443`, Origin 일치, 악성 Host/포트 거부 검사 |
| `backend/test_oauth.py` | 새 resource/issuer/endpoint, 401 challenge, 이전 resource refresh 거부 검사 |
| `plugin/.mcp.json` | 기본 URL을 `https://prd.donyk.link/mcp`로 변경 |
| `plugin/.claude-plugin/plugin.json` | 인라인 MCP 기본 URL을 같은 값으로 변경 |
| `frontend/test_auth_modal.mjs` | 두 플러그인 설정의 새 URL 및 동기화 검사 |
| `.env.example` | 새 `PUBLIC_URL`, 새 운영 host 예시와 localhost 설명 |
| `README.md` | Google callback, MCP 설치, 도메인 전환·재연결·검증 절차 |
| `plugin/README.md` | 기본 서버 URL과 ChatGPT/Codex/Claude 재연결 안내 |

`docker-compose.yml`은 이미 값을 환경변수로 전달하므로 동작 변경은 없다. 주석만 필요하면 새 canonical origin
개념에 맞춘다.

## 5. 플러그인 연결 설계

### 5.1 저장소 플러그인

- Claude/Codex 기본 MCP URL은 `https://prd.donyk.link/mcp`로 변경한다.
- `OLGAE_URL` override는 자체 배포 사용자를 위해 유지한다.
- `.claude-plugin/plugin.json`과 `.mcp.json`은 테스트로 동일 URL을 보장한다.
- 플러그인 버전 정책이 현재 수동이면 patch version 증가 여부를 구현 시 기존 릴리스 관례로 결정한다.

### 5.2 ChatGPT 등록 연결

ChatGPT에 저장된 `plugin_asdk_app...` 연결은 저장소 manifest 변경만으로 서버 URL이 자동 변경된다고 가정하지 않는다.

1. 백엔드 cutover와 discovery 검증을 먼저 완료한다.
2. ChatGPT 플러그인 관리 화면에서 MCP server URL을 `https://prd.donyk.link/mcp`로 갱신한다.
3. 수정이 지원되지 않거나 기존 DCR 등록이 고정돼 있으면 새 custom MCP server를 만든다.
4. 인증은 OAuth, client registration은 DCR을 사용한다.
5. 새 연결을 승인하고 scan/tool 호출이 성공한 뒤 이전 연결을 제거한다.

공개 플러그인 패키지를 업로드하는 흐름이라면 `mcp.json`의 server URL을 새 도메인으로 갱신한 새 버전을 업로드하고,
저장된 연결 설정이 실제로 교체됐는지 관리 화면에서 확인한다.

## 6. 구현 순서

1. `PUBLIC_URL` 검증 및 Google callback 파생 로직 구현
2. 이전 resource refresh token 거부 로직 구현
3. 백엔드 OAuth·Google 회귀 테스트 갱신
4. 플러그인 MCP URL과 프론트 정적 테스트 갱신
5. 샘플 환경변수와 운영 문서 갱신
6. 로컬 Compose 전체 OAuth smoke test
7. 운영 DB 백업 및 `.env` cutover
8. 백엔드/프론트 재배포, 공개 endpoint 검증
9. ChatGPT 플러그인 연결 갱신 또는 재생성
10. Google 로그인과 실제 MCP tool 호출 검증

## 7. 테스트 설계

### 7.1 정적·단위 테스트

| 케이스 | 기대 결과 |
|---|---|
| `PUBLIC_URL=https://prd.donyk.link` | 정규화된 canonical origin 생성 |
| trailing slash | 제거 후 동일 값 |
| path/query/fragment/userinfo 포함 | 시작 실패 |
| 운영 `http` URL | 시작 실패 |
| Host `prd.donyk.link` | 새 Google callback 반환 |
| Host `prd.donyk.link:443` | 새 Google callback 반환 |
| Host `evil.example` 또는 임의 포트 | HTTP 400 |
| Origin이 canonical과 다름 | HTTP 400 |
| plugin 두 설정 파일 | 모두 새 URL, Authorization header 없음 |

### 7.2 통합 테스트

- `python backend/test_google_auth.py`
- `python backend/test_oauth.py`
- `node --test frontend/test_auth_modal.mjs`
- Docker 이미지 빌드와 `git diff --check`
- DCR → 승인 → code 교환 → MCP initialize/tools → refresh → revoke 전체 흐름
- 이전 resource로 발급된 OAuth access/refresh token이 새 resource에서 거부되는지 확인
- API token으로 `/mcp` 호출이 계속 성공하는지 확인

### 7.3 운영 smoke test

```text
GET https://prd.donyk.link/                                      -> 200
GET https://prd.donyk.link/.well-known/oauth-protected-resource/mcp -> 200, 새 resource
GET https://prd.donyk.link/.well-known/oauth-authorization-server   -> 200, 새 issuer/endpoints
GET https://prd.donyk.link/mcp                                  -> 401, 새 challenge
Google 로그인 시작/콜백                                         -> 성공
ChatGPT list_projects                                           -> 성공
```

응답 본문과 헤더에서 `prd.donhse.duckdns.org`가 한 번도 나타나지 않아야 한다.

## 8. 배포와 롤백

### 8.1 배포

1. PostgreSQL `pg_dump`를 호스트의 백업 경로에 저장하고 복구 가능 여부를 확인한다.
2. Google Cloud에 새 callback이 등록된 상태를 확인한다. 이전 callback은 안정화까지 유지한다.
3. 서버 `.env`를 다음처럼 변경한다.

```dotenv
PUBLIC_URL=https://prd.donyk.link
MCP_ALLOWED_HOSTS=prd.donyk.link,localhost:3000,127.0.0.1:3000
```

4. `docker compose up -d --build backend frontend`로 재배포한다.
5. discovery·Google·OAuth smoke test가 모두 통과한 뒤 ChatGPT 연결 URL을 전환한다.
6. 24시간 로그를 관찰하고 안정화 후 이전 Google callback과 이전 연결 제거를 검토한다.

### 8.2 롤백

- 이전 이미지와 이전 `.env`의 `PUBLIC_URL`, `MCP_ALLOWED_HOSTS`로 되돌린다.
- DB 스키마 변경이 없으므로 DB restore는 하지 않는다.
- 새 도메인에서 발급된 OAuth token은 이전 resource에서 유효하지 않으므로 롤백 후에도 재연결이 필요하다.
- Google Cloud의 이전 callback은 롤백 관찰 기간 동안 제거하지 않는다.

## 9. 보안 검토

- Host header를 callback URL 생성에 직접 신뢰하지 않는다.
- OAuth issuer/resource/callback은 exact match로 검증한다.
- DCR은 HTTPS redirect URI만 허용하고 fragment·userinfo를 거부하는 기존 정책을 유지한다.
- PKCE verifier, state, nonce의 일회성·만료 정책을 유지한다.
- Google client secret, DB 비밀번호, OAuth token 원문을 로그·문서·커밋에 남기지 않는다.
- 이전 resource refresh token이 새 도메인 token으로 승격되지 않도록 resource 필터를 추가한다.
- `authorization_response_iss_parameter_supported`는 실제 모든 응답에 `iss`를 넣기 전에는 선언하지 않는다.

## 10. 구현 완료 조건

- 계획 문서의 성공 기준 전부 충족
- 전체 회귀 테스트와 운영 smoke test 통과
- ChatGPT 실제 연결에서 OAuth 승인 후 MCP tool 호출 성공
- 새 discovery 및 로그에 이전 도메인 잔존 없음
- 사용자 재연결 절차와 롤백 절차 문서화
