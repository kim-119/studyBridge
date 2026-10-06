import { MENTION_ALL, applyMentionPrefill } from '../../../utils/agentIdentity.js';
import { ROLE_NAMES, ROLE_TO_AGENT_INDEX, roleForAgentIndex } from '../../../components/studymate/pixel/professorSprites.js';

const ACTION_REQUESTS = {
  detail: '더 자세히 설명해 주세요.',
  rebuttal: '현재 답변의 약점과 반론을 제시해 주세요.',
  compare: '유사 개념 또는 대안과 비교해 주세요.',
  example: '구체적인 예시를 들어 주세요.',
  why: '왜 그런지 소크라테스식 질문으로 파고들어 주세요.',
  assumption: '답변의 전제와 숨은 가정을 검토해 주세요.',
  counterQuestion: '학습자가 스스로 생각할 수 있는 역질문을 제시해 주세요.',
  defense: '반박에 대한 방어 논리를 제시해 주세요.',
  judge: '양쪽 관점을 판정하고 근거를 제시해 주세요.',
  roleplay: '상황극 방식으로 설명해 주세요.',
  choice: '선택지 기반으로 다음 행동을 제안해 주세요.',
  reaction: '상황에 따른 인물/교수의 반응을 제시해 주세요.',
};

const TARGET_REQUESTS = {
  all: '모든 에이전트가 각자 관점으로 답변해 주세요.',
  agent1: '1번 에이전트 관점 중심으로 답변해 주세요.',
  agent2: '2번 에이전트 관점 중심으로 답변해 주세요.',
  agent3: '3번 에이전트 관점 중심으로 답변해 주세요.',
};

const EXCERPT_LENGTH = 60;

export const FOLLOW_UP_ACT_MESSAGE = {
  DEEPEN: '방금 내용을 더 깊이 자세히 설명해줘',
  ALT_VIEW: '다른 관점이나 반대 의견도 들려줘',
  SIMPLIFY: '더 쉬운 예시로 다시 설명해줘',
};

function excerptOf(text) {
  if (!text) return '';
  if (text.length <= EXCERPT_LENGTH) return text.replace(/\n/g, ' ');
  return `${text.substring(0, EXCERPT_LENGTH).replace(/\n/g, ' ')}...`;
}

export function buildProfessorActionPrompt({ actionKey, targetKey, baseText }) {
  const excerpt = excerptOf(baseText);
  const action = ACTION_REQUESTS[actionKey] || ACTION_REQUESTS.detail;
  const target = TARGET_REQUESTS[targetKey] || TARGET_REQUESTS.all;
  const reference = excerpt ? `\n\n기준 내용:\n${excerpt}` : '';
  return `${MENTION_ALL} ${action}\n${target}${reference}`;
}

export function professorDisplayName(roomAgents, role) {
  return roomAgents?.[ROLE_TO_AGENT_INDEX[role] ?? -1]?.name || ROLE_NAMES[role] || '교수';
}

export function professorRoleOfSlot(slot) {
  return roleForAgentIndex(slot);
}

export function mentionForAgent(agent) {
  return agent?.name ? `@${agent.name} ` : `${MENTION_ALL} `;
}

export function prefillMention(draft, mention, roomAgents) {
  return applyMentionPrefill(draft, mention, roomAgents);
}

export function followUpMessage(chip) {
  return FOLLOW_UP_ACT_MESSAGE[chip?.act] || chip?.label || '';
}

export function mentionQueryOf(draft) {
  const lastAt = draft.lastIndexOf('@');
  if (lastAt === -1) return null;
  const afterAt = draft.slice(lastAt + 1);
  return afterAt.includes(' ') ? null : afterAt;
}

export function insertMention(draft, name) {
  const lastAt = draft.lastIndexOf('@');
  if (lastAt === -1) return draft;
  const afterAtText = draft.slice(lastAt);
  const spaceIndex = afterAtText.indexOf(' ');
  const afterMention = spaceIndex !== -1 ? afterAtText.slice(spaceIndex) : ' ';
  return `${draft.slice(0, lastAt)}@${name}${afterMention}`;
}
