import test from 'node:test';
import assert from 'node:assert/strict';
import { anchorFromSession, elapsedSecondsFrom, formatHMS, checkRunningSession } from '../studyTimer.js';

test('anchor uses server-local startTime/lastHeartbeatAt difference (timezone-agnostic) and client monotonic delta', () => {
  const now = 1_000_000;
  const a = anchorFromSession({ id: 7, startTime: '2026-10-07T11:00:00', lastHeartbeatAt: '2026-10-07T11:17:30', status: 'RUNNING' }, now);
  assert.equal(a.elapsedMs, 17.5 * 60 * 1000);
  assert.equal(elapsedSecondsFrom(a, now), 1050);
  assert.equal(elapsedSecondsFrom(a, now + 12_000), 1062);
  assert.equal(formatHMS(elapsedSecondsFrom(a, now)), '00:17:30');
});

test('refresh restore: resumed session with same startTime yields the same elapsed, not 00:00:00', () => {
  const s = { id: 7, startTime: '2026-10-07T11:00:00', lastHeartbeatAt: '2026-10-07T11:17:00', resumed: true };
  assert.equal(formatHMS(elapsedSecondsFrom(anchorFromSession(s, 0), 0)), '00:17:00');
});

test('fresh session without heartbeat starts at 0; ended session yields null anchor; array LocalDateTime accepted', () => {
  assert.equal(elapsedSecondsFrom(anchorFromSession({ id: 1, startTime: '2026-10-07T11:00:00' }, 5000), 5000), 0);
  assert.equal(anchorFromSession({ id: 1, startTime: '2026-10-07T11:00:00', endTime: '2026-10-07T11:30:00', status: 'ENDED' }), null);
  assert.equal(anchorFromSession(null), null);
  const a = anchorFromSession({ startTime: [2026, 10, 7, 11, 0, 0], lastHeartbeatAt: [2026, 10, 7, 11, 1, 5] }, 0);
  assert.equal(elapsedSecondsFrom(a, 0), 65);
});

test('formatHMS pads and clamps', () => {
  assert.equal(formatHMS(0), '00:00:00');
  assert.equal(formatHMS(3661), '01:01:01');
  assert.equal(formatHMS(-5), '00:00:00');
  assert.equal(formatHMS(36000), '10:00:00');
});

// 학습리포트 타이머 30초 주기: 개인 세션만 heartbeat, 그룹 세션은 서버 상태 재조회(방 밖에서 그룹 출석 누적 방지)
const fakeApi = (hbResult, currentResult) => {
  const calls = { heartbeat: 0, current: 0 };
  return {
    calls,
    heartbeat: async () => { calls.heartbeat += 1; return hbResult; },
    getCurrentSession: async () => { calls.current += 1; return currentResult; },
  };
};
const running = (groupStudyId = null) => ({ id: 1, startTime: '2026-10-29T05:00:00', endTime: null, groupStudyId });

test('personal session: heartbeat only; 204(null) means stop', async () => {
  const api = fakeApi(running(), running());
  assert.equal(await checkRunningSession(null, api), true);
  assert.deepEqual(api.calls, { heartbeat: 1, current: 0 });
  const gone = fakeApi(null, null);
  assert.equal(await checkRunningSession(null, gone), false);
});

test('group session: never heartbeats from the report screen, only re-reads server state', async () => {
  const api = fakeApi(running(25), running(25));
  assert.equal(await checkRunningSession(25, api), true);
  assert.deepEqual(api.calls, { heartbeat: 0, current: 1 });
  // 방에서 종료·reaper 자동 종료(204 → '') 또는 다른 그룹으로 바뀌면 다시 불러와야 함
  assert.equal(await checkRunningSession(25, fakeApi(null, '')), false);
  assert.equal(await checkRunningSession(25, fakeApi(null, running(26))), false);
  assert.equal(await checkRunningSession(25, fakeApi(null, { ...running(25), endTime: '2026-10-29T05:10:00' })), false);
});
