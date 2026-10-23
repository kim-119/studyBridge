// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { createCancelRegistry } from '../studymate/streamCancelRegistry.js';
import { createStreamStateMachine, STREAM_PHASES } from '../studymate/streamStateMachine.js';

test('Stop aborts the registered controller exactly once and clears the entry', () => {
  const reg = createCancelRegistry();
  const c = new AbortController();
  reg.register(234, c, 'web-A');
  assert.equal(reg.has(234), true);
  assert.equal(reg.cancel(234, 'user_stop'), true);
  assert.equal(c.signal.aborted, true);
  assert.equal(c.signal.reason, 'user_stop');
  assert.equal(reg.has(234), false);
  assert.equal(reg.cancel(234, 'user_stop'), false, '두 번째 취소는 no-op');
});

test('new question replaces the previous turn: cancelling old controller does not touch the new one', () => {
  const reg = createCancelRegistry();
  const a = new AbortController();
  const b = new AbortController();
  reg.register(1, a, 'web-A');
  reg.cancel(1, 'new_question');
  reg.register(1, b, 'web-B');
  reg.release(1, 'web-A'); // 늦게 실행된 A 의 finally
  assert.equal(reg.has(1), true, 'A 의 release 가 B 등록을 지우지 않는다');
  assert.equal(a.signal.aborted, true);
  assert.equal(b.signal.aborted, false);
});

test('room change / unmount cancels every in-flight stream', () => {
  const reg = createCancelRegistry();
  const cs = [new AbortController(), new AbortController(), new AbortController()];
  cs.forEach((c, i) => reg.register(i + 1, c, `web-${i}`));
  assert.equal(reg.cancelAll('unmount'), 3);
  assert.ok(cs.every((c) => c.signal.aborted));
  assert.equal(reg.size, 0);
});

test('state machine reflects cancel and keeps partial answers semantics (not FAILED)', async () => {
  const reg = createCancelRegistry();
  const m = createStreamStateMachine();
  const c = new AbortController();
  reg.register(7, c, 'web-C');
  m.open(); m.event('agent_answer');
  const aborted = new Promise((resolve) => c.signal.addEventListener('abort', () => { m.cancel(c.signal.reason); resolve(); }));
  reg.cancel(7, 'mode_switch');
  await aborted;
  assert.equal(m.phase, STREAM_PHASES.CANCELLED);
  assert.equal(m.anyAnswer, true, '취소 전 받은 답변은 유지(부분 답변 보존)');
  m.close();
  assert.equal(m.phase, STREAM_PHASES.CANCELLED, '취소는 FAILED 로 바뀌지 않는다');
});
