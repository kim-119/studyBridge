import test from 'node:test';
import assert from 'node:assert/strict';
import { anchorFromSession, elapsedSecondsFrom, formatHMS } from '../studyTimer.js';

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
