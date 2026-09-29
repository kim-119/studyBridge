import { resolveMentionTarget } from '../../../utils/agentIdentity.js';
import { ROLE_TO_TARGET_KEY, roleForAgentIndex } from '../../../components/studymate/pixel/professorSprites.js';
import {
  DEFAULT_DEBATE_CONFIG,
  DEFAULT_SIMULATION_CONFIG,
  DEFAULT_SOCRATIC_CONFIG,
  normalizeLearningMode,
} from './learningModes.js';

const EXPLICIT_SOCRATIC_REQUEST =
  /소크라테스|소크라틱|socratic|단계별\s*(질문|학습|설명|유도)|질문\s*(하면서|으로)\s*(알려|유도|설명|진행|학습)|질문하면서|질문으로\s*유도|카드\s*(로|기반|식)|문답\s*(으로|식|형|법)/i;

export function sanitizeQuestion(raw) {
  if (raw == null) return '';
  return String(raw)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s+|\s+$/g, '');
}

export function resolveActiveLearningMode(roomLearningMode, message) {
  const roomMode = normalizeLearningMode(roomLearningMode);
  const asksForSocratic = EXPLICIT_SOCRATIC_REQUEST.test(String(message || ''));
  return asksForSocratic && roomMode === 'basic' ? 'socratic' : roomMode;
}

export function resolveTurnTarget(message, roomAgents, pinnedAgentId) {
  const mention = resolveMentionTarget(message, roomAgents, pinnedAgentId);
  if (mention.scope !== 'single') return { scope: 'all', mention };

  const professorRole = roleForAgentIndex(mention.slot);
  return {
    scope: 'single',
    mention,
    agentId: mention.agentId,
    agentIndex: mention.slot,
    agentName: mention.agentName,
    professorRole,
    agentKey: ROLE_TO_TARGET_KEY[professorRole] || null,
  };
}

export function stateForMode(conversationState, mode) {
  const state = conversationState || {};
  if (state.mode && state.mode !== mode) return {};
  return state;
}

function socraticExtras(message, room, state) {
  const config = room?.socraticConfig || DEFAULT_SOCRATIC_CONFIG;
  const extras = {
    userAttempt: message,
    socraticConfig: { questionIntensity: config.questionIntensity, hintPolicy: config.hintPolicy },
  };
  if (state.sessionId) extras.sessionId = state.sessionId;
  if (state.socraticState != null) extras.socraticState = state.socraticState;
  return extras;
}

function debateExtras(room, state) {
  const config = room?.debateConfig || DEFAULT_DEBATE_CONFIG;
  const strength = config.debateStrength || config.debateDepth || 'normal';
  const extras = { debateConfig: { debateStrength: strength }, debateStrength: strength };
  if (state.debateState != null) extras.debateState = state.debateState;
  if (state.selectedTopic) extras.selectedTopic = state.selectedTopic;
  if (state.debateSessionId) extras.debateSessionId = state.debateSessionId;
  if (typeof state.turnIndex === 'number') extras.turnIndex = state.turnIndex;
  return extras;
}

function simulationConfigPayload(config) {
  return {
    scenarioType: config.scenarioType,
    difficulty: config.difficulty,
    choiceCount: Number(config.choiceCount) || 3,
    ...(config.userRole ? { userRole: config.userRole } : {}),
    ...(config.userRoleMode ? { userRoleMode: config.userRoleMode } : {}),
  };
}

function simulationExtras(room, state) {
  const extras = { simulationConfig: simulationConfigPayload(room?.simulationConfig || DEFAULT_SIMULATION_CONFIG) };
  if (state.sessionId) extras.sessionId = state.sessionId;
  if (state.simulationState != null) extras.simulationState = state.simulationState;
  if (state.scenarioId) extras.scenarioId = state.scenarioId;
  if (typeof state.turnIndex === 'number') extras.turnIndex = state.turnIndex;
  if (state.selectedChoice) extras.selectedChoice = state.selectedChoice;
  if (Array.isArray(state.previousChoices) && state.previousChoices.length) {
    extras.previousChoices = state.previousChoices;
  }
  return extras;
}

function basicExtras() {
  return {
    stagePolicy: 'full',
    enableDeepening: true,
    enablePeerFeedback: true,
    enableHallucinationValidation: true,
  };
}

function targetExtras(target) {
  if (target?.scope !== 'single') return {};

  return {
    targetAgentId: target.agentId != null ? String(target.agentId) : null,
    askScope: 'single',
    targetProfessorRole: target.professorRole,
    targetAgentIndex: target.agentIndex,
    targetAgentKey: target.agentKey,
    targetAgentName: target.agentName,
    professorSelectedTarget: target.agentKey,
    selectedProfessorRole: target.professorRole,
  };
}

function modeExtras(mode, message, room, state) {
  if (mode === 'socratic') return socraticExtras(message, room, state);
  if (mode === 'debate') return debateExtras(room, state);
  if (mode === 'simulation') return simulationExtras(room, state);
  return basicExtras();
}

export function nextRegenerateAttempt(regenerateTrack, message) {
  return regenerateTrack && regenerateTrack.question === message ? regenerateTrack.attempt + 1 : 1;
}

export function buildStreamPayload({ message, room, mode, target, conversationState, requestId, regenerateAttempt }) {
  const state = stateForMode(conversationState, mode);
  const materialId = room?.materialId ?? room?.material_id;

  const payload = {
    message,
    learningMode: mode,
    rounds: 1,
    ...modeExtras(mode, message, room, state),
    ...targetExtras(target),
    ...(materialId ? { materialId } : {}),
    messageId: requestId,
    regenerateAttempt,
    forceRegenerate: regenerateAttempt > 1,
  };

  if (mode !== 'basic') payload.mode = mode;
  return payload;
}

export function selectSimulationChoice(conversationState, choice) {
  const label = choice?.label || choice?.choiceId || 'A';
  const choiceId = choice?.choiceId || choice?.label || label;
  return { ...(conversationState || {}), selectedChoice: { choiceId, label } };
}

export function consumeSimulationChoice(conversationState, mode) {
  const state = stateForMode(conversationState, mode);
  if (mode !== 'simulation' || !state.selectedChoice) return state;

  const previousChoices = Array.isArray(state.previousChoices) ? [...state.previousChoices] : [];
  previousChoices.push(state.selectedChoice);

  return {
    ...state,
    previousChoices,
    selectedChoice: null,
    turnIndex: (typeof state.turnIndex === 'number' ? state.turnIndex : 0) + 1,
  };
}

export function captureConversationState(previousState, eventData, mode) {
  if (!eventData || typeof eventData !== 'object') return previousState || {};

  const next = { ...(previousState || {}), mode };
  const assign = (key, value) => {
    if (value !== undefined && value !== null && value !== '') next[key] = value;
  };

  assign('debateState', eventData.debateState ?? eventData.debate_state);
  assign('selectedTopic', eventData.selectedTopic ?? eventData.selected_topic);
  assign('debateSessionId', eventData.debateSessionId ?? eventData.debate_session_id);
  assign(
    'sessionId',
    eventData.sessionId ??
      eventData.session_id ??
      eventData.socraticState?.sessionId ??
      eventData.simulationState?.sessionId
  );
  assign('socraticState', eventData.socraticState ?? eventData.socratic_state);
  assign('simulationState', eventData.simulationState ?? eventData.simulation_state);
  assign('scenarioId', eventData.scenarioId ?? eventData.scenario_id);

  const turnIndex = eventData.turnIndex ?? eventData.turn_index;
  if (typeof turnIndex === 'number') next.turnIndex = turnIndex;

  return next;
}
