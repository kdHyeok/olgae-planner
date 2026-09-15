import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const html = readFileSync(new URL('./index.html', import.meta.url), 'utf8');

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
