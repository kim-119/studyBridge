// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  readTokenExpiryMs,
  isTokenExpiring,
  resolveStompAccessToken,
  buildStompConnectHeaders,
  classifyStompError,
  createStompAuthPolicy,
  isOwnQuizAck,
  MAX_UNAUTHORIZED_RETRIES,
} from '../stompAuth.js';

const b64url = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const tokenExpiringAt = (ms) => `${b64url({ alg: 'HS256' })}.${b64url({ sub: 'a@b', userId: 11, exp: Math.floor(ms / 1000) })}.sig`;
const errorFrame = (message, reason) => ({ headers: { message, ...(reason ? { 'sb-reason': reason } : {}) } });

test('토큰 exp 판독: 정상/형식 오류', () => {
  assert.equal(readTokenExpiryMs(tokenExpiringAt(2_000_000_000_000)), 2_000_000_000_000);
  assert.equal(readTokenExpiryMs('not-a-jwt'), null);
  assert.equal(readTokenExpiryMs(null), null);
  assert.equal(isTokenExpiring('garbage', Date.now()), false, 'exp 를 못 읽으면 서버 판단에 맡긴다');
});

test('곧 만료(60초 이내)면 갱신 대상', () => {
  const now = 1_000_000;
  assert.equal(isTokenExpiring(tokenExpiringAt(now + 30_000), now), true);
  assert.equal(isTokenExpiring(tokenExpiringAt(now + 10 * 60_000), now), false);
});

test('연결 직전 토큰: 유효하면 그대로, 만료 임박·없음·강제면 갱신', async () => {
  const now = 1_000_000;
  const fresh = tokenExpiringAt(now + 10 * 60_000);
  const stale = tokenExpiringAt(now - 1);
  let refreshed = 0;
  const refresh = async () => { refreshed += 1; return 'NEW'; };

  assert.equal(await resolveStompAccessToken({ getStoredToken: () => fresh, refresh, now }), fresh);
  assert.equal(refreshed, 0);
  assert.equal(await resolveStompAccessToken({ getStoredToken: () => stale, refresh, now }), 'NEW');
  assert.equal(await resolveStompAccessToken({ getStoredToken: () => null, refresh, now }), 'NEW');
  assert.equal(await resolveStompAccessToken({ getStoredToken: () => fresh, refresh, now, forceRefresh: true }), 'NEW');
  assert.equal(refreshed, 3);
});

test('갱신 실패 시 저장 토큰으로 시도(서버가 다시 거부하면 정책이 멈춘다)', async () => {
  const stale = tokenExpiringAt(1);
  const token = await resolveStompAccessToken({ getStoredToken: () => stale, refresh: async () => { throw new Error('401'); }, now: 10_000 });
  assert.equal(token, stale);
});

test('CONNECT 헤더: 토큰이 없으면 빈 Authorization 을 보내지 않는다', () => {
  assert.deepEqual(buildStompConnectHeaders('abc'), { Authorization: 'Bearer abc' });
  assert.deepEqual(buildStompConnectHeaders(null), {});
});

test('ERROR 분류: 서버 message 헤더 계약', () => {
  assert.equal(classifyStompError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID')), 'unauthorized');
  assert.equal(classifyStompError(errorFrame('FORBIDDEN', 'NOT_GROUP_MEMBER')), 'forbidden');
  assert.equal(classifyStompError(errorFrame('BAD_REQUEST')), 'other');
  assert.equal(classifyStompError({}), 'other');
});

test('정책: FORBIDDEN 은 즉시 멈춤, 사유별 안내', () => {
  const policy = createStompAuthPolicy();
  const d = policy.onError(errorFrame('FORBIDDEN', 'MEMBERSHIP_REVOKED'));
  assert.equal(d.action, 'stop');
  assert.match(d.message, /권한/);
  assert.match(policy.onError(errorFrame('FORBIDDEN', 'NOT_GROUP_MEMBER')).message, /그룹 멤버/);
});

test('정책: UNAUTHORIZED 는 강제 갱신 후 재시도, 연속 한도 초과 시 멈춤, 연결 성공하면 초기화', () => {
  const policy = createStompAuthPolicy();
  for (let i = 0; i < MAX_UNAUTHORIZED_RETRIES; i += 1) {
    assert.equal(policy.onError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID')).action, 'refresh-and-retry');
    assert.equal(policy.consumeForceRefresh(), true);
    assert.equal(policy.consumeForceRefresh(), false, '한 번만 소비');
  }
  assert.equal(policy.onError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID')).action, 'stop');

  const again = createStompAuthPolicy();
  again.onError(errorFrame('UNAUTHORIZED'));
  again.onError(errorFrame('UNAUTHORIZED'));
  again.onConnected();
  for (let i = 0; i < MAX_UNAUTHORIZED_RETRIES; i += 1) {
    assert.equal(again.onError(errorFrame('UNAUTHORIZED')).action, 'refresh-and-retry');
  }
});

test('정책: 인증과 무관한 오류는 기존 재연결 유지', () => {
  assert.equal(createStompAuthPolicy().onError(errorFrame('BAD_REQUEST')).action, 'retry');
});

test('퀴즈 ack: 내 것만 반영(다른 멤버 제출이 내 버튼을 잠그지 않음)', () => {
  assert.equal(isOwnQuizAck({ userId: 11, accepted: true }, '11'), true);
  assert.equal(isOwnQuizAck({ userId: '11', accepted: true }, 11), true);
  assert.equal(isOwnQuizAck({ userId: 12, accepted: true }, 11), false);
  assert.equal(isOwnQuizAck({ accepted: true }, 11), true, 'userId 없는 ack 는 이전 서버 호환');
  assert.equal(isOwnQuizAck(null, 11), false);
});
