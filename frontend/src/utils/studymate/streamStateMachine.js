// StudyMate SSE 턴 상태 머신 — boolean 조합(isLoading/isDone/…) 대신 단일 phase 로 모순 상태를 막는다.
//  IDLE → CONNECTING → STREAMING → FINALIZING → COMPLETED
//                              → FAILED / CANCELLED   (종결 상태에서는 되돌아가지 않는다)
//  · all_complete = 비즈니스 완료(FINALIZING 진입), done = 프로토콜 종결(finalReceived), close = 전송 종료(COMPLETED/FAILED 판정).
//  · 종결 상태(COMPLETED/FAILED/CANCELLED)에서 event/allComplete/done 은 무시된다(늦은 이벤트 방어).
export const STREAM_PHASES = Object.freeze({
  IDLE: 'IDLE', CONNECTING: 'CONNECTING', STREAMING: 'STREAMING', FINALIZING: 'FINALIZING',
  COMPLETED: 'COMPLETED', FAILED: 'FAILED', CANCELLED: 'CANCELLED',
});
const TERMINAL = new Set([STREAM_PHASES.COMPLETED, STREAM_PHASES.FAILED, STREAM_PHASES.CANCELLED]);
const ANSWER_EVENTS = new Set(['agent_answer', 'stage_complete', 'socratic_step', 'debate_section', 'simulation_stage']);

export function createStreamStateMachine(onChange) {
  let phase = STREAM_PHASES.IDLE;
  let allCompleteSeen = false;
  let doneSeen = false;
  let anyAnswer = false;
  let cancelReason = null;
  const set = (next, note) => {
    if (phase === next) return phase;
    if (TERMINAL.has(phase)) return phase;
    phase = next;
    if (onChange) onChange(phase, note);
    return phase;
  };
  return {
    get phase() { return phase; },
    get isTerminal() { return TERMINAL.has(phase); },
    // UI 의 '로딩/전송 잠금' 은 오직 이 값에서 파생한다.
    get isLoading() { return phase === STREAM_PHASES.CONNECTING || phase === STREAM_PHASES.STREAMING || phase === STREAM_PHASES.FINALIZING; },
    get finalReceived() { return allCompleteSeen || doneSeen; },
    get allCompleteSeen() { return allCompleteSeen; },
    get doneSeen() { return doneSeen; },
    get anyAnswer() { return anyAnswer; },
    get cancelReason() { return cancelReason; },
    open() { return set(STREAM_PHASES.CONNECTING, 'open'); },
    // business/control event 수신(heartbeat 포함): CONNECTING → STREAMING. FINALIZING 이후엔 유지.
    event(name) {
      if (TERMINAL.has(phase)) return phase;
      if (ANSWER_EVENTS.has(name)) anyAnswer = true;
      if (phase === STREAM_PHASES.CONNECTING || phase === STREAM_PHASES.IDLE) return set(STREAM_PHASES.STREAMING, name);
      return phase;
    },
    allComplete() {
      if (TERMINAL.has(phase)) return phase;
      allCompleteSeen = true;
      return set(STREAM_PHASES.FINALIZING, 'all_complete');
    },
    done() {
      if (TERMINAL.has(phase)) return phase;
      doneSeen = true;
      return set(STREAM_PHASES.FINALIZING, 'done');
    },
    // 전송 종료(reader done / fetch resolve). 최종 신호 여부로 COMPLETED/FAILED 를 판정한다.
    close() {
      if (TERMINAL.has(phase)) return phase;
      return set(allCompleteSeen || doneSeen ? STREAM_PHASES.COMPLETED : STREAM_PHASES.FAILED, 'close');
    },
    fail(reason) {
      if (TERMINAL.has(phase)) return phase;
      return set(STREAM_PHASES.FAILED, reason || 'fail');
    },
    cancel(reason) {
      if (TERMINAL.has(phase)) return phase;
      cancelReason = reason || 'cancel';
      return set(STREAM_PHASES.CANCELLED, cancelReason);
    },
  };
}
