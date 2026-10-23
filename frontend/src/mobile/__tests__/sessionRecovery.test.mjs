import test from 'node:test';
import assert from 'node:assert/strict';
import { isSessionOrphaned, planSessionRestore, stripTokensFromProfile } from '../auth/sessionRecovery.js';

const EMPTY_PROFILE = { user: null, userId: null, userEmail: null };
const DEVICE_PROFILE = { user: '{"userId":7}', userId: '7', userEmail: 'a@b.c' };

test('WebView 에 최신 refresh token 이 있으면 기기 저장본으로 덮어쓰지 않는다', () => {
  const plan = planSessionRestore({
    localRefreshToken: 'rotated-new',
    vaultRefreshToken: 'stale-old',
    localProfile: EMPTY_PROFILE,
    deviceProfile: DEVICE_PROFILE,
  });

  assert.equal(plan.refreshTokenToRestore, null);
  assert.deepEqual(plan.profileToRestore, {});
});

test('WebView 저장소가 비었으면 암호화 저장본과 프로필을 복구한다', () => {
  const plan = planSessionRestore({
    localRefreshToken: null,
    vaultRefreshToken: 'vault-token',
    localProfile: EMPTY_PROFILE,
    deviceProfile: DEVICE_PROFILE,
  });

  assert.equal(plan.refreshTokenToRestore, 'vault-token');
  assert.deepEqual(plan.profileToRestore, DEVICE_PROFILE);
});

test('복구할 토큰이 없으면 프로필만 되살려 반쪽 세션을 만들지 않는다', () => {
  const plan = planSessionRestore({
    localRefreshToken: null,
    vaultRefreshToken: null,
    localProfile: EMPTY_PROFILE,
    deviceProfile: DEVICE_PROFILE,
  });

  assert.equal(plan.refreshTokenToRestore, null);
  assert.deepEqual(plan.profileToRestore, {});
});

test('사용자 정보만 남고 토큰이 모두 사라진 세션은 고아 세션이다', () => {
  assert.equal(isSessionOrphaned({ userId: '7', token: null, refreshToken: null }), true);
  assert.equal(isSessionOrphaned({ userId: '7', token: null, refreshToken: 'r' }), false);
  assert.equal(isSessionOrphaned({ userId: null, token: null, refreshToken: null }), false);
});

test('기기 저장소에 남기는 사용자 프로필에서는 토큰 필드를 제거한다', () => {
  const stored = JSON.stringify({ userId: 7, email: 'a@b.c', accessToken: 'jwt-a', refreshToken: 'jwt-r' });
  const sanitized = JSON.parse(stripTokensFromProfile('user', stored));

  assert.deepEqual(sanitized, { userId: 7, email: 'a@b.c' });
  assert.equal(stripTokensFromProfile('userId', '7'), '7');
  assert.equal(stripTokensFromProfile('user', '{broken'), null);
});
