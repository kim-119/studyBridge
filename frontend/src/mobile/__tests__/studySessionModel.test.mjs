import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SESSION_KIND,
  checkRunningSession,
  describeRunningSession,
  elapsedSecondsOf,
  isSameRunningSession,
  parseServerDateTime,
  sessionFromServer,
} from '../screens/report/studySessionModel.js';

const NOW = Date.UTC(2026, 9, 28, 3, 0, 0); // 2026-10-28 12:00:00 서울

test('서버 LocalDateTime 은 서울 시각으로 해석한다', () => {
  assert.equal(parseServerDateTime('2026-10-28T12:00:00'), NOW);
  assert.equal(parseServerDateTime('2026-10-28T12:00:00.500'), NOW + 500);
  assert.equal(parseServerDateTime([2026, 10, 28, 12, 0, 0]), NOW);
  assert.equal(parseServerDateTime('2026-10-28T03:00:00Z'), NOW);
  assert.equal(parseServerDateTime(null), null);
  assert.equal(parseServerDateTime('not-a-date'), null);
});

test('서버에 활성 세션이 없으면 실행 중으로 보지 않는다(앱 시작·204·종료 세션)', () => {
  assert.equal(sessionFromServer(null, NOW), null);
  assert.equal(sessionFromServer('', NOW), null);
  assert.equal(sessionFromServer({}, NOW), null);
  assert.equal(
    sessionFromServer({ id: 1, startTime: '2026-10-28T11:00:00', endTime: '2026-10-28T11:30:00' }, NOW),
    null
  );
});

test('활성 개인 세션 복원: 경과는 서버 시각끼리(lastHeartbeatAt − startTime)로 계산한다', () => {
  const running = sessionFromServer(
    { id: 7, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:59:30', groupStudyId: null },
    NOW
  );
  assert.equal(running.kind, SESSION_KIND.PERSONAL);
  assert.equal(running.sessionId, 7);
  assert.equal(elapsedSecondsOf(running, NOW), 3570);
  assert.equal(elapsedSecondsOf(running, NOW + 10_000), 3580);
});

test('heartbeat 기록이 없는 구 세션은 시작 시각 기준으로 추정하고 음수가 되지 않는다', () => {
  const running = sessionFromServer({ id: 8, startTime: '2026-10-28T11:59:00' }, NOW);
  assert.equal(elapsedSecondsOf(running, NOW), 60);

  const future = sessionFromServer({ id: 9, startTime: '2026-10-28T12:05:00' }, NOW);
  assert.equal(elapsedSecondsOf(future, NOW), 0);
});

test('그룹 세션은 개인 타이머와 구분한다', () => {
  const running = sessionFromServer({ id: 3, startTime: '2026-10-28T11:00:00', groupStudyId: 51 }, NOW);
  assert.equal(running.kind, SESSION_KIND.GROUP);
  assert.equal(running.groupStudyId, '51');
  assert.match(describeRunningSession(running), /그룹 스터디룸/);
  assert.match(describeRunningSession(null), /시작을 누르면/);
});

test('주기 확인: 같은 세션만 계속 진행으로 인정한다', () => {
  const running = sessionFromServer({ id: 7, startTime: '2026-10-28T11:00:00' }, NOW);
  assert.equal(isSameRunningSession(running, { id: 7, startTime: '2026-10-28T11:00:00' }), true);
  assert.equal(isSameRunningSession(running, null), false, '204 = 서버가 자동 종료');
  assert.equal(isSameRunningSession(running, { id: 8, startTime: '2026-10-28T11:10:00' }), false, '다른 세션');
  assert.equal(
    isSameRunningSession(running, { id: 7, startTime: '2026-10-28T11:00:00', endTime: '2026-10-28T11:20:00' }),
    false
  );
  assert.equal(
    isSameRunningSession(running, { id: 7, startTime: '2026-10-28T11:00:00', groupStudyId: 51 }),
    false,
    '다른 컨텍스트'
  );
});

test('개인 세션만 heartbeat 하고 그룹 세션은 조회만 한다', async () => {
  const calls = [];
  const deps = {
    heartbeat: async () => {
      calls.push('heartbeat');
      return { id: 7, startTime: '2026-10-28T11:00:00' };
    },
    getCurrentSession: async () => {
      calls.push('current');
      return { id: 3, startTime: '2026-10-28T11:00:00', groupStudyId: 51 };
    },
  };

  const personal = sessionFromServer({ id: 7, startTime: '2026-10-28T11:00:00' }, NOW);
  const group = sessionFromServer({ id: 3, startTime: '2026-10-28T11:00:00', groupStudyId: 51 }, NOW);

  assert.equal(await checkRunningSession(personal, deps), true);
  assert.equal(await checkRunningSession(group, deps), true);
  assert.equal(await checkRunningSession(null, deps), false);
  assert.deepEqual(calls, ['heartbeat', 'current']);
});
