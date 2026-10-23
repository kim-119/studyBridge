import { AGENT_COLOR_PALETTE, hashAgentKey } from '../../../utils/agentColor.js';
import { agentIdOf, resolveRoomAgentSlot } from '../../../utils/agentIdentity.js';
import { personalityLabel } from '../../../utils/personality.js';
import { isUserMessage, stripLegacyActBadge } from './chatMessages.js';

export const UNASSIGNED_AGENT_KEY = 'unassigned';

function hasValue(value) {
  return value != null && String(value).trim() !== '';
}

export function agentPaletteForSlot(slot) {
  const index = Math.max(0, Number(slot) || 0) % AGENT_COLOR_PALETTE.length;
  return AGENT_COLOR_PALETTE[index];
}

export function agentPaletteForName(name) {
  return AGENT_COLOR_PALETTE[hashAgentKey(name) % AGENT_COLOR_PALETTE.length];
}

export function agentRoleText(agent) {
  if (!agent) return '';
  const personality = agent.personality || agent.tone || agent.style;
  return [agent.role, personality && personalityLabel(personality)].filter(Boolean).join(' · ');
}

const CONSENSUS_STAGE_TYPES = new Set(['DEBATE_FINAL_CONCLUSION', 'FINAL_CONCLUSION', 'JUDGEMENT']);
const CONSENSUS_AGENT_ID = 'debate-consensus';
const NO_AGENT = {};

export function isConsensusSpeech(speech) {
  if (!speech) return false;
  return (
    CONSENSUS_STAGE_TYPES.has(String(speech.stageType || '').toUpperCase()) ||
    String(speech.speechType || '').toUpperCase() === 'FINAL_CONCLUSION' ||
    String(speech.agentId ?? speech.agent_id ?? '') === CONSENSUS_AGENT_ID ||
    speech.consensus === true
  );
}

export function identityOfMessage(message) {
  if (isConsensusSpeech(message)) return NO_AGENT;
  return {
    agentId: message?.agentId ?? message?.agent_id,
    agentSlot: message?.agentSlot,
    agentName: message?.senderName,
  };
}

export function identityOfStage(stage) {
  if (isConsensusSpeech(stage)) return NO_AGENT;
  return {
    agentId: stage?.agentId,
    agentIndex: stage?.agentIndex,
    agentName: stage?.agentName,
  };
}

export function identityOfRoomAgent(agent, slot) {
  const id = agentIdOf(agent);
  return {
    key: hasValue(id) ? `agent-${id}` : `slot-${slot}`,
    slot,
    name: agent?.name || `교수 ${slot + 1}`,
    roleText: agentRoleText(agent),
    palette: agentPaletteForSlot(slot),
  };
}

function outsideAgentIdentity(identity) {
  const name = String(identity?.agentName ?? '').trim();
  const id = identity?.agentId;
  if (!name && !hasValue(id)) return null;
  return {
    key: name ? `name-${name}` : `agent-${id}`,
    slot: -1,
    name: name || `에이전트 ${id}`,
    roleText: '',
    palette: agentPaletteForName(name || String(id)),
  };
}

export function resolveAnswerAgent(identity, roomAgents) {
  const agents = Array.isArray(roomAgents) ? roomAgents : [];
  const slot = resolveRoomAgentSlot(agents, identity);
  if (slot >= 0 && agents[slot]) return identityOfRoomAgent(agents[slot], slot);
  return outsideAgentIdentity(identity);
}

export function agentStyleOf(agent) {
  if (!agent) return undefined;
  return {
    '--agent-border': agent.palette.border,
    '--agent-bg': agent.palette.bg,
    '--agent-text': agent.palette.text,
  };
}

function structuredEntriesOf(message) {
  return (message.stages || []).map((stage, index) => ({
    id: `${message.id}::stage::${index}`,
    title: stage.title || '',
    content: stage.content || '',
    identity: identityOfStage(stage),
  }));
}

function plainEntryOf(message) {
  return {
    id: String(message.id),
    title: message.stageTitle || '',
    content: message.isPending ? message.statusText || '답변 생성 중…' : stripLegacyActBadge(message.content),
    identity: identityOfMessage(message),
    isPending: Boolean(message.isPending),
    isError: Boolean(message.isError),
  };
}

export function answerEntriesOf(message) {
  if (!message || isUserMessage(message) || message.isNotice) return [];
  if (message.turnKind) return structuredEntriesOf(message);
  return [plainEntryOf(message)];
}

export function latestTurnAnswerEntries(messages) {
  const list = Array.isArray(messages) ? messages : [];
  const lastUserIndex = list.map(isUserMessage).lastIndexOf(true);
  return list
    .slice(lastUserIndex + 1)
    .flatMap(answerEntriesOf)
    .filter((entry) => String(entry.content || '').trim() !== '');
}

export function groupAnswersByAgent(entries, roomAgents) {
  const groups = new Map();
  (entries || []).forEach((entry) => {
    const agent = resolveAnswerAgent(entry.identity, roomAgents);
    const key = agent?.key ?? UNASSIGNED_AGENT_KEY;
    if (!groups.has(key)) groups.set(key, { key, agent, entries: [] });
    groups.get(key).entries.push(entry);
  });
  return [...groups.values()];
}
