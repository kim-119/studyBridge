import { reorderHistoryByRequest } from '../../../utils/studymate/historyOrder.js';

export const FAILED_AGENT_TEXT = '응답 생성에 실패했습니다. 다시 시도해 주세요.';

const UNUSABLE_AGENT_TEXT_PATTERNS = [
  /빈\s*응답을\s*반환/, /모델이\s*빈\s*응답/, /응답이\s*비어/,
  /empty\s*response/i, /returned\s+an?\s+empty/i, /no\s+(valid\s+)?response\s+(was\s+)?generated/i,
  /Authorization\s*헤더/i, /AI\s*서버\s*인증/i, /인증에?\s*실패/, /OPENAI_API_KEY/i, /TAVILY_API_KEY/i,
  /Traceback\s*\(most recent\s*call/i, /Internal\s*Server\s*Error/i,
  /Connection\s*refused/i, /\bECONNREFUSED\b/i,
];

const STAGE_BADGE_TITLES = {
  initial: '⚡ 1차 · 빠른 초안',
  validated: '✅ 2차 · 검증 답안',
  feedback: '💬 3차 · 상호 피드백',
  d_initial: '🗣 1차 입론 · 주장',
  d_feedback: '⚔️ 반박',
  d_revised: '🎯 최종 변론',
  d_summary: '⚖️ 심사 정리 · 판단은 당신 몫',
};

const SOCRATIC_STAGE_TITLES = {
  DIAGNOSIS: '현재 이해도 진단',
  CORE_CONCEPT: '핵심 개념 질문',
  MISCONCEPTION_CHECK: '오개념 점검',
  HINT: '단계별 힌트',
  APPLICATION: '적용 질문',
  COUNTEREXAMPLE: '반례 질문',
  SELF_EXPLANATION: '자기 설명 유도',
  SUMMARY: '정리 및 다음 학습 방향',
  NEXT_STUDY_PLAN: '다음 학습 방향',
};

const SIMULATION_STAGE_TITLES = {
  SCENARIO_SETUP: '상황 설정',
  USER_ROLE: '나의 역할',
  SITUATION_CONTEXT: '문제 상황',
  CHOICES: '선택지',
  SELECTED_CHOICE: '선택한 행동',
  CONSEQUENCE_PREVIEW: '결과 변화',
  CONSEQUENCE: '선택 결과',
  CONCEPT_MAPPING: '개념 연결',
  CONCEPT_EXPLANATION: '개념 설명',
  MISCONCEPTION_TRAP: '오개념 함정',
  RISK_OR_LIMITATION: '위험과 한계',
  REFLECTION_QUESTION: '성찰 질문',
  NEXT_SCENARIO: '다음 분기',
  NEXT_BRANCH: '다음 사건',
  SCENE_SETUP: '상황 제시',
  CHALLENGE: '심화 검증',
  FEEDBACK: '피드백',
  NEXT_SCENE: '다음 장면',
  SUMMARY: '상황극 요약',
};

const DEBATE_STAGE_BASE_TITLES = {
  OPENING_STATEMENT: '입론',
  REBUTTAL: '반박',
  CROSS_REBUTTAL: '재반박',
  CLOSING_STATEMENT: '최종 변론',
};

const DEBATE_SIDE_PREFIX = { PRO: '찬성측', CON: '반대측', NEUTRAL: '중립' };

export const TURN_KIND_LABELS = { debate: '토론', socratic: '소크라테스', simulation: '상황극' };

export function isUserMessage(message) {
  return String(message?.sender || '').toUpperCase() === 'USER';
}

export function coerceAgentText(raw) {
  const text = String(raw ?? '').trim();
  const unusable = !text || UNUSABLE_AGENT_TEXT_PATTERNS.some((pattern) => pattern.test(text));
  return unusable ? { ok: false, text: FAILED_AGENT_TEXT } : { ok: true, text: String(raw) };
}

export function stripLegacyActBadge(text) {
  return String(text ?? '').replace(/^>\s*(💬|🧩)[^\n]*\n+/u, '');
}

function stepContent(row) {
  return row?.content ?? row?.answer ?? row?.feedback ?? '';
}

function agentOrderOf(row) {
  return Number(row.agentIndex ?? row.displayOrder ?? row.agentOrder ?? row.fromAgentIndex ?? row.agentId ?? 999);
}

export function sortByAgentOrder(rows) {
  return [...(rows || [])].sort((a, b) => agentOrderOf(a) - agentOrderOf(b));
}

export function sortByDisplayOrder(rows) {
  return (rows || [])
    .map((row, index) => [row, index])
    .sort(([rowA, indexA], [rowB, indexB]) => {
      const orderA = Number(rowA?.displayOrder ?? Number.POSITIVE_INFINITY);
      const orderB = Number(rowB?.displayOrder ?? Number.POSITIVE_INFINITY);
      return orderA !== orderB ? orderA - orderB : indexA - indexB;
    })
    .map(([row]) => row);
}

export function isInternalVisibleMode(mode) {
  const value = String(mode || '').toLowerCase();
  return ['validation', '검증', 'collaboration', 'collaborative', '협업'].includes(value);
}

export function debateStageTitle(side, stageType) {
  if (stageType === 'TOPIC') return '논제';
  if (stageType === 'JUDGEMENT') return '중립 판정';
  if (stageType === 'NEUTRAL_ANALYSIS') return '중립 쟁점 정리';
  if (stageType === 'NEUTRAL_CHECK') return '중립 검토';

  const base = DEBATE_STAGE_BASE_TITLES[stageType] || stageType;
  return `${DEBATE_SIDE_PREFIX[side] || ''} ${base}`.trim();
}

export function socraticStageTitle(stageType) {
  return SOCRATIC_STAGE_TITLES[stageType] || stageType;
}

export function simulationStageTitle(stageType) {
  return SIMULATION_STAGE_TITLES[stageType] || stageType || '상황극 요약';
}

function toTurnStage(stage, title) {
  return {
    stageType: stage.stageType,
    speechType: stage.speechType,
    consensus: stage.consensus === true,
    title,
    side: stage.side,
    agentId: stage.agentId,
    agentIndex: stage.agentIndex,
    agentName: stage.agentName,
    content: stage.content ?? stage.text ?? stage.answer ?? stage.feedback ?? stage.question ?? stage.hint ?? '',
    choices: Array.isArray(stage.choices) ? stage.choices : [],
  };
}

export function normalizeDebateStages(message) {
  const stages = message?.debateStages || message?.processSteps?.debateStages || message?.debate?.debateStages;
  if (!Array.isArray(stages) || stages.length === 0) return null;
  return stages.map((stage) =>
    toTurnStage(stage, stage.stageTitle || stage.title || debateStageTitle(stage.side, stage.stageType))
  );
}

function firstAnswerOf(message) {
  return message?.content || message?.answer || (Array.isArray(message?.answers) ? message.answers[0]?.answer : '');
}

export function normalizeSocraticSteps(message) {
  const steps =
    message?.socraticSteps ||
    message?.socratic?.socraticSteps ||
    message?.processSteps?.socraticSteps ||
    (Array.isArray(message?.answers) ? message.answers[0]?.socraticSteps : null);

  if (Array.isArray(steps) && steps.length > 0) {
    return steps.map((step) => toTurnStage(step, step.stageTitle || socraticStageTitle(step.stageType)));
  }

  const answer = firstAnswerOf(message);
  if (message?.isSocratic && answer) {
    return [toTurnStage({ stageType: 'SUMMARY', agentIndex: 3, content: answer }, socraticStageTitle('SUMMARY'))];
  }
  return null;
}

export function normalizeSimulationStages(message) {
  const stages =
    message?.simulationStages ||
    message?.simulation?.simulationStages ||
    message?.processSteps?.simulationStages ||
    (Array.isArray(message?.answers) ? message.answers[0]?.simulationStages : null);

  if (Array.isArray(stages) && stages.length > 0) {
    return stages.map((stage) =>
      toTurnStage({ ...stage, stageType: stage.stageType || 'SUMMARY' }, stage.stageTitle || simulationStageTitle(stage.stageType))
    );
  }

  const answer = firstAnswerOf(message);
  const isSimulation = message?.isSimulation || String(message?.mode || message?.learningMode || '').toLowerCase() === 'simulation';
  if (isSimulation && answer) {
    return [toTurnStage({ stageType: 'SUMMARY', agentIndex: 3, content: answer }, simulationStageTitle('SUMMARY'))];
  }
  return null;
}

export function buildTurnMessage(turnKind, stages, parentId, createdAt) {
  return {
    id: `${parentId}::${turnKind}`,
    sender: 'AI',
    senderName: TURN_KIND_LABELS[turnKind],
    content: TURN_KIND_LABELS[turnKind],
    createdAt: createdAt || new Date().toISOString(),
    parentId,
    turnKind,
    stages,
  };
}

function stageBubble({ key, name, content, parentId, createdAt, index, extra = {} }) {
  return {
    id: `${parentId}::${name}::${key}::${index}`,
    sender: 'AI',
    senderName: name,
    content,
    stageTitle: STAGE_BADGE_TITLES[key],
    createdAt,
    parentId,
    ...extra,
  };
}

function debateStageBubbles(steps, parentId, createdAt) {
  const bubbles = [];
  sortByAgentOrder(steps.initialAnswers).forEach((row, index) => {
    bubbles.push(stageBubble({ key: 'd_initial', name: row.agentName, content: stepContent(row), parentId, createdAt, index }));
  });
  sortByAgentOrder(steps.peerFeedback).forEach((row, index) => {
    bubbles.push(stageBubble({ key: 'd_feedback', name: row.fromAgent, content: stepContent(row), parentId, createdAt, index }));
  });
  sortByAgentOrder(steps.revisedAnswers).forEach((row, index) => {
    bubbles.push(stageBubble({ key: 'd_revised', name: row.agentName, content: stepContent(row), parentId, createdAt, index }));
  });
  if (steps.debateSummary) {
    bubbles.push(stageBubble({ key: 'd_summary', name: '토론 정리', content: steps.debateSummary, parentId, createdAt, index: 0 }));
  }
  return bubbles;
}

function staticStageBubble(key, row, name, parentId, createdAt, index) {
  const coerced = coerceAgentText(stepContent(row));
  return stageBubble({
    key,
    name,
    content: coerced.text,
    parentId,
    createdAt,
    index,
    extra: { isError: !coerced.ok, agentId: row.agentId, agentIndex: row.agentIndex },
  });
}

export function buildStageBubbles(steps, parentId, createdAt, { showInternal = false } = {}) {
  if (!steps) return [];
  const timestamp = createdAt || new Date().toISOString();

  const isDebate = (steps.revisedAnswers && steps.revisedAnswers.length > 0) || Boolean(steps.debateSummary);
  if (isDebate) return debateStageBubbles(steps, parentId, timestamp);

  const bubbles = sortByAgentOrder(steps.initialAnswers).map((row, index) =>
    staticStageBubble('initial', row, row.agentName, parentId, timestamp, index)
  );
  if (!showInternal) return bubbles;

  sortByAgentOrder(steps.validatedAnswers).forEach((row, index) => {
    bubbles.push(staticStageBubble('validated', row, row.agentName, parentId, timestamp, index));
  });
  sortByAgentOrder(steps.peerFeedback).forEach((row, index) => {
    bubbles.push(staticStageBubble('feedback', row, row.fromAgent, parentId, timestamp, index));
  });
  return bubbles;
}

function structuredTurnOf(row) {
  const debateStages = normalizeDebateStages(row);
  if (debateStages) return { turnKind: 'debate', stages: debateStages };

  const socraticSteps = normalizeSocraticSteps(row);
  if (socraticSteps) return { turnKind: 'socratic', stages: socraticSteps };

  const simulationStages = normalizeSimulationStages(row);
  if (simulationStages) return { turnKind: 'simulation', stages: simulationStages };

  return null;
}

function turnKeyOf(row, fallback) {
  return row.parentId ?? row.requestId ?? fallback;
}

function hasProcessStages(steps) {
  return Boolean(
    steps &&
      ((steps.initialAnswers && steps.initialAnswers.length) ||
        (steps.validatedAnswers && steps.validatedAnswers.length) ||
        (steps.peerFeedback && steps.peerFeedback.length))
  );
}

function explodeAiRow(row, seenTurns) {
  const structured = structuredTurnOf(row);
  if (structured) {
    const contentKey = `${structured.turnKind}::${structured.stages[0]?.content || ''}`.slice(0, 240);
    const turnKey = turnKeyOf(row, contentKey);
    if (seenTurns.has(turnKey)) return [];
    seenTurns.add(turnKey);
    return [{ ...buildTurnMessage(structured.turnKind, structured.stages, turnKey, row.createdAt), id: row.id ?? turnKey }];
  }

  if (hasProcessStages(row.processSteps)) {
    const turnKey = turnKeyOf(row, row.id);
    if (seenTurns.has(turnKey)) return [];
    seenTurns.add(turnKey);
    const bubbles = buildStageBubbles(row.processSteps, turnKey, row.createdAt, {
      showInternal: isInternalVisibleMode(row.mode || row.learningMode),
    });
    if (bubbles.length) return bubbles;
  }

  return [row];
}

export function historyToMessages(history) {
  const rows = Array.isArray(history) ? history : history?.messages || [];
  const ordered = reorderHistoryByRequest(rows.filter(Boolean));
  const seenTurns = new Set();

  return ordered.flatMap((row, index) => {
    const base = { ...row, id: row.id ?? `history-${index}`, content: row.content ?? row.message ?? '' };
    if (isUserMessage(base)) return [{ ...base, sender: 'USER' }];
    return explodeAiRow({ ...base, sender: 'AI' }, seenTurns);
  });
}

export function replaceTurnMessages(messages, parentId, turnMessages) {
  const kept = messages.filter((message) => !(message.sender === 'AI' && message.parentId === parentId));
  return [...kept, ...turnMessages];
}

export function appendUnique(messages, message) {
  return messages.some((existing) => existing.id === message.id) ? messages : [...messages, message];
}

export function closePendingMessages(messages, parentId) {
  return messages.map((message) =>
    message.sender === 'AI' && message.parentId === parentId && message.isPending
      ? { ...message, isPending: false, isCancelled: true, statusText: '', content: message.content || '답변 생성을 중단했어요.' }
      : message
  );
}

export function removeFailedTurn(messages, notice) {
  const failedUserId = String(notice.parentId || '').replace(/::notice$/, '') || null;
  const turnHasAnswer =
    !failedUserId ||
    messages.some(
      (message) => message.sender === 'AI' && message.parentId === failedUserId && !message.isError && !message.isNotice && !message.isPending
    );

  return messages.filter((message) => {
    if (message.id === notice.id) return false;
    return turnHasAnswer || message.id !== failedUserId || !isUserMessage(message);
  });
}

export function mergeLiveMessages(historyMessages, liveMessages) {
  const historyIds = new Set(historyMessages.map((message) => String(message.id)));
  return [...historyMessages, ...liveMessages.filter((message) => !historyIds.has(String(message.id)))];
}

function structuredTurnCount(messages) {
  return messages.filter((message) => message.sender === 'AI' && message.turnKind).length;
}

export function reconcileHistory(serverMessages, localMessages) {
  const server = Array.isArray(serverMessages) ? serverMessages : [];
  const local = Array.isArray(localMessages) ? localMessages : [];
  if (structuredTurnCount(local) > structuredTurnCount(server)) return local;
  return server.length >= local.length ? server : local;
}

export function lastRealMessage(messages) {
  return [...(messages || [])].reverse().find((message) => !message.isNotice && !message.isError && !message.isPending) || null;
}

export function isAnswerMessage(message) {
  return Boolean(message) && !isUserMessage(message) && !message.isNotice && !message.isPending && !message.isError;
}

export function mindmapSourceMessages(messages) {
  return (messages || []).filter((message) => isUserMessage(message) || (isAnswerMessage(message) && !message.turnKind));
}

export function latestUserQuestion(messages) {
  const lastUser = [...(messages || [])].reverse().find(isUserMessage);
  return lastUser?.content || '';
}

export function latestAnswer(messages) {
  return [...(messages || [])].reverse().find((message) => isAnswerMessage(message) && message.content) || null;
}
