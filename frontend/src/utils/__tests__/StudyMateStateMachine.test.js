// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { createStreamStateMachine, STREAM_PHASES } from '../studymate/streamStateMachine.js';

test('happy path: IDLE → CONNECTING → STREAMING → FINALIZING(all_complete) → FINALIZING(done) → COMPLETED(close)', () => {
  const seen = [];
  const m = createStreamStateMachine((p, note) => seen.push(`${p}:${note}`));
  assert.equal(m.phase, STREAM_PHASES.IDLE);
  assert.equal(m.isLoading, false);
  m.open();
  assert.equal(m.isLoading, true);
  m.event('turn_start');
  assert.equal(m.phase, STREAM_PHASES.STREAMING);
  m.event('heartbeat');
  m.event('agent_answer');
  assert.equal(m.anyAnswer, true);
  m.allComplete();
  assert.equal(m.phase, STREAM_PHASES.FINALIZING);
  assert.equal(m.isLoading, true, 'all_complete 후 done/close 전까지는 아직 로딩(전송 잠금)');
  m.done();
  assert.equal(m.finalReceived, true);
  m.close();
  assert.equal(m.phase, STREAM_PHASES.COMPLETED);
  assert.equal(m.isLoading, false);
  assert.equal(m.isTerminal, true);
  assert.deepEqual(seen, ['CONNECTING:open', 'STREAMING:turn_start', 'FINALIZING:all_complete', 'COMPLETED:close']);
});

test('close without final signal is FAILED; late events after terminal are ignored (no contradictory state)', () => {
  const m = createStreamStateMachine();
  m.open(); m.event('agent_answer'); m.close();
  assert.equal(m.phase, STREAM_PHASES.FAILED);
  m.event('agent_answer'); m.allComplete(); m.done(); m.open();
  assert.equal(m.phase, STREAM_PHASES.FAILED, '종결 후 되돌아가지 않는다');
  assert.equal(m.isLoading, false);
});

test('cancel is terminal and keeps reason; done after cancel does not resurrect', () => {
  const m = createStreamStateMachine();
  m.open(); m.event('turn_start');
  m.cancel('user_stop');
  assert.equal(m.phase, STREAM_PHASES.CANCELLED);
  assert.equal(m.cancelReason, 'user_stop');
  m.done(); m.close();
  assert.equal(m.phase, STREAM_PHASES.CANCELLED);
  assert.equal(m.isLoading, false);
});

test('done only (no all_complete) still counts as final → COMPLETED on close; fail() before final → FAILED', () => {
  const a = createStreamStateMachine();
  a.open(); a.done(); a.close();
  assert.equal(a.phase, STREAM_PHASES.COMPLETED);
  const b = createStreamStateMachine();
  b.open(); b.fail('http_503');
  assert.equal(b.phase, STREAM_PHASES.FAILED);
});
