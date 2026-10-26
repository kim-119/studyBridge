import { isEventForTarget, resolveRoomAgentSlot } from '../../../utils/agentIdentity.js';
import {
  buildStageBubbles,
  buildTurnMessage,
  coerceAgentText,
  debateStageTitle,
  isInternalVisibleMode,
  normalizeDebateStages,
  normalizeSimulationStages,
  normalizeSocraticSteps,
  simulationStageTitle,
  socraticStageTitle,
  sortByAgentOrder,
  sortByDisplayOrder,
} from './chatMessages.js';

const MODE_LABELS = { socratic: '소크라테스', debate: '토론', simulation: '상황극', basic: '기본' };
const MODE_GUARD_MESSAGES = { NON_LEARNING_INPUT: '학습할 개념, 문제, 비교 논제 또는 연습 상황을 입력해 주세요.' };
const MODE_ERROR_CODE = /^(DEBATE|SOCRATIC|SIMULATION)_/;
const EMPTY_TURN_TEXT = 'AI 응답을 받지 못했습니다. 잠시 후 다시 시도해주세요.';

function statusOf(data) {
  return String(data?.status || '').toUpperCase();
}

function isFailedStatus(data) {
  return data?.success === false || ['FAILED', 'ERROR'].includes(statusOf(data));
}

export function isModeGuardPayload(data) {
  if (!data) return false;
  if (data.blocked === true || statusOf(data) === 'BLOCKED') return true;
  if (data.code && MODE_GUARD_MESSAGES[data.code]) return true;
  return Boolean(data.code) && MODE_ERROR_CODE.test(String(data.code)) && isFailedStatus(data);
}

export function isModeErrorPayload(data) {
  return Boolean(data?.code) && (MODE_ERROR_CODE.test(String(data.code)) || isFailedStatus(data));
}

export function modeGuardText(data, mode) {
  const base = data?.message || data?.content || MODE_GUARD_MESSAGES[data?.code] || '이 모드에서 처리할 수 없는 입력입니다.';
  const label = MODE_LABELS[mode] || '';
  return label ? `[${label} 모드] ${base}` : base;
}

function toList(value) {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (typeof value === 'string' && value.trim()) return [value.trim()];
  return [];
}

function validationSourceOf(data) {
  if (data.validation && typeof data.validation === 'object') return data.validation;
  if (data.hallucinationCheck && typeof data.hallucinationCheck === 'object') return data.hallucinationCheck;
  if (data.hallucination_check && typeof data.hallucination_check === 'object') return data.hallucination_check;
  return data;
}

export function extractValidation(data) {
  if (!data || typeof data !== 'object') return null;

  const source = validationSourceOf(data);
  const rawScore = source.factualityScore ?? source.factuality_score ?? source.factuality;
  const risk = source.riskLevel ?? source.risk_level ?? source.risk ?? source.hallucinationRisk ?? source.hallucination_risk;
  const score = rawScore != null && rawScore !== '' && !Number.isNaN(Number(rawScore)) ? Number(rawScore) : null;
  const unsupportedClaims = toList(source.unsupportedClaims ?? source.unsupported_claims);
  const contradictions = toList(source.contradictions ?? source.contradiction);
  const evidenceNotes = [
    ...toList(source.evidenceNotes ?? source.evidence_notes ?? source.notes),
    ...toList(source.missingEvidenceNotes ?? source.missing_evidence_notes),
  ];
  const hint = source.safeRevisionHint ?? source.safe_revision_hint;
  const safeRevisionHint = typeof hint === 'string' && hint.trim() ? hint.trim() : null;

  const isEmpty =
    score == null && risk == null && !unsupportedClaims.length && !contradictions.length && !evidenceNotes.length && !safeRevisionHint;
  if (isEmpty) return null;

  return {
    factualityScore: score,
    riskLevel: risk != null ? String(risk).toLowerCase() : null,
    unsupportedClaims,
    contradictions,
    evidenceNotes,
    safeRevisionHint,
  };
}

function contentHash(text) {
  let hash = 0;
  const value = String(text || '');
  for (let index = 0; index < value.length; index += 1) hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
  return String(hash);
}

function isDeltaPayload(data) {
  return Boolean(data && (data.delta === true || data.isDelta === true || data.chunk === true || data.partial === true));
}

export function createTurnState({ parentId, requestId, roomAgents, target, mode, fallbackAgentName }) {
  return {
    parentId,
    requestId,
    agents: Array.isArray(roomAgents) ? roomAgents : [],
    target,
    mode,
    fallbackAgentName: fallbackAgentName || 'StudyMate',
    createdAt: new Date().toISOString(),
    answers: new Map(),
    debateStages: new Map(),
    socraticSteps: new Map(),
    simulationStages: new Map(),
    processSteps: { initialAnswers: [], validatedAnswers: [], peerFeedback: [] },
    rendered: false,
    completed: false,
    routedTerminal: false,
    modeGuardShown: false,
    messages: [],
  };
}

