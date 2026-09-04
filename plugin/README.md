# olgae-planner 플러그인

PRD & 기능명세서 서비스를 AI 에이전트에 붙이는 플러그인. 두 가지가 들어 있다.

- **MCP 서버 연결** — 배포 서버의 `/mcp` 엔드포인트(툴 13개: 명세 조회·수정, 용어 사전, 버전, 코멘트)
- **스킬** `olgae-planner` — 이 서비스의 작성 컨벤션과 산출물 규칙([skills/olgae-planner/SKILL.md](skills/olgae-planner/SKILL.md))

## 준비: 계정과 토큰

이 플러그인에는 서버 주소도 토큰도 들어 있지 않다. 각자 **자기 배포 서버 주소**와
**자기 계정의 API 토큰**을 환경변수로 넣어 쓴다. 그래서 하나의 플러그인으로 여러 서버를 쓸 수 있다.

1. 서비스에 계정을 만든다 (가입은 관리자 승인 후 사용 가능).
2. 로그인해서 헤더 메뉴 → **플러그인 설치** → `+ 새 토큰 발급`.
   전체 값은 그 자리에서 한 번만 보이니 복사해 둔다. 목록에는 앞뒤만 남는다.
3. 환경변수로 둔다. 설정 파일에 토큰을 적지 않아도 된다.

```bash
export OLGAE_URL=https://<호스트>/mcp     # 생략하면 http://localhost:3000/mcp
export OLGAE_TOKEN=olg_...
```

Windows PowerShell:

```powershell
$env:OLGAE_URL  = "https://<호스트>/mcp"
$env:OLGAE_TOKEN = "olg_..."
```

토큰으로 보이는 것은 **그 계정이 만든 프로젝트 + 멤버로 참여중인 프로젝트**다.
할 수 있는 일은 화면에서와 똑같이 프로젝트별 권한을 따른다 —
편집자는 내용 수정·버전, 공동 소유자는 공유 링크·멤버 관리까지, 소유자만 프로젝트 삭제.

## Claude Code

```bash
claude plugin marketplace add kdHyeok/olgae-planner
claude plugin install olgae-planner@olgae-planner
```

마켓플레이스 목록은 저장소 루트의 `.claude-plugin/marketplace.json` 이다.
저장소를 클론해 뒀다면 그 경로로 바로 등록할 수 있다 (`.` 은 안 되고 `./` 형태로 준다).

```bash
claude plugin marketplace add ./          # 클론한 저장소 루트에서
claude plugin install olgae-planner@olgae-planner
```

등록 뒤 Claude Code 를 재시작하고 `/mcp` 로 연결(`plugin:olgae-planner:olgae-planner`),
`/plugin` 으로 스킬 `olgae-planner` 을 확인한다.

> `claude mcp add` 로 같은 이름(`olgae-planner`)을 이미 등록해 뒀다면 그쪽이 플러그인 설정을 가린다.
> 플러그인 쪽을 쓰려면 수동 등록을 지운다: `claude mcp remove olgae-planner`.
> 목록에 `Connected` 로 떠도 토큰 검사는 통과한 게 아니다(연결 단계에는 인증이 필요 없다).
> 실제 권한은 툴을 한 번 호출해 봐야 알 수 있다.

## Codex

`.codex-plugin/plugin.json` 이 같은 MCP 설정(`.mcp.json`)을 가리킨다.
플러그인을 지원하지 않는 버전이라면 MCP 만 직접 등록한다
(`~/.codex/config.toml` 의 `[mcp_servers.olgae-planner]`).

스킬 자동 로딩은 Claude Code 기능이라, Codex 에는 작업 저장소의 `AGENTS.md` 로 규칙을 물린다.
규칙 본문을 복사하지 말고 **경로만 참조**한다 (이 저장소가 쓰는 방식):

```markdown
PRD·기능명세서 내용을 쓰거나 고칠 때는 `plugin/skills/olgae-planner/SKILL.md` 의 작성 규칙을 따른다.
```

다른 저장소에서 쓴다면 `skills/olgae-planner/SKILL.md` 를 그 저장소에 복사해 두고 같은 식으로 가리킨다.

## MCP 만 붙이기 (플러그인 없이)

```bash
claude mcp add --transport http olgae-planner https://<호스트>/mcp -H "Authorization: Bearer olg_..."
```

## 주의

- 토큰은 그 계정으로 행동하는 열쇠다. 공유하지 않는다.
  유출됐으면 **플러그인 설치** 창의 목록에서 지우면 즉시 끊긴다.
- 브라우저 세션과 별개라 **로그아웃해도 계속 동작한다**.
  관리자가 그 계정의 비밀번호를 재설정하면 함께 끊긴다.
- 계정당 토큰은 10개까지. 기기·용도별로 따로 발급해 두면 하나만 폐기할 수 있다.
- `.claude-plugin/plugin.json` 의 인라인 MCP 설정과 `.mcp.json` 은 **같은 내용을 유지**해야 한다
  (Claude 는 인라인 객체, Codex 는 파일 경로를 읽는다).
