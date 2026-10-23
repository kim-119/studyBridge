import {
  PERSONALITY_STYLE_OPTIONS,
  normalizePersonalityKey,
  personalityLabel,
  personalityTemperature,
} from '../../../utils/personality.js';
import { DEFAULT_DEBATE_CONFIG, DEFAULT_SIMULATION_CONFIG, DEFAULT_SOCRATIC_CONFIG } from './learningModes.js';

export const MIN_AGENT_COUNT = 1;
export const MAX_AGENT_COUNT = 3;
export const STUDYBRIDGE_ROOM_TITLE = '스터디 브릿지';
export const MIN_CUSTOM_INSTRUCTION_LENGTH = 5;

export const KNOWLEDGE_LEVELS = [
  { value: 'INTRO', label: '입문 수준', desc: '쉬운 말과 비유 중심으로 설명합니다.' },
  { value: 'BACHELOR', label: '학사 수준', desc: '대학 학부 수준으로 정의, 원리, 예시를 설명합니다.' },
  { value: 'MASTER', label: '석사 수준', desc: '비교, 한계, 적용까지 포함해 깊게 설명합니다.' },
  { value: 'DOCTOR', label: '박사 수준', desc: '연구 맥락, 이론적 근거, 쟁점까지 포함해 설명합니다.' },
  { value: 'EXPERT', label: '전문가 수준', desc: '박사 수준 설명에 실무 판단, 트레이드오프, 적용 전략까지 포함합니다.' },
];

export const TONE_OPTIONS = PERSONALITY_STYLE_OPTIONS.map((option) => ({
  value: option.label,
  label: option.label,
}));

export const MATE_TYPES = [
  { key: '정확 설명형', role: '정확한 개념 설명자', icon: '🎓', desc: '개념과 근거를 정확히 정리합니다.' },
  { key: '쉬운 튜터형', role: '쉬운 설명 튜터', icon: '✨', desc: '어려운 내용을 쉽게 풀어줍니다.' },
  { key: '비판 코치형', role: '비판적 학습 코치', icon: '🧐', desc: '오개념과 논리적 허점을 짚어줍니다.' },
  { key: '냉철 분석형', role: '논리적 분석 멘토', icon: '❄️', desc: '감정보다 근거와 구조 중심으로 분석합니다.' },
];

export const REQUEST_GUIDE_CHIPS = [
  { label: '코드 예시 포함', text: '코드 예시를 포함해줘' },
  { label: '쉬운 비유로 설명', text: '쉬운 비유로 설명해줘' },
  { label: '3줄 요약', text: '마지막에 3줄로 요약해줘' },
  { label: '오개념 주의', text: '헷갈리기 쉬운 오개념도 짚어줘' },
  { label: '시험 대비', text: '시험 대비 포인트를 정리해줘' },
];

const MATE_TYPE_PRESETS = {
  '정확 설명형': { role: '정확한 개념 설명자', tone: '효율적', learnerLevel: 'BACHELOR', additionalRequest: '개념 정의, 핵심 원리, 예시, 주의점을 구조적으로 설명해줘.' },
  '쉬운 튜터형': { role: '쉬운 설명 튜터', tone: '친근함', learnerLevel: 'INTRO', additionalRequest: '어려운 용어는 쉬운 비유로 풀고, 단계별로 천천히 설명해줘.' },
  '비판 코치형': { role: '비판적 학습 코치', tone: '솔직함', learnerLevel: 'MASTER', additionalRequest: '내가 놓친 부분, 논리적 허점, 오개념 가능성을 근거 중심으로 짚어줘.' },
  '냉철 분석형': { role: '논리적 분석 멘토', tone: '냉소적', learnerLevel: 'EXPERT', additionalRequest: '감정보다 근거와 구조 중심으로 판단하고, 핵심 쟁점과 논리적 약점을 분리해서 설명해줘.' },
};

