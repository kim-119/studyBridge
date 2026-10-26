export const QUIZ_PHASE = {
  IDLE: 'IDLE',
  QUESTION: 'QUESTION',
  NEXT: 'NEXT',
  REVEAL: 'REVEAL',
  ENDED: 'ENDED',
};

const DEFAULT_TIME_LIMIT_SECONDS = 30;
const FALLBACK_TIME_TAKEN_SECONDS = 5;
const MAX_REMEMBERED_DISMISSALS = 20;

export const INITIAL_QUIZ_STATE = {
  sessionId: null,
  phase: QUIZ_PHASE.IDLE,
  question: null,
  deadlineAt: null,
  startedAt: null,
  selectedAnswer: null,
  hasSubmitted: false,
  submissionAck: null,
  reveal: null,
  scoreboard: null,
  finalResult: null,
};

function toScoreboard(payload) {
  return Array.isArray(payload?.scoreboard) ? payload.scoreboard : null;
}

function toReveal(payload) {
  return {
    correctAnswer: payload.correctAnswer,
    pointsAwarded: payload.pointsAwarded,
    message: payload.message || '',
  };
}

function resolveDeadline(payload, now) {
  if (typeof payload.remainingSeconds === 'number') return now + payload.remainingSeconds * 1000;
  if (payload.questionEndsAt) return new Date(payload.questionEndsAt).getTime();
  return null;
}

function resolveStartedAt(payload, timeLimitSeconds, now) {
  if (typeof payload.remainingSeconds !== 'number') return now;
  return now - Math.max(0, (timeLimitSeconds - payload.remainingSeconds) * 1000);
}

function isDifferentQuestion(state, payload) {
  const previous = state.question?.questionId ?? null;
  const incoming = payload.questionId ?? null;
  if (previous == null || incoming == null) return true;
  return Number(previous) !== Number(incoming);
}

export function acceptsSession(state, payload) {
  if (!payload?.sessionId || !state.sessionId) return true;
  return Number(payload.sessionId) === Number(state.sessionId);
}

export function applySessionPayload(state, payload, now) {
  if (!payload) return state;

  const phase = payload.phase || QUIZ_PHASE.QUESTION;
  const timeLimitSeconds = payload.timeLimitSeconds ?? DEFAULT_TIME_LIMIT_SECONDS;
  const showsResult = phase === QUIZ_PHASE.REVEAL || phase === QUIZ_PHASE.ENDED;
  const next = {
    ...state,
    sessionId: payload.sessionId ?? null,
    phase,
    question: {
      quizId: payload.quizId,
      quizTitle: payload.quizTitle,
      questionId: payload.questionId,
      questionText: payload.questionText,
      options: payload.options || [],
      currentIndex: payload.currentIndex ?? 0,
      totalQuestions: payload.totalQuestions ?? 0,
      timeLimitSeconds,
    },
    deadlineAt: resolveDeadline(payload, now),
    startedAt: resolveStartedAt(payload, timeLimitSeconds, now),
    scoreboard: showsResult ? toScoreboard(payload) : null,
    reveal: showsResult ? toReveal(payload) : null,
    submissionAck: null,
    finalResult: phase === QUIZ_PHASE.ENDED ? payload : null,
  };

  if (typeof payload.userSubmitted === 'boolean') {
    next.selectedAnswer =
      typeof payload.userSubmittedAnswer === 'number' ? payload.userSubmittedAnswer : null;
    next.hasSubmitted = payload.userSubmitted;
  } else if (isDifferentQuestion(state, payload)) {
    next.selectedAnswer = null;
    next.hasSubmitted = false;
  }

  return next;
}

export function applyTimerPayload(state, payload, now) {
  if (!acceptsSession(state, payload) || typeof payload?.remainingSeconds !== 'number') return state;
  return { ...state, deadlineAt: now + payload.remainingSeconds * 1000 };
}

export function applySubmittedPayload(state, payload) {
  if (!acceptsSession(state, payload)) return state;

  const currentQuestionId = state.question?.questionId;
  if (payload.questionId && currentQuestionId && Number(payload.questionId) !== Number(currentQuestionId)) {
    return state;
  }

  const accepted = Boolean(payload.accepted);
  return {
    ...state,
    submissionAck: payload,
    hasSubmitted: accepted,
    selectedAnswer: accepted ? state.selectedAnswer : null,
  };
}

export function applyRevealPayload(state, payload) {
  if (!acceptsSession(state, payload)) return state;
  return {
    ...state,
    phase: QUIZ_PHASE.REVEAL,
    reveal: toReveal(payload),
    scoreboard: toScoreboard(payload),
  };
}

export function applyScoreboardPayload(state, payload) {
  if (!acceptsSession(state, payload)) return state;

  const next = { ...state, scoreboard: toScoreboard(payload) };
  if (payload.phase === QUIZ_PHASE.REVEAL) {
    next.phase = QUIZ_PHASE.REVEAL;
    next.reveal = toReveal(payload);
  }
  if (payload.phase === QUIZ_PHASE.ENDED) {
    next.phase = QUIZ_PHASE.ENDED;
    next.finalResult = payload;
  }
  return next;
}

export function applyEndPayload(state, payload) {
  if (!acceptsSession(state, payload)) return state;
  return {
    ...state,
    phase: QUIZ_PHASE.ENDED,
    finalResult: payload,
    scoreboard: toScoreboard(payload),
  };
}

export function selectAnswer(state, answerIndex) {
  return { ...state, selectedAnswer: answerIndex, hasSubmitted: true };
}

export function remainingSecondsAt(state, now) {
  if (!state.deadlineAt) return 0;
  return Math.max(0, Math.ceil((state.deadlineAt - now) / 1000));
}

export function timeTakenSecondsAt(state, now) {
  if (!state.startedAt) return FALLBACK_TIME_TAKEN_SECONDS;
  return Math.round((now - state.startedAt) / 1000);
}

export function isAnswerable(state, now) {
  const isAnsweringPhase = state.phase === QUIZ_PHASE.QUESTION || state.phase === QUIZ_PHASE.NEXT;
  return isAnsweringPhase && !state.hasSubmitted && remainingSecondsAt(state, now) > 0;
}

export function isQuizActive(state) {
  return Boolean(state.question) && state.phase !== QUIZ_PHASE.IDLE;
}

export function dismissalStorageKey(groupId) {
  return `sb_quiz_dismissed_${groupId}`;
}

export function parseDismissedSessions(raw) {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.map(Number) : [];
  } catch {
    return [];
  }
}

export function rememberDismissedSession(dismissed, sessionId) {
  const unique = new Set(dismissed.map(Number));
  unique.add(Number(sessionId));
  return Array.from(unique).slice(-MAX_REMEMBERED_DISMISSALS);
}
