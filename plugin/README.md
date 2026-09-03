# prd-spec 플러그인

PRD & 기능명세서 서비스를 AI 에이전트에 붙이는 플러그인. 두 가지가 들어 있다.

- **MCP 서버 연결** — 배포 서버의 `/mcp` 엔드포인트(툴 13개: 명세 조회·수정, 용어 사전, 버전, 코멘트)
- **스킬** `prd-spec` — 이 서비스의 작성 컨벤션과 산출물 규칙([skills/prd-spec/SKILL.md](skills/prd-spec/SKILL.md))

## 준비: 토큰과 주소

서비스에 로그인한 뒤 헤더 메뉴 → **MCP 연결** 에서 토큰을 확인하거나, 직접 발급한다.

```bash
curl -s -X POST https://<호스트>/api/auth/login   -H "Content-Type: application/json" -d '{"username":"<계정>","password":"<비밀번호>"}'
```

환경변수로 둔다. 설정 파일에 토큰을 적지 않아도 된다.

```bash
export PRDSPEC_URL=https://<호스트>/mcp     # 생략하면 http://localhost:3000/mcp
export PRDSPEC_TOKEN=<세션 토큰>
```

Windows PowerShell:

```powershell
$env:PRDSPEC_URL  = "https://<호스트>/mcp"
$env:PRDSPEC_TOKEN = "<세션 토큰>"
```

## Claude Code

```bash
claude plugin marketplace add kdHyeok/prd-spec-demo
claude plugin install prd-spec@prd-spec-demo
```

마켓플레이스 목록은 저장소 루트의 `.claude-plugin/marketplace.json` 이다.
저장소를 클론해 뒀다면 그 경로로 바로 등록할 수 있다 (`.` 은 안 되고 `./` 형태로 준다).

```bash
claude plugin marketplace add ./          # 클론한 저장소 루트에서
claude plugin install prd-spec@prd-spec-demo
```

등록 뒤 Claude Code 를 재시작하고 `/mcp` 로 연결(`plugin:prd-spec:prd-spec`),
`/plugin` 으로 스킬 `prd-spec` 을 확인한다.

> `claude mcp add` 로 같은 이름(`prd-spec`)을 이미 등록해 뒀다면 그쪽이 플러그인 설정을 가린다.
> 플러그인 쪽을 쓰려면 수동 등록을 지운다: `claude mcp remove prd-spec`.
> 목록에 `Connected` 로 떠도 토큰 검사는 통과한 게 아니다(연결 단계에는 인증이 필요 없다).
> 실제 권한은 툴을 한 번 호출해 봐야 알 수 있다.

## Codex

`.codex-plugin/plugin.json` 이 같은 MCP 설정(`.mcp.json`)을 가리킨다.
플러그인을 지원하지 않는 버전이라면 MCP 만 직접 등록한다
(`~/.codex/config.toml` 의 `[mcp_servers.prd-spec]`).

스킬 자동 로딩은 Claude Code 기능이라, Codex 에는 작업 저장소의 `AGENTS.md` 로 규칙을 물린다.
규칙 본문을 복사하지 말고 **경로만 참조**한다 (이 저장소가 쓰는 방식):

```markdown
PRD·기능명세서 내용을 쓰거나 고칠 때는 `plugin/skills/prd-spec/SKILL.md` 의 작성 규칙을 따른다.
```

다른 저장소에서 쓴다면 `skills/prd-spec/SKILL.md` 를 그 저장소에 복사해 두고 같은 식으로 가리킨다.

## MCP 만 붙이기 (플러그인 없이)

```bash
claude mcp add --transport http prd-spec https://<호스트>/mcp -H "Authorization: Bearer <토큰>"
```

## 주의

- 토큰은 그 사용자의 **모든 프로젝트에 대한 읽기·쓰기 권한**이다. 공유하지 않는다.
- 로그아웃하면 토큰이 무효가 되므로 다시 발급해 환경변수를 갱신한다.
- `.claude-plugin/plugin.json` 의 인라인 MCP 설정과 `.mcp.json` 은 **같은 내용을 유지**해야 한다
  (Claude 는 인라인 객체, Codex 는 파일 경로를 읽는다).