export function slotOfEvent(turn, data) {
  const slot = resolveRoomAgentSlot(turn.agents, data);
  return slot >= 0 ? slot : null;
}

export function isEventForTurnTarget(turn, data = {}, patch = {}) {
  if (turn.target?.scope !== 'single') return true;
  return isEventForTarget(turn.agents, turn.target.mention, {
    agentId: data?.agentId ?? patch?.agentId,
    agentName: data?.agentName ?? data?.agent_name ?? patch?.agentName,
    agentIndex: data?.agentIndex ?? patch?.agentIndex,
    agentSlot: data?.agentSlot ?? patch?.agentSlot,
  });
}

function scopeRows(turn, rows) {
  if (turn.target?.scope !== 'single' || !Array.isArray(rows)) return rows || [];
  return rows.filter((row, index) =>
    isEventForTurnTarget(turn, {
      agentIndex: row?.agentIndex ?? index + 1,
      agentId: row?.agentId,
      agentName: row?.agentName || row?.agent_name,
    })
  );
}

function publish(turn, messages) {
  turn.messages = messages.map((message) => (message.mode == null ? { ...message, mode: turn.mode } : message));
  turn.rendered = true;
  return turn.messages;
}

function answerList(turn) {
  return sortByDisplayOrder(Array.from(turn.answers.values()));
}

function answerKeyOf(turn, data, patch) {
  const index = data?.agentIndex ?? patch.agentIndex ?? 0;
  const agentId = data?.agentId ?? patch.agentId ?? index;
  const actType = data?.actType ?? patch.actType ?? '';
  const order = data?.displayOrder ?? patch.displayOrder ?? '';
  const segment = actType ? `${actType}::${order}` : data?.stageType || 'FIRST_DRAFT';
  return `${data?.requestId || turn.requestId}::basic::${segment}::${index}::${agentId}`;
}

function answerContentOf(data, patch, previous) {
  const incoming = data?.content ?? data?.answer ?? patch.content ?? '';
  const raw = isDeltaPayload(data) && previous && !previous.isPending ? `${previous.content || ''}${incoming}` : incoming;
  return patch.isPending || patch.isError ? { ok: !patch.isError, text: raw } : coerceAgentText(raw);
}

function upsertAnswer(turn, data, patch = {}) {
  if (turn.completed || !isEventForTurnTarget(turn, data, patch)) return null;

  const key = answerKeyOf(turn, data, patch);
  const index = data?.agentIndex ?? patch.agentIndex ?? 0;
  const content = answerContentOf(data, patch, turn.answers.get(key));
  const slot = slotOfEvent(turn, {
    agentId: data?.agentId ?? patch.agentId,
    agentName: data?.agentName ?? patch.agentName,
    agentIndex: index,
  });

  turn.answers.set(key, {
    id: key,
    sender: 'AI',
    senderName: data?.agentName || patch.agentName || turn.fallbackAgentName,
    content: content.text,
    agentId: data?.agentId ?? patch.agentId ?? index,
    agentIndex: slot ?? index,
    agentSlot: slot ?? undefined,
    displayOrder: Number(data?.displayOrder ?? patch.displayOrder ?? 0) || undefined,
    stageType: data?.stageType || 'FIRST_DRAFT',
    actType: data?.actType ?? patch.actType ?? undefined,
    replyTo: data?.replyTo ?? patch.replyTo ?? undefined,
    replyToName: data?.replyToName ?? patch.replyToName ?? undefined,
    createdAt: data?.createdAt || turn.createdAt,
    parentId: turn.parentId,
    requestId: data?.requestId || turn.requestId,
    isPending: Boolean(patch.isPending),
    isError: Boolean(patch.isError) || !content.ok,
    statusText: patch.statusText || '',
    failureCode: patch.failureCode ?? data?.failureCode ?? data?.code,
    validation: extractValidation(data),
  });

  return publish(turn, answerList(turn));
}

export function applyModeGuard(turn, data, options) {
  turn.modeGuardShown = true;
  const isError = options?.isError ?? (isModeErrorPayload(data) && statusOf(data) !== 'BLOCKED');
  return publish(turn, [
    {
      id: `${turn.parentId}::mode-guard`,
      sender: 'AI',
      senderName: `${MODE_LABELS[turn.mode] || '학습'} 모드 안내`,
      content: modeGuardText(data, turn.mode),
      isNotice: true,
      isModeGuard: true,
      isError,
      createdAt: new Date().toISOString(),
      parentId: turn.parentId,
    },
  ]);
}