const MATE_NAME_POOL = {
  '정확 설명형': ['개념 정리 교수', '원리 해설가', '정확한 설명자'],
  '쉬운 튜터형': ['쉬운 풀이 튜터', '친절한 개념 선생', '차근차근 도우미'],
  '비판 코치형': ['논점 검증 코치', '반례 탐색가', '날카로운 피드백러'],
  '냉철 분석형': ['냉철 분석관', '핵심 진단가', '구조 분석가'],
};

const DEFAULT_BASIC_TYPES = ['정확 설명형', '쉬운 튜터형', '비판 코치형'];

const ROLE_BY_PERSONALITY = {
  '기본값': '학습 메이트',
  '전문적': '전문 교수',
  '친근함': '친근한 친구',
  '솔직함': '솔직한 멘토',
  '독특함': '독창적 강사',
  '효율적': '효율적 튜터',
  '냉소적': '냉철한 멘토',
};

const DEFAULT_AGENT = {
  name: '',
  role: '정확한 개념 설명자',
  personality: '친근함',
  knowledgeLevel: 'BACHELOR',
  customInstruction: '',
  goal: '사용자의 학습을 돕는다',
  agentPreset: '정확 설명형',
  nameEdited: false,
};

export function normalizeKnowledgeLevel(raw) {
  const value = String(raw || '').trim();
  if (!value) return 'BACHELOR';

  const lower = value.toLowerCase();
  if (value.includes('입문') || lower.includes('intro') || lower.includes('beginner')) return 'INTRO';
  if (value.includes('학사') || value.includes('학부') || lower.includes('bachelor') || lower.includes('undergrad')) return 'BACHELOR';
  if (value.includes('석사') || lower.includes('master')) return 'MASTER';
  if (value.includes('박사') || lower.includes('doctor') || lower.includes('phd')) return 'DOCTOR';
  if (value.includes('전문가') || lower.includes('expert')) return 'EXPERT';

  const upper = value.toUpperCase();
  return KNOWLEDGE_LEVELS.some((level) => level.value === upper) ? upper : 'BACHELOR';
}

export function knowledgeLevelOf(value) {
  const normalized = normalizeKnowledgeLevel(value);
  return KNOWLEDGE_LEVELS.find((level) => level.value === normalized) || KNOWLEDGE_LEVELS[1];
}

export function suggestMateName(mateTypeKey, usedNames = []) {
  const pool = MATE_NAME_POOL[mateTypeKey] || [mateTypeKey];
  const used = new Set(usedNames.map((name) => String(name || '').trim()).filter(Boolean));
  const free = pool.find((name) => !used.has(name));
  if (free) return free;

  let suffix = 2;
  while (used.has(`${pool[0]} ${suffix}`)) suffix += 1;
  return `${pool[0]} ${suffix}`;
}

export function buildAgentFromMateType(mateTypeKey) {
  const preset = MATE_TYPE_PRESETS[mateTypeKey] || {};

  return {
    ...DEFAULT_AGENT,
    name: MATE_NAME_POOL[mateTypeKey]?.[0] || mateTypeKey,
    role: preset.role || DEFAULT_AGENT.role,
    personality: preset.tone || DEFAULT_AGENT.personality,
    knowledgeLevel: preset.learnerLevel || DEFAULT_AGENT.knowledgeLevel,
    customInstruction: preset.additionalRequest || '',
    goal: preset.role || DEFAULT_AGENT.goal,
    agentPreset: mateTypeKey,
  };
}

export function createDefaultAgent(index) {
  const mateTypeKey = DEFAULT_BASIC_TYPES[index] || DEFAULT_BASIC_TYPES[DEFAULT_BASIC_TYPES.length - 1];
  return buildAgentFromMateType(mateTypeKey);
}

export function makeDefaultAgents() {
  return DEFAULT_BASIC_TYPES.map(buildAgentFromMateType);
}

export function mapPresetAgentToDraft(presetAgent) {
  return {
    ...DEFAULT_AGENT,
    name: presetAgent.name,
    role: presetAgent.role,
    personality: presetAgent.tone,
    knowledgeLevel: presetAgent.learnerLevel,
    customInstruction: presetAgent.additionalRequest,
    goal: presetAgent.role,
    agentPreset: '',
  };
}

