// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { createTurnGuard } from '../studymate/turnGuard.js';

test('question A then B: A late events are rejected as stale_turn, B events accepted', () => {
  const g = createTurnGuard();
  const a = g.begin(234, 'web-A');
  const b = g.begin(234, 'web-B');
  assert.equal(a.isActive(), false);
  assert.equal(b.isActive(), true);
  assert.deepEqual(a.accept({ requestId: 'web-A', eventId: 'e1' }), { ok: false, reason: 'stale_turn' });
  assert.deepEqual(b.accept({ requestId: 'web-B', eventId: 'e2' }), { ok: true, reason: null });
});

test('event carrying a foreign requestId is rejected even for the active turn (mixed stream defence)', () => {
  const g = createTurnGuard();
  const t = g.begin(1, 'web-X');
  assert.equal(t.accept({ requestId: 'web-OTHER' }).reason, 'foreign_request');
  assert.equal(t.accept({ requestId: 'web-X' }).ok, true);
  assert.equal(t.accept({}).ok, true, 'requestId 없는 레거시 이벤트는 활성 턴이면 통과');
});

test('duplicate eventId within a turn passes once; turnId is observed not enforced (failover may change it)', () => {
  const g = createTurnGuard();
  const t = g.begin(1, 'web-X');
  assert.equal(t.accept({ requestId: 'web-X', eventId: 'evt_1', turnId: 'turn_a' }).ok, true);
  assert.equal(t.accept({ requestId: 'web-X', eventId: 'evt_1', turnId: 'turn_a' }).reason, 'duplicate_event');
  assert.equal(t.accept({ requestId: 'web-X', eventId: 'evt_2', turnId: 'turn_b' }).ok, true);
  assert.equal(t.turnId, 'turn_a');
});

test('rooms are independent; end() only clears its own generation; mode/room switch invalidates', () => {
  const g = createTurnGuard();
  const r1 = g.begin(1, 'web-1');
  const r2 = g.begin(2, 'web-2');
  assert.equal(r1.isActive(), true);
  assert.equal(r2.isActive(), true);
  const r1b = g.begin(1, 'web-1b');
  r1.end();
  assert.equal(g.activeRequestId(1), 'web-1b', '이전 세대의 end() 는 새 세대를 지우지 않는다');
  g.invalidate(1);
  assert.equal(r1b.isActive(), false);
  assert.match(g.makeRequestId(), /^web-[a-z0-9]+-[a-z0-9]{12}$/);
});
