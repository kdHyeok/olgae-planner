import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const mcp = JSON.parse(readFileSync(new URL('../plugin/.mcp.json', import.meta.url), 'utf8'))
  .mcpServers['olgae-planner'];
const claudePlugin = JSON.parse(readFileSync(
  new URL('../plugin/.claude-plugin/plugin.json', import.meta.url), 'utf8'));
const codexPlugin = JSON.parse(readFileSync(
  new URL('../plugin/.codex-plugin/plugin.json', import.meta.url), 'utf8'));
const claudeMcp = claudePlugin.mcpServers['olgae-planner'];

test('로그아웃 헤더는 단일 버튼으로 인증 모달을 연다', () => {
  const renderAuth = html.match(/function renderAuth\(\)[\s\S]*?\n}/)?.[0] || '';
  assert.match(renderAuth, /openAuthModal\('login'\)/);
  assert.doesNotMatch(renderAuth, /id="au-(id|pw)"/);
  assert.match(html, /function authModalHTML\(mode\)/);
  assert.match(html, /openAuthModal\('register'\)/);
  assert.match(html, /<label class="auth-field">닉네임/);
  assert.match(html, /Google로 계속하기/);
  assert.match(html, /\/api\/auth\/google\/start/);
  assert.match(html, /Google 계정 연결/);
});

test('설치형 플러그인은 빈 Bearer 헤더 없이 배포 서버 OAuth를 사용한다', () => {
  for (const config of [mcp, claudeMcp]) {
    assert.equal(config.url, '${OLGAE_URL:-https://prd.donhse.duckdns.org/mcp}');
    assert.equal(config.headers, undefined);
  }
  assert.match(html, /별도 토큰은 필요 없습니다/);
  assert.match(html, /OAuth 로그인을 완료한 뒤/);
  assert.equal(claudePlugin.version, codexPlugin.version);
});
