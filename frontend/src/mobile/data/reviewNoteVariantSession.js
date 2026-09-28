const STORAGE_PREFIX = 'studybridge:review-note-variant:';
const SESSION_VERSION = 1;

export function variantSessionKey(reviewNoteId) {
  return `${STORAGE_PREFIX}${reviewNoteId}`;
}

export function createEmptyVariantSession(settings) {
  return {
    settings: { ...settings },
    lastRequest: null,
    questions: [],
    usedFallback: false,
    hasResult: false,
    activeId: null,
    answers: {},
    submitted: {},
  };
}

function browserSessionStorage() {
  try {
    return typeof window !== 'undefined' ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isStoredQuestion(question) {
  return isPlainObject(question) && typeof question.id === 'string' && Array.isArray(question.choices);
}

function pickAnswers(answers) {
  if (!isPlainObject(answers)) return {};
  return Object.fromEntries(
    Object.entries(answers).filter(([, index]) => Number.isInteger(index) && index >= 0)
  );
}

function pickSubmitted(submitted) {
  if (!isPlainObject(submitted)) return {};
  return Object.fromEntries(Object.entries(submitted).filter(([, flag]) => flag === true));
}

function pickLastRequest(lastRequest) {
  if (!isPlainObject(lastRequest) || !Number.isInteger(lastRequest.count) || lastRequest.count < 1) return null;
  return {
    wrongQuestionId: Number(lastRequest.wrongQuestionId) || 1,
    difficulty: String(lastRequest.difficulty || ''),
    count: lastRequest.count,
  };
}

export function serializeVariantSession(session) {
  return JSON.stringify({
    version: SESSION_VERSION,
    settings: session.settings,
    lastRequest: session.lastRequest,
    questions: session.questions,
    usedFallback: session.usedFallback,
    hasResult: session.hasResult,
    activeId: session.activeId,
    answers: session.answers,
    submitted: session.submitted,
  });
}

export function parseVariantSession(raw, defaultSettings) {
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return null;
  }

  if (!isPlainObject(parsed) || parsed.version !== SESSION_VERSION) return null;
  if (!Array.isArray(parsed.questions) || !parsed.questions.every(isStoredQuestion)) return null;

  const questionIds = new Set(parsed.questions.map((question) => question.id));
  const activeId = questionIds.has(parsed.activeId) ? parsed.activeId : parsed.questions[0]?.id ?? null;

  return {
    settings: { ...defaultSettings, ...(isPlainObject(parsed.settings) ? parsed.settings : {}) },
    lastRequest: pickLastRequest(parsed.lastRequest),
    questions: parsed.questions,
    usedFallback: parsed.usedFallback === true,
    hasResult: parsed.hasResult === true,
    activeId,
    answers: pickAnswers(parsed.answers),
    submitted: pickSubmitted(parsed.submitted),
  };
}

export function loadVariantSession(reviewNoteId, defaultSettings, storage = browserSessionStorage()) {
  const emptySession = createEmptyVariantSession(defaultSettings);
  if (!storage || reviewNoteId == null) return emptySession;

  try {
    const raw = storage.getItem(variantSessionKey(reviewNoteId));
    if (!raw) return emptySession;
    return parseVariantSession(raw, defaultSettings) || emptySession;
  } catch {
    return emptySession;
  }
}

export function saveVariantSession(reviewNoteId, session, storage = browserSessionStorage()) {
  if (!storage || reviewNoteId == null) return false;

  try {
    storage.setItem(variantSessionKey(reviewNoteId), serializeVariantSession(session));
    return true;
  } catch {
    return false;
  }
}

export function clearVariantSession(reviewNoteId, storage = browserSessionStorage()) {
  if (!storage || reviewNoteId == null) return false;

  try {
    storage.removeItem(variantSessionKey(reviewNoteId));
    return true;
  } catch {
    return false;
  }
}