export function applyAgentStart(turn, data) {
  return upsertAnswer(turn, data, { isPending: true, content: '답변 생성 중…' });
}

function replyToNameOf(turn, data) {
  if (data.actType !== 'REACTION') return '';
  return answerList(turn).find((message) => message.agentId === data.replyTo)?.senderName || '';
}

export function applyAgentAnswer(turn, data) {
  if (turn.modeGuardShown || isModeGuardPayload(data)) return applyModeGuard(turn, data);
  const shown = data.content || data.answer || '';
  return upsertAnswer(
    turn,
    { ...data, content: shown, answer: shown, replyToName: replyToNameOf(turn, data) },
    { isPending: false, content: shown }
  );
}

export function applyAgentError(turn, data, message, failureCode) {
  return upsertAnswer(turn, data, { isPending: false, isError: true, content: message, statusText: '', failureCode });
}

export function applyHeartbeat(turn, data) {
  if (turn.completed || data?.agentIndex == null) return null;
  const segment = `::${data.agentIndex}::`;
  const entry = Array.from(turn.answers.entries()).find(([key, value]) => key.includes(segment) && value.isPending);
  if (!entry) return null;
  turn.answers.set(entry[0], { ...entry[1], statusText: data.message || '답변 생성 중입니다.' });
  return publish(turn, answerList(turn));
}

export function markPendingAnswers(turn, statusText) {
  const pending = Array.from(turn.answers.entries()).filter(([, value]) => value.isPending);
  if (!pending.length) return null;
  pending.forEach(([key, value]) => turn.answers.set(key, { ...value, statusText }));
  return publish(turn, answerList(turn));
}

function mergeStageRows(turn, data) {
  const steps = turn.processSteps;
  const answers = sortByAgentOrder(scopeRows(turn, data.answers));
  const feedbacks = sortByAgentOrder(scopeRows(turn, data.feedbacks));

  if (data.stage === 1) steps.initialAnswers = answers;
  else if (data.stage === 2) steps.validatedAnswers = answers;
  else if (data.stage === 3) steps.peerFeedback = feedbacks;
  else if (answers.length) steps.initialAnswers = answers;
  else if (feedbacks.length) steps.peerFeedback = feedbacks;
}

export function applyStageComplete(turn, data) {
  if (turn.completed || !data) return null;
  mergeStageRows(turn, data);
  return publish(
    turn,
    buildStageBubbles(turn.processSteps, turn.parentId, turn.createdAt, { showInternal: isInternalVisibleMode(turn.mode) })
  );
}

function liveStage(data, title) {
  return {
    stageType: data.stageType,
    speechType: data.speechType,
    consensus: data.consensus === true,
    title,
    side: data.side,
    agentId: data.agentId,
    agentIndex: data.agentIndex,
    agentName: data.agentName,
    content: data.content ?? data.question ?? data.hint ?? data.feedback ?? '',
    choices: Array.isArray(data.choices) ? data.choices : [],
  };
}

function publishStructured(turn, turnKind, stages) {
  return publish(turn, [buildTurnMessage(turnKind, stages, turn.parentId, turn.createdAt)]);
}

export function applyDebateSection(turn, data) {
  if (turn.completed || !data?.stageType) return null;
  const title = data.stageTitle || debateStageTitle(data.side, data.stageType);
  turn.debateStages.set(`${data.stageType}::${data.side}`, liveStage(data, title));
  return publishStructured(turn, 'debate', Array.from(turn.debateStages.values()));
}

export function applySocraticStep(turn, data) {
  if (turn.completed || !data?.stageType) return null;
  const title = data.stageTitle || socraticStageTitle(data.stageType);
  turn.socraticSteps.set(`${data.stageType}::${data.agentIndex ?? 0}`, liveStage(data, title));
  return publishStructured(turn, 'socratic', Array.from(turn.socraticSteps.values()));
}

export function applySimulationStage(turn, data) {
  if (turn.completed || !data?.stageType) return null;
  const key = `${turn.requestId}::${data.stageType}::${data.agentIndex ?? 0}::${contentHash(data.content)}`;
  turn.simulationStages.set(key, liveStage(data, data.stageTitle || simulationStageTitle(data.stageType)));
  return publishStructured(turn, 'simulation', Array.from(turn.simulationStages.values()));
}

