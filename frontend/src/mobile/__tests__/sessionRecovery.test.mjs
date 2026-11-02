import test from 'node:test';
import assert from 'node:assert/strict';
import {
  NATIVE_STUDY_SYNC,
  isSessionOrphaned,
  planNativeStudySync,
  planSessionRestore,
  stripTokensFromProfile,
} from '../auth/sessionRecovery.js';

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

test('네이티브 학습 기능에는 access token 이 있을 때만 세션을 넘긴다', () => {
  assert.equal(
    planNativeStudySync({ token: 'access', refreshToken: 'refresh', isAuthChange: false }),
    NATIVE_STUDY_SYNC.SHARE
  );
  assert.equal(
    planNativeStudySync({ token: null, refreshToken: 'refresh', isAuthChange: true }),
    NATIVE_STUDY_SYNC.WAIT,
    '리프레시 토큰만 있으면 갱신 이벤트를 기다린다'
  );
});

test('네이티브 학습 로그아웃은 인증 변경 이벤트에서만 보낸다(부팅 중 세션 복구 전에는 보내지 않는다)', () => {
  assert.equal(
    planNativeStudySync({ token: null, refreshToken: null, isAuthChange: true }),
    NATIVE_STUDY_SYNC.SIGN_OUT
  );
  assert.equal(
    planNativeStudySync({ token: null, refreshToken: null, isAuthChange: false }),
    NATIVE_STUDY_SYNC.WAIT
  );
});
