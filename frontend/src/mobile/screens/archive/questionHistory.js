export const QUESTION_INTRO = '업로드한 자료를 바탕으로 궁금한 점을 질문해보세요.';

export const SENDER = {
  USER: 'user',
  AI: 'ai',
};

const ROUTE_TAB_HINT = {
  QUIZ_PIPELINE: { fallback: '문제를 생성했습니다.', tab: '퀴즈' },
  SUMMARY_PIPELINE: { fallback: '요약을 정리했습니다.', tab: '요약' },
  ROADMAP_PIPELINE: { fallback: '로드맵을 불러왔습니다.', tab: '로드맵' },
};

export function historyStorageKey(materialId) {
  return `studybridge:material-chat:${materialId}`;
}

function introMessage() {
  return { sender: SENDER.AI, text: QUESTION_INTRO };
}

function isStoredMessage(message) {
  return Boolean(message) && typeof message.text === 'string' && typeof message.sender === 'string';
}

export function loadHistory(materialId) {
  try {
    const raw = window.localStorage.getItem(historyStorageKey(materialId));
    const saved = raw ? JSON.parse(raw) : null;
    if (Array.isArray(saved) && saved.length > 0) return saved.filter(isStoredMessage);
  } catch {
    return [introMessage()];
  }
  return [introMessage()];
}

export function saveHistory(materialId, messages) {
  const persisted = messages.filter((message) => !message.isThinking);
  try {
    window.localStorage.setItem(historyStorageKey(materialId), JSON.stringify(persisted));
    return true;
  } catch {
    return false;
  }
}

let messageSequence = 0;

export function createMessage(sender, text, materialId, extra = {}) {
  messageSequence += 1;
  return {
    id: `${Date.now()}-${messageSequence}`,
    sender,
    text,
    createdAt: new Date().toISOString(),
    materialId: String(materialId),
    ...extra,
  };
}

export function messageKey(message, index) {
  return message.id || `${index}-${message.createdAt || 'intro'}`;
}

export function answerTextOf(response) {
  const routeAction = response?.routeAction;
  const answer = response?.aiAnswer || '';

  if (routeAction === 'WARN' && response.routeMessage) {
    return `${response.routeMessage}\n\n${answer}`.trim();
  }

  const hint = ROUTE_TAB_HINT[routeAction];
  if (hint) return `${answer || hint.fallback} 상단 ‘${hint.tab}’ 탭에서 확인하세요.`;

  return answer || '문서 기준으로는 확인되지 않습니다.';
}