export function applySocraticAnswer(turn, data) {
  if (turn.completed || !data) return null;
  const answer = data.answer ?? (Array.isArray(data.answers) ? data.answers[0]?.answer : '') ?? '';
  const summary = liveStage({ stageType: 'SUMMARY', agentIndex: 3, content: answer }, socraticStageTitle('SUMMARY'));
  return publishStructured(turn, 'socratic', [summary]);
}

export function applyRouteMessage(turn, data, { isPipeline = false } = {}) {
  if (!data) return null;
  turn.routedTerminal = true;
  return publish(turn, [
    {
      id: `${turn.parentId}::${isPipeline ? 'route-pipeline' : 'route'}`,
      sender: 'AI',
      senderName: turn.fallbackAgentName,
      content: data.message || (isPipeline ? '요청을 처리했습니다.' : ''),
      routeAction: data.routeAction || null,
      createdAt: new Date().toISOString(),
      parentId: turn.parentId,
    },
  ]);
}

function hasStages(data, key) {
  return Array.isArray(data?.[key]) && data[key].length > 0;
}

function finalStructuredStages(data, key, accumulated, normalize) {
  if (hasStages(data, key)) return normalize(data);
  if (accumulated.size) return Array.from(accumulated.values());
  return normalize(data) || [];
}

function finalStructuredMessage(turn, data) {
  const responseMode = String(data?.mode || data?.learningMode || '').toLowerCase();

  if (responseMode === 'simulation' || turn.mode === 'simulation') {
    const stages = finalStructuredStages(data, 'simulationStages', turn.simulationStages, normalizeSimulationStages);
    if (stages.length) return buildTurnMessage('simulation', stages, turn.parentId, turn.createdAt);
  }

  if (responseMode === 'socratic' || turn.mode === 'socratic') {
    const steps = finalStructuredStages(data, 'socraticSteps', turn.socraticSteps, normalizeSocraticSteps);
    if (steps.length) return buildTurnMessage('socratic', steps, turn.parentId, turn.createdAt);
  }

  const debateStages = finalStructuredStages(data, 'debateStages', turn.debateStages, normalizeDebateStages);
  if (debateStages.length) return buildTurnMessage('debate', debateStages, turn.parentId, turn.createdAt);

  return null;
}

function scopedProcessSteps(turn, data) {
  if (!data?.processSteps) return turn.processSteps;
  return {
    ...data.processSteps,
    initialAnswers: scopeRows(turn, data.processSteps.initialAnswers),
    validatedAnswers: scopeRows(turn, data.processSteps.validatedAnswers),
    peerFeedback: scopeRows(turn, data.processSteps.peerFeedback),
  };
}

function replyMessage(turn, reply, index) {
  const coerced = coerceAgentText(reply.answer || reply.content || '');
  const slot = slotOfEvent(turn, {
    agentId: reply.agentId,
    agentName: reply.agentName || reply.agent_name,
    agentIndex: reply.agentIndex ?? index + 1,
  });
  return {
    id: `${turn.parentId}::ans::${index}`,
    sender: 'AI',
    senderName: reply.agentName || reply.agent_name || turn.fallbackAgentName,
    content: coerced.text,
    agentId: reply.agentId,
    agentIndex: slot ?? undefined,
    agentSlot: slot ?? undefined,
    isError: !coerced.ok,
    validation: extractValidation(reply),
    createdAt: turn.createdAt,
    parentId: turn.parentId,
  };
}

function emptyTurnMessage(turn) {
  return {
    id: `${turn.parentId}::empty`,
    sender: 'AI',
    senderName: turn.fallbackAgentName,
    content: EMPTY_TURN_TEXT,
    isError: true,
    createdAt: turn.createdAt,
    parentId: turn.parentId,
  };
}

function finalTurnMessages(turn, data) {
  const structured = finalStructuredMessage(turn, data);
  if (structured) return [structured];
  if (turn.answers.size > 0) return answerList(turn);

  const responseMode = String(data?.mode || data?.learningMode || '').toLowerCase();
  const bubbles = buildStageBubbles(scopedProcessSteps(turn, data), turn.parentId, turn.createdAt, {
    showInternal: isInternalVisibleMode(responseMode || turn.mode),
  });
  if (bubbles.length) return bubbles;

  const replies = scopeRows(turn, data?.answers || data?.replies || []);
  if (replies.length) return sortByAgentOrder(replies).map((reply, index) => replyMessage(turn, reply, index));

  return turn.rendered ? turn.messages : [emptyTurnMessage(turn)];
}

export function applyAllComplete(turn, data) {
  if (turn.completed) return null;
  turn.completed = true;
  if (turn.routedTerminal) return turn.messages;
  if (turn.modeGuardShown || isModeGuardPayload(data)) return applyModeGuard(turn, data);
  return publish(turn, finalTurnMessages(turn, data));
}