export function normalizeAgentDrafts(list) {
  const drafts = (Array.isArray(list) ? list : []).filter(Boolean).slice(0, MAX_AGENT_COUNT);
  return drafts.length > 0 ? drafts : [createDefaultAgent(0)];
}

export function nextAgentDraft(index, activePreset) {
  const presetAgent = activePreset?.agents?.[index];
  return presetAgent ? mapPresetAgentToDraft(presetAgent) : createDefaultAgent(index);
}

export function applyMateType(drafts, index, mateTypeKey) {
  const preset = MATE_TYPE_PRESETS[mateTypeKey] || {};
  const mateType = MATE_TYPES.find((type) => type.key === mateTypeKey) || {};
  const current = drafts[index] || DEFAULT_AGENT;
  const otherNames = drafts.filter((_, position) => position !== index).map((draft) => draft?.name);
  const keepName = current.nameEdited && String(current.name || '').trim();

  const updated = [...drafts];
  updated[index] = {
    ...current,
    agentPreset: mateTypeKey,
    name: keepName ? current.name : suggestMateName(mateTypeKey, otherNames),
    role: preset.role || mateType.role,
    personality: preset.tone || current.personality,
    knowledgeLevel: preset.learnerLevel || current.knowledgeLevel,
    customInstruction: preset.additionalRequest || '',
    goal: preset.role || mateType.role,
  };
  return updated;
}

export function appendRequestChip(customInstruction, chipText) {
  const current = String(customInstruction || '').trim();
  if (current.includes(chipText)) return current;
  return current ? `${current} ${chipText}` : chipText;
}

export function findInvalidInstruction(drafts) {
  return drafts.find((draft) => {
    const length = String(draft.customInstruction || '').trim().length;
    return length > 0 && length < MIN_CUSTOM_INSTRUCTION_LENGTH;
  });
}

function deriveRole(personality) {
  return ROLE_BY_PERSONALITY[personality] || '학습 메이트';
}

export function buildCanonicalAgentPayload(draft) {
  const personalityKey = normalizePersonalityKey(draft.personality);
  const personality = personalityLabel(personalityKey);
  const knowledgeLevel = normalizeKnowledgeLevel(draft.knowledgeLevel);
  const customInstruction = String(draft.customInstruction || '').trim();
  const goal = String(draft.goal || '사용자의 학습을 돕는다').trim();
  const agentPreset = String(draft.agentPreset || '').trim();
  const presetTag = agentPreset ? `[프리셋: ${agentPreset}] ` : '';

  return {
    name: String(draft.name || '').trim(),
    role: String(draft.role || '').trim() || deriveRole(personality),
    agentPreset,
    personality,
    personalityStyle: personalityKey,
    temperature: personalityTemperature(personalityKey),
    personalityStrength: draft.personalityStrength || 'extreme',
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    knowledgeLevelLabel: knowledgeLevelOf(knowledgeLevel).label,
    goal,
    customInstruction,
    custom_instruction: customInstruction,
    persona: `${presetTag}[지식수준: ${knowledgeLevel}] [성격: ${personality}] ${customInstruction || goal}`,
  };
}

export function buildCreateRoomPayload({ roomName, learningMode, agentDrafts, debateConfig, socraticConfig, simulationConfig }) {
  return {
    roomName: String(roomName || '').trim() || STUDYBRIDGE_ROOM_TITLE,
    agents: normalizeAgentDrafts(agentDrafts).map(buildCanonicalAgentPayload),
    learningMode,
    debateConfig: learningMode === 'debate' ? debateConfig || DEFAULT_DEBATE_CONFIG : null,
    socraticConfig: learningMode === 'socratic' ? socraticConfig || DEFAULT_SOCRATIC_CONFIG : null,
    simulationConfig: learningMode === 'simulation' ? simulationConfig || DEFAULT_SIMULATION_CONFIG : null,
  };
}

export function roomLimitForRole(role) {
  const normalized = String(role || '').trim().toUpperCase();
  return ['ADMIN', 'ROOT', 'PREMIUM'].includes(normalized) ? 10 : 3;
}
