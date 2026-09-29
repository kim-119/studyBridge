export const LEARNING_MODE_OPTIONS = [
  {
    value: 'basic',
    title: '기본 설명',
    desc: '개념을 빠르게 정리하고 예시와 함께 설명합니다.',
    result: '개념 정리 · 예시 · 핵심 요약',
  },
  {
    value: 'socratic',
    title: '소크라테스',
    desc: '정답을 바로 주지 않고 질문과 힌트로 이해를 유도합니다.',
    result: '단계별 질문 · 힌트 · 오개념 확인',
  },
  {
    value: 'debate',
    title: '토론',
    desc: '장점, 단점, 반론을 비교하며 사고를 넓힙니다.',
    result: '주장 · 근거 · 반박 · 결론',
  },
  {
    value: 'simulation',
    title: '상황극',
    desc: '현실 상황 속 역할을 맡아 개념을 체험합니다.',
    result: '시나리오 · 선택지 · 피드백',
  },
];

export const MODE_SETTING_INTRO = {
  basic: {
    title: '기본 설명 모드',
    desc: 'AI들이 사용자의 질문을 중심으로 개념을 정리하고, 예시와 핵심 요약을 제공합니다.',
  },
  socratic: {
    title: '소크라테스 모드',
    desc: 'AI가 정답을 바로 알려주기보다 질문과 힌트로 사용자의 이해를 유도합니다.',
  },
  debate: {
    title: '토론 모드',
    desc: '채팅에 입력하는 메시지가 곧 논제입니다. 두 입장이 입론 → 상호 반박 → 예외 정리 → 하나의 최종 결론 순으로 진행합니다.',
  },
  simulation: {
    title: '상황극 모드',
    desc: 'AI가 현실적인 상황을 만들고, 사용자가 선택과 피드백을 통해 개념을 체험하도록 진행합니다.',
  },
};

export const DEFAULT_DEBATE_CONFIG = { debateStrength: 'normal' };
export const DEFAULT_SOCRATIC_CONFIG = { questionIntensity: 'normal', hintPolicy: 'concept' };
export const DEFAULT_SIMULATION_CONFIG = {
  scenarioType: 'realistic',
  difficulty: 'normal',
  choiceCount: 3,
  userRoleMode: 'auto',
};

export const DEBATE_STRENGTH_LABELS = { light: '가볍게', normal: '보통', deep: '깊게' };
export const QUESTION_INTENSITY_LABELS = { gentle: '부드럽게', normal: '보통', intensive: '집중적으로' };
export const HINT_STYLE_LABELS = {
  concept: '개념 힌트',
  example: '예시 힌트',
  choice: '선택지 힌트',
  counterexample: '반례 힌트',
  step: '단계별 힌트',
};
export const SCENARIO_TYPE_LABELS = { realistic: '현실', interview: '면접', project: '프로젝트' };
export const DIFFICULTY_LABELS = { easy: '쉬움', normal: '보통', hard: '어려움' };
export const CHOICE_COUNT_OPTIONS = [2, 3, 4];

function toOptions(labels) {
  return Object.entries(labels).map(([value, label]) => ({ value, label }));
}

export const DEBATE_STRENGTH_OPTIONS = toOptions(DEBATE_STRENGTH_LABELS);
export const QUESTION_INTENSITY_OPTIONS = toOptions(QUESTION_INTENSITY_LABELS);
export const HINT_STYLE_OPTIONS = toOptions(HINT_STYLE_LABELS);
export const SCENARIO_TYPE_OPTIONS = toOptions(SCENARIO_TYPE_LABELS);
export const DIFFICULTY_OPTIONS = toOptions(DIFFICULTY_LABELS);

export function normalizeLearningMode(mode) {
  const value = String(mode || '').toLowerCase();
  if (value.includes('socratic') || value.includes('소크라테스')) return 'socratic';
  if (value.includes('debate') || value.includes('토론')) return 'debate';
  if (value.includes('simulation') || value.includes('상황극') || value.includes('시뮬레이션')) return 'simulation';
  return 'basic';
}

function labelOr(labels, value, fallback) {
  return labels[String(value || '').toLowerCase()] || (value ? String(value) : fallback);
}

function describeDebateRoom(room) {
  const config = room?.debateConfig || {};
  return {
    label: '토론 모드',
    badge: '입론 · 상호반박 · 예외 정리 · 최종 결론',
    rows: [
      { key: '토론 강도', value: labelOr(DEBATE_STRENGTH_LABELS, config.debateStrength ?? config.debateDepth, '보통') },
      { key: '논제', value: '채팅에 입력한 메시지' },
    ],
  };
}

function describeSocraticRoom(room) {
  const config = room?.socraticConfig || {};
  return {
    label: '소크라테스 모드',
    badge: '질문 · 힌트 · 자기설명',
    rows: [
      { key: '질문 강도', value: labelOr(QUESTION_INTENSITY_LABELS, config.questionIntensity, '보통') },
      { key: '힌트 방식', value: labelOr(HINT_STYLE_LABELS, config.hintPolicy, '개념 힌트') },
    ],
  };
}

function describeSimulationRoom(room) {
  const config = room?.simulationConfig || {};
  return {
    label: '상황극 모드',
    badge: '상황 · 선택 · 피드백',
    rows: [
      { key: '상황 유형', value: labelOr(SCENARIO_TYPE_LABELS, config.scenarioType, '현실') },
      { key: '난이도', value: labelOr(DIFFICULTY_LABELS, config.difficulty, '보통') },
      { key: '선택지 개수', value: `${Number(config.choiceCount) || 3}개` },
    ],
  };
}

function describeBasicRoom() {
  return {
    label: '기본 설명 모드',
    badge: '개념 정리 · 예시 · 핵심 요약',
    rows: [{ key: '답변 구조', value: '개념 정리 · 예시 · 핵심 요약' }],
  };
}

export function describeRoomMode(room) {
  const mode = normalizeLearningMode(room?.learningMode || room?.mode);
  if (mode === 'debate') return describeDebateRoom(room);
  if (mode === 'socratic') return describeSocraticRoom(room);
  if (mode === 'simulation') return describeSimulationRoom(room);
  return describeBasicRoom();
}

export function summarizeRoomPreset(preset) {
  const chips = [];
  if (preset.mode === 'socratic') {
    chips.push(`질문 ${QUESTION_INTENSITY_LABELS[preset.questionIntensity] || preset.questionIntensity}`);
    chips.push(`힌트 ${HINT_STYLE_LABELS[preset.hintPolicy] || preset.hintPolicy}`);
  }
  if (preset.mode === 'debate') {
    chips.push(`강도 ${DEBATE_STRENGTH_LABELS[preset.debateStrength] || preset.debateStrength}`);
  }
  if (preset.mode === 'simulation') {
    chips.push(`상황 ${SCENARIO_TYPE_LABELS[preset.scenarioType] || preset.scenarioType}`);
    chips.push(`난이도 ${DIFFICULTY_LABELS[preset.difficulty] || preset.difficulty}`);
  }
  chips.push('에이전트 3인 개별 톤');
  return chips;
}
