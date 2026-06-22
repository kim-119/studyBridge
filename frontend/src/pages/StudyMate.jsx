import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { Bot, Plus, Send, Sparkles, Trash2, X, MessageSquare, MessageCircle, UsersRound, Network, ChevronLeft, ChevronRight, CheckCircle2, Bookmark, ShieldCheck } from 'lucide-react';
import AgentDiscussionThread from '../components/studymate/AgentDiscussionThread';
import ProfessorLearningPanel from '../components/studymate/ProfessorLearningPanel';
import '../components/studymate/studymate-premium.css';
import { motion, AnimatePresence } from 'framer-motion';
import { getAgentColor, agentColorKey } from '../utils/agentColor';
import { PERSONALITY_STYLE_OPTIONS, normalizePersonalityKey, personalityLabel as canonicalPersonalityLabel, personalityTemperature } from '../utils/personality';

// 성격/말투는 공통 7종(기본값/전문적/친근함/솔직함/독특함/효율적/냉소적)으로 통일한다(두 번째 UI 기준).

// 학습자 수준: 표시 라벨(한국어)과 전송 value(enum) 분리. ai07/Spring은 enum으로 라우팅한다.
const KNOWLEDGE_LEVELS = [
  { value: 'INTRO', label: '입문 수준', desc: '쉬운 말과 비유 중심으로 설명합니다.' },
  { value: 'BACHELOR', label: '학사 수준', desc: '대학 학부 수준으로 정의, 원리, 예시를 설명합니다.' },
  { value: 'MASTER', label: '석사 수준', desc: '비교, 한계, 적용까지 포함해 깊게 설명합니다.' },
  { value: 'DOCTOR', label: '박사 수준', desc: '연구 맥락, 이론적 근거, 쟁점까지 포함해 설명합니다.' },
  { value: 'EXPERT', label: '전문가 수준', desc: '박사 수준 설명에 실무 판단, 트레이드오프, 적용 전략까지 포함합니다.' },
];
const KNOWLEDGE_LEVEL_VALUES = KNOWLEDGE_LEVELS.map((l) => l.value);
// 한국어("학사 수준")/영문(bachelor)/enum 입력을 표준 enum으로 통일. 구버전 저장방 persona 태그도 호환.
const normalizeKnowledgeLevel = (raw) => {
  const v = String(raw || '').trim();
  if (!v) return 'BACHELOR';
  const low = v.toLowerCase();
  if (v.includes('입문') || low.includes('intro') || low.includes('beginner')) return 'INTRO';
  if (v.includes('학사') || v.includes('학부') || low.includes('bachelor') || low.includes('undergrad')) return 'BACHELOR';
  if (v.includes('석사') || low.includes('master')) return 'MASTER';
  if (v.includes('박사') || low.includes('doctor') || low.includes('phd')) return 'DOCTOR';
  if (v.includes('전문가') || low.includes('expert')) return 'EXPERT';
  const up = v.toUpperCase();
  return KNOWLEDGE_LEVEL_VALUES.includes(up) ? up : 'BACHELOR';
};
const knowledgeLevelLabel = (v) => (KNOWLEDGE_LEVELS.find((l) => l.value === normalizeKnowledgeLevel(v)) || {}).label || '학사 수준';
const knowledgeLevelDesc = (v) => (KNOWLEDGE_LEVELS.find((l) => l.value === normalizeKnowledgeLevel(v)) || {}).desc || '';

// 말투(성격) → 내부 role 기본값. UI에서 '역할' 입력은 숨기되 payload의 role은 말투에서 자동 유도한다.
const ROLE_BY_PERSONALITY = {
  '기본값': '학습 메이트',
  '전문적': '전문 교수',
  '친근함': '친근한 친구',
  '솔직함': '솔직한 멘토',
  '독특함': '독창적 강사',
  '효율적': '효율적 튜터',
  '냉소적': '냉철한 멘토',
};
const deriveRole = (personality) => ROLE_BY_PERSONALITY[personality] || '학습 메이트';

// 학습메이트 유형 = "어떤 역할로 도와줄지"(역할). 답변 톤/학습자 수준과 개념 분리.
// 유형 선택 시 payload의 role만 내부 매핑하고, 톤(personality)은 별도 선택값을 유지한다.
const MATE_TYPES = [
  { key: '정확 설명형', role: '정확한 개념 설명자', icon: '🎓', color: '#2563EB', desc: '개념과 근거를 정확히 정리합니다.' },
  { key: '쉬운 튜터형', role: '쉬운 설명 튜터', icon: '✨', color: '#EA580C', desc: '어려운 내용을 쉽게 풀어줍니다.' },
  { key: '비판 코치형', role: '비판적 학습 코치', icon: '🧐', color: '#E11D48', desc: '오개념과 논리적 허점을 짚어줍니다.' },
  { key: '냉철 분석형', role: '논리적 분석 멘토', icon: '❄️', color: '#374151', desc: '감정보다 근거와 구조 중심으로 분석합니다.' },
];

// 학습메이트 유형별 자연스러운 이름 후보 풀 — 유형명을 그대로 이름으로 쓰지 않도록 자동 작명에 사용.
// suggestMateName(key, usedNames): 같은 방의 다른 에이전트 이름과 겹치지 않는 첫 후보를 고른다(모두 사용 중이면 번호 부여).
const MATE_NAME_POOL = {
  '정확 설명형': ['개념 정리 교수', '원리 해설가', '정확한 설명자'],
  '쉬운 튜터형': ['쉬운 풀이 튜터', '친절한 개념 선생', '차근차근 도우미'],
  '비판 코치형': ['논점 검증 코치', '반례 탐색가', '날카로운 피드백러'],
  '냉철 분석형': ['냉철 분석관', '핵심 진단가', '구조 분석가'],
};
const suggestMateName = (key, usedNames = []) => {
  const pool = MATE_NAME_POOL[key] || [key];
  const used = new Set((usedNames || []).map((n) => String(n || '').trim()).filter(Boolean));
  const free = pool.find((n) => !used.has(n));
  if (free) return free;
  // 후보가 모두 쓰이면 첫 후보에 번호를 붙여 중복 회피
  let i = 2;
  while (used.has(`${pool[0]} ${i}`)) i += 1;
  return `${pool[0]} ${i}`;
};

// 답변 톤(성격) = 공통 7종으로 통일. value(내부 personality enum)와 표시 label을 동일한 정규 라벨로 맞춘다.
// 7개 personality(기본값/전문적/친근함/솔직함/독특함/효율적/냉소적)를 모두 노출해 에이전트별 톤 차별화를 지원한다.
const TONE_OPTIONS = PERSONALITY_STYLE_OPTIONS.map((o) => ({ value: o.label, label: o.label, key: o.key, description: o.description }));

// 추가 요청 입력 보조용 추천 칩(클릭 시 입력창 뒤에 자연스럽게 덧붙임).
const REQUEST_GUIDE_CHIPS = [
  { label: '코드 예시 포함', text: '코드 예시를 포함해줘' },
  { label: '쉬운 비유로 설명', text: '쉬운 비유로 설명해줘' },
  { label: '3줄 요약', text: '마지막에 3줄로 요약해줘' },
  { label: '오개념 주의', text: '헷갈리기 쉬운 오개념도 짚어줘' },
  { label: '시험 대비', text: '시험 대비 포인트를 정리해줘' },
];

const DEFAULT_AGENT = {
  name: '',
  role: '정확한 개념 설명자',
  personality: '친근함',
  knowledgeLevel: 'BACHELOR',
  customInstruction: '',
  goal: '사용자의 학습을 돕는다',
  agentPreset: '정확 설명형'
};

// ── 학습메이트 유형(기본 모드) 프리셋 ───────────────────────────────────────────
// MATE_TYPES 버튼을 누르면 이름/답변 톤/학습자 수준/추가 요청을 한 번에 채운다.
// tone 값은 TONE_OPTIONS의 personality enum 값과 일치시켜 select 표시값이 즉시 바뀌게 한다.
const LEARNING_MATE_TYPE_PRESETS = {
  '정확 설명형': { role: '정확한 개념 설명자', tone: '효율적', learnerLevel: 'BACHELOR', additionalRequest: '개념 정의, 핵심 원리, 예시, 주의점을 구조적으로 설명해줘.' },
  '쉬운 튜터형': { role: '쉬운 설명 튜터',     tone: '친근함', learnerLevel: 'INTRO',    additionalRequest: '어려운 용어는 쉬운 비유로 풀고, 단계별로 천천히 설명해줘.' },
  '비판 코치형': { role: '비판적 학습 코치',   tone: '솔직함', learnerLevel: 'MASTER',   additionalRequest: '내가 놓친 부분, 논리적 허점, 오개념 가능성을 근거 중심으로 짚어줘.' },
  '냉철 분석형': { role: '논리적 분석 멘토',   tone: '냉소적', learnerLevel: 'EXPERT',   additionalRequest: '감정보다 근거와 구조 중심으로 판단하고, 핵심 쟁점과 논리적 약점을 분리해서 설명해줘.' },
};

// 기본 모드 진입 시 자동 구성되는 에이전트 시드 3종(유형 프리셋). 이후 사용자가 1~3명으로 조절한다.
const DEFAULT_BASIC_TYPES = ['정확 설명형', '쉬운 튜터형', '비판 코치형'];
const buildAgentFromMateType = (key) => {
  const p = LEARNING_MATE_TYPE_PRESETS[key] || {};
  return {
    ...DEFAULT_AGENT,
    name: (MATE_NAME_POOL[key] && MATE_NAME_POOL[key][0]) || key,
    nameEdited: false,
    role: p.role || DEFAULT_AGENT.role,
    personality: p.tone || DEFAULT_AGENT.personality,
    knowledgeLevel: p.learnerLevel || DEFAULT_AGENT.knowledgeLevel,
    customInstruction: p.additionalRequest || '',
    goal: p.role || DEFAULT_AGENT.goal,
    agentPreset: key,
  };
};
// 에이전트 인원 정책 — 최소 1명, 최대 3명. createdAgents 배열 길이가 곧 현재 에이전트 수다.
const MIN_AGENT_COUNT = 1;
const MAX_AGENT_COUNT = 3;

// 모달 단계 전환용 큰 ‹ › 버튼(모달 좌·우 끝). 화면 단계 전체를 옆으로 넘긴다 —
// 추천 방 설정 캐러셀의 작은 ‹ › 와 시각적으로 구분되도록 크게 만든다.
const BIG_NAV = {
  width: '42px', minHeight: '160px', borderRadius: '12px',
  border: '1px solid var(--color-border)', background: '#fff', color: 'var(--color-primary)',
  fontSize: '28px', fontWeight: 800, cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
  boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
};
const BIG_NAV_OFF = { ...BIG_NAV, opacity: 0.3, cursor: 'not-allowed', boxShadow: 'none' };

// index 위치의 기본 에이전트 한 명 생성. 기본 유형(정확 설명형/쉬운 튜터형/비판 코치형)을 시드로 써서
// 이름·역할·톤이 비어 있지 않게 채운다(추가/복원 시 required 이름 입력이 비지 않도록).
const createDefaultAgent = (index) => {
  const key = DEFAULT_BASIC_TYPES[index] || DEFAULT_BASIC_TYPES[DEFAULT_BASIC_TYPES.length - 1];
  return buildAgentFromMateType(key);
};

// 기본 진입 에이전트(기본 모드 시드 3명). 첫 진입 기본값은 3명이며 이후 + / - 로 1~3명으로 조절 가능.
const makeDefaultAgents = () => DEFAULT_BASIC_TYPES.map(buildAgentFromMateType);

// 추천 방 설정 프리셋 agent(name/role/tone/learnerLevel/additionalRequest) → createdAgents 항목으로 매핑.
const mapPresetAgentToCreatedAgent = (a) => ({
  ...DEFAULT_AGENT,
  name: a.name,
  role: a.role,
  personality: a.tone,
  knowledgeLevel: a.learnerLevel,
  customInstruction: a.additionalRequest,
  goal: a.role,
  agentPreset: '',
});

// 캐러셀/제출 공통 방어: 길이를 1~3명으로 보정한다(이름·역할 등 사용자 입력은 보존, 빈 배열만 기본 1명 시드).
const normalizeAgents = (list) => {
  const base = (Array.isArray(list) ? list : []).filter(Boolean).slice(0, MAX_AGENT_COUNT);
  return base.length > 0 ? base : [createDefaultAgent(0)];
};

// 정규 성격 키 → 한글 라벨 (백엔드 personalityType: creative/sardonic/logical/...)
const PERSONALITY_TYPE_LABELS = {
  creative: '독특함', sardonic: '냉소적', logical: '논리형',
  critical: '비판형', friendly: '친근함', concise: '효율적',
  professional: '전문적', custom: '맞춤형',
};
const personalityLabel = (t) => PERSONALITY_TYPE_LABELS[t] || t || '';
const stepContent = (row) => row?.content ?? row?.answer ?? row?.feedback ?? '';
const formatElapsed = (ms) => (typeof ms === 'number' && ms > 0 ? `${(ms / 1000).toFixed(1)}초` : '');

// 단계/토론 row를 항상 에이전트 1 → 2 → 3 순서로 확정 정렬한다.
function sortByAgentOrder(rows) {
  return [...(rows || [])].sort((a, b) => {
    const ai = Number(a.agentIndex ?? a.displayOrder ?? a.agentOrder ?? a.fromAgentIndex ?? a.agentId ?? 999);
    const bi = Number(b.agentIndex ?? b.displayOrder ?? b.agentOrder ?? b.fromAgentIndex ?? b.agentId ?? 999);
    return ai - bi;
  });
}


// ── 단계별 말풍선 (상세과정을 안 눌러도 결과를 메인 대화에 순차 표시) ──────────────
// 일반: ⚡1차 → ✅2차(웹검증) → 💬3차(피드백)
// 토론: 🗣1차 의견 → 💬서로 피드백 → ✅보완 답변 → 📌토론 정리
const STAGE_BADGES = {
  initial:    { text: '⚡ 1차 · 빠른 초안', hint: 'Ollama', color: '#f59e0b' },
  validated:  { text: '✅ 2차 · 검증 답안', hint: '웹 근거', color: '#16a34a' },
  feedback:   { text: '💬 3차 · 상호 피드백', hint: '', color: '#6366f1' },
  d_initial:  { text: '🗣 1차 입론 · 주장', hint: '', color: '#f59e0b' },
  d_feedback: { text: '⚔️ 반박', hint: '', color: '#ef4444' },
  d_revised:  { text: '🎯 최종 변론', hint: '', color: '#16a34a' },
  d_summary:  { text: '⚖️ 심사 정리 · 판단은 당신 몫', hint: '', color: '#0ea5e9' },
};

const pvForName = (pvSummary, name) => (pvSummary || []).find((p) => p.agentName === name) || null;

// 채팅 화면 라이브 모드 토글 옵션. value는 backend learningMode/mode와 그대로 일치한다.
const LEARNING_MODE_CHIPS = [
  { value: 'basic', label: '기본', icon: '💬' },
  { value: 'validation', label: '검증', icon: '✅' },
  { value: 'collaboration', label: '협업', icon: '🤝' },
  { value: 'debate', label: '토론', icon: '🗣️' },
  { value: 'socratic', label: '소크라테스', icon: '🧭' },
  { value: 'simulation', label: '상황극', icon: '🎭' },
];

// 메시지 메타데이터(사용된 모드) → 한글 라벨. "이 답변: ○○ 모드" 표시에 사용.
const LEARNING_MODE_LABEL = Object.fromEntries(LEARNING_MODE_CHIPS.map((m) => [m.value, m.label]));
const modeLabelOf = (v) => LEARNING_MODE_LABEL[String(v || '').toLowerCase()] || '기본';

// 토론으로 인정하는 값은 명시적 토론만 (discussion/tikitaka/multi_agent_discussion 제외)
const DEBATE_MODE_VALUES = new Set(['debate', '토론', '토론 모드']);
const isDebateModeValue = (value) => DEBATE_MODE_VALUES.has(String(value || '').trim().toLowerCase());

const SIMULATION_MODE_VALUES = new Set(['simulation', '상황극', '상황극 모드', '시뮬레이션', '시뮬레이션 모드']);
const isSimulationModeValue = (value) => SIMULATION_MODE_VALUES.has(String(value || '').trim().toLowerCase());

// 토론 모드 논제/구조 설정 기본값 (프론트 → Spring → FastAPI)
const DEFAULT_SIMULATION_CONFIG = {
  scenarioType: 'realistic',
  domain: 'auto',
  interactionStyle: 'choice_based',
  difficulty: 'normal',
  userRoleMode: 'auto',
  choiceCount: 3,
  includeChoices: true,
  includeConsequences: true,
  includeConceptMapping: true,
  includeMisconceptionTrap: true,
  includeReflectionQuestion: true,
  includeNextScenario: true,
  simulationDepth: 'normal',
  outputStages: [
    'SCENARIO_SETUP', 'USER_ROLE', 'SITUATION_CONTEXT', 'CHOICES',
    'CONSEQUENCE_PREVIEW', 'CONCEPT_MAPPING', 'MISCONCEPTION_TRAP',
    'REFLECTION_QUESTION', 'NEXT_SCENARIO',
  ],
};

const SIMULATION_STAGE_META = {
  SCENARIO_SETUP: { title: '상황 설정', className: 'scenario', color: '#1d4ed8' },
  USER_ROLE: { title: '나의 역할', className: 'role', color: '#7c3aed' },
  SITUATION_CONTEXT: { title: '문제 상황', className: 'context', color: '#0d9488' },
  CHOICES: { title: '선택지', className: 'choices', color: '#059669' },
  SELECTED_CHOICE: { title: '선택한 행동', className: 'choices', color: '#059669' },
  CONSEQUENCE_PREVIEW: { title: '결과 변화', className: 'consequence', color: '#ea580c' },
  CONSEQUENCE: { title: '선택 결과', className: 'consequence', color: '#ea580c' },
  CONCEPT_MAPPING: { title: '개념 연결', className: 'concept', color: '#2563eb' },
  CONCEPT_EXPLANATION: { title: '개념 설명', className: 'concept', color: '#2563eb' },
  MISCONCEPTION_TRAP: { title: '오개념 함정', className: 'trap', color: '#dc2626' },
  RISK_OR_LIMITATION: { title: '위험과 한계', className: 'trap', color: '#dc2626' },
  REFLECTION_QUESTION: { title: '성찰 질문', className: 'reflection', color: '#ca8a04' },
  NEXT_SCENARIO: { title: '다음 분기', className: 'next', color: '#4c1d95' },
  NEXT_BRANCH: { title: '다음 사건', className: 'next', color: '#4c1d95' },
  SUMMARY: { title: '상황극 요약', className: 'context', color: '#64748b' },
};

const DEFAULT_DEBATE_CONFIG = {
  topicMode: 'auto',
  manualTopic: '',
  motionType: 'learning_strategy',
  stancePolicy: 'agent1_con_agent2_pro_agent3_neutral',
  issueAxes: ['개념정확성', '학습효율', '실무적용', '오개념위험'],
  debateDepth: 'normal',
  debateStyle: 'academic_practical',
  includeExamples: true,
  includeCounterexamples: true,
  includeStudyPlan: true,
  judgeCriteria: ['논리성', '근거성', '반박력', '학습가치', '실무성'],
  outputStages: [
    'TOPIC', 'CON_OPENING', 'PRO_OPENING', 'NEUTRAL_ANALYSIS',
    'CON_REBUTTAL', 'PRO_REBUTTAL', 'NEUTRAL_CHECK',
    'CON_CLOSING', 'PRO_CLOSING', 'NEUTRAL_JUDGEMENT',
  ],
};

// 토론 설정 모달용 스타일/헬퍼
const dbLabelStyle = { fontSize: '12px', fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: '5px' };
const dbChipStyle = (active) => ({
  padding: '5px 10px', borderRadius: '999px', fontSize: '12px', fontWeight: 700, cursor: 'pointer',
  border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
  background: active ? 'var(--color-primary-soft, rgba(99,102,241,0.10))' : 'transparent',
  color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
});
const toggleInArray = (arr, value) =>
  (arr || []).includes(value) ? arr.filter((v) => v !== value) : [...(arr || []), value];

// 에이전트 카드 상단 프리셋은 "학습메이트 유형"(MATE_TYPES)으로 대체됨. 역할/톤/수준은 생성폼에서 분리 설정한다.

// 모드별 추천 에이전트 조합 (생성 모달 '추천 채우기'용)
const RECOMMENDED_PRESETS = {
  basic: ['expert_professor', 'friendly_friend', 'cold_mentor'],
  debate: ['cold_mentor', 'expert_professor', 'practical_architect'],
  socratic: ['friendly_friend', 'misconception_tracker', 'expert_professor'],
  simulation: ['creative_teacher', 'friendly_friend', 'misconception_tracker'],
};

// 소크라테스로 인정하는 값 (한글 별칭 포함)
const SOCRATIC_MODE_VALUES = new Set(['socratic', '소크라테스', '소크라테스 모드']);
const isSocraticModeValue = (value) => SOCRATIC_MODE_VALUES.has(String(value || '').trim().toLowerCase());

// 정책: 소크라테스 단계 카드(현재 이해도 진단/핵심 개념 질문/오개념 점검/단계별 힌트/적용 질문/
// 반례 질문/자기 설명 유도/정리 카드)는 "사용자가 메시지로 명시적으로 요청"했을 때만 생성·렌더한다.
// 모드 라디오에서 '소크라테스'를 골랐다는 사실만으로는 카드를 자동 출력하지 않는다.
// 일반/개념 질문("SSH가 뭐야?", "핵심만 설명해줘" 등)은 항상 평문 채팅 답변만 출력한다.
const EXPLICIT_SOCRATIC_REQUEST_RE =
  /소크라테스|소크라틱|socratic|단계별\s*(질문|학습|설명|유도)|질문\s*(하면서|으로)\s*(알려|유도|설명|진행|학습)|질문하면서|질문으로\s*유도|카드\s*(로|기반|식)|문답\s*(으로|식|형|법)/i;
const isExplicitSocraticRequest = (text) => EXPLICIT_SOCRATIC_REQUEST_RE.test(String(text || ''));

// 전송 직전 최소 정제(목표 F). 사용자가 붙여넣은 내용(SSH 명령/로그/코드블록/마크다운 ###)은
// 절대 삭제·치환하지 않는다. 공백류만 정리한다:
//  - 줄 끝의 공백/탭 제거
//  - 빈 줄 3개 이상은 2개로 축소(맥락 보존)
//  - 앞뒤 공백/줄바꿈 제거(trim)
// 길이를 임의로 자르거나 의미를 바꾸지 않는다.
const sanitizeQuestion = (raw) => {
  if (raw == null) return '';
  return String(raw)
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/^\s+|\s+$/g, '');
};

// 소크라테스 문답 설정 기본값
const DEFAULT_SOCRATIC_CONFIG = {
  goal: 'concept_understanding',
  diagnosisMode: 'quick',
  questionIntensity: 'normal',
  hintPolicy: 'step_by_step',
  answerRevealPolicy: 'final_only',
  questionTypes: ['definition', 'comparison', 'why', 'application', 'metacognition'],
  progressFlow: ['diagnosis', 'core_concept', 'misconception_check', 'hint', 'application', 'self_explanation', 'summary'],
  feedbackStyle: 'concept_check',
  maxQuestionsPerTurn: 3,
  requireUserAnswerFirst: true,
  includeExamples: true,
  includeCounterexamples: true,
  includeFinalSummary: true,
  includeNextStudyPlan: true,
  trackMisconceptions: true,
};

// ── 스터디방 학습 방식(모드) 표시용 라벨 매핑 ──
// 실제 코드 enum 값 기준(생성 모달 칩 value와 동일). 알 수 없는 값은 원문을 그대로 노출.
const labelOr = (map, v, fallback) => map[String(v || '').toLowerCase()] || (v ? String(v) : fallback);
const TOPIC_MODE_LABELS = { auto: '자동 생성', manual: '직접 입력' };
const DEBATE_DEPTH_LABELS = { light: '가볍게', normal: '보통', deep: '깊게' };
const QUESTION_INTENSITY_LABELS = { gentle: '부드럽게', normal: '보통', strict: '집중적으로' };
const HINT_STYLE_LABELS = { step_by_step: '단계별 힌트', example_hint: '예시 힌트', partial_answer_when_stuck: '막히면 일부 공개' };
const SCENARIO_TYPE_LABELS = { realistic: '현실 상황', roleplay: '면접 상황', lab_scenario: '프로젝트 상황' };
const DIFFICULTY_LABELS = { easy: '쉬움', normal: '보통', hard: '어려움' };

// ── 추천 방 설정 프리셋 (소크라테스 / 토론 / 상황극) ────────────────────────────
// 카드 클릭 시 모드 세부 설정(질문 강도·힌트·토론 깊이·상황 유형 등)과 함께 에이전트 3명을
// 한 번에 자동 반영한다. ★3명은 역할/이름/답변 톤/학습자 수준/추가 요청이 모두 서로 다르다.★
// agent.tone 값은 TONE_OPTIONS의 personality enum 값(전문적/친근함/솔직함/독특함/효율적/냉소적).
const SOCRATIC_ROOM_PRESETS = [
  {
    id: 'socratic-basic', label: '추천 방 설정 1', title: '기본 개념 유도형', mode: 'socratic',
    roomName: '000-소크라테스', purpose: '핵심 개념을 질문으로 스스로 이해',
    questionIntensity: 'normal', hintPolicy: 'step_by_step',
    agents: [
      { name: '개념 유도자', role: '핵심 개념을 질문으로 끌어내는 역할', tone: '친근함', learnerLevel: 'BACHELOR', additionalRequest: '정답을 바로 말하지 말고 쉬운 질문으로 사용자의 사고를 유도해줘.' },
      { name: '오개념 점검자', role: '사용자 답변에서 오개념과 논리적 빈틈을 찾는 역할', tone: '솔직함', learnerLevel: 'MASTER', additionalRequest: '사용자의 답변이 애매하거나 틀렸으면 근거를 들어 다시 질문해줘.' },
      { name: '정리 코치', role: '마지막에 핵심 개념과 학습 포인트를 정리하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '앞선 질문과 답변을 바탕으로 핵심 개념, 오개념 주의점, 복습 포인트를 정리해줘.' },
    ],
  },
  {
    id: 'socratic-exam', label: '추천 방 설정 2', title: '시험 대비 압박형', mode: 'socratic',
    roomName: '000-소크라테스', purpose: '시험처럼 집요하게 개념 점검',
    questionIntensity: 'strict', hintPolicy: 'partial_answer_when_stuck',
    agents: [
      { name: '출제자', role: '시험에 나올 법한 핵심 질문을 던지는 역할', tone: '솔직함', learnerLevel: 'BACHELOR', additionalRequest: '시험 상황처럼 핵심 개념을 집요하게 질문해줘.' },
      { name: '반례 질문자', role: '사용자 답변에 반례와 예외 상황을 제시하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '사용자의 답변이 성립하지 않는 조건, 예외, 반례를 질문해줘.' },
      { name: '채점 코치', role: '답변을 평가하고 보완 방향을 제시하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '답변을 채점하듯 평가하고 부족한 키워드와 보완 문장을 알려줘.' },
    ],
  },
  {
    id: 'socratic-intro', label: '추천 방 설정 3', title: '입문자 친화형', mode: 'socratic',
    roomName: '000-소크라테스', purpose: '쉬운 질문과 비유로 입문자 유도',
    questionIntensity: 'gentle', hintPolicy: 'example_hint',
    agents: [
      { name: '쉬운 질문자', role: '쉬운 질문부터 시작하는 역할', tone: '친근함', learnerLevel: 'INTRO', additionalRequest: '초보자도 답할 수 있는 쉬운 질문부터 시작해줘.' },
      { name: '비유 설명자', role: '어려운 개념을 비유로 풀어주는 역할', tone: '독특함', learnerLevel: 'BACHELOR', additionalRequest: '어려운 용어는 생활 비유와 간단한 예시로 설명해줘.' },
      { name: '복습 정리자', role: '배운 내용을 짧게 복습시키는 역할', tone: '효율적', learnerLevel: 'BACHELOR', additionalRequest: '마지막에 핵심을 3줄로 정리하고 간단한 복습 질문을 던져줘.' },
    ],
  },
  {
    id: 'socratic-correct', label: '추천 방 설정 4', title: '오개념 교정형', mode: 'socratic',
    roomName: '000-소크라테스', purpose: '틀린 이해를 발견하고 교정',
    questionIntensity: 'normal', hintPolicy: 'step_by_step',
    agents: [
      { name: '진단 질문자', role: '사용자의 현재 이해 상태를 확인하는 역할', tone: '솔직함', learnerLevel: 'BACHELOR', additionalRequest: '사용자가 지금 무엇을 어떻게 이해하고 있는지 확인하는 질문을 먼저 해줘.' },
      { name: '오류 추적자', role: '틀린 전제와 용어 혼동을 추적하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '답변 속 틀린 전제, 용어 혼동, 인과 오류가 어디서 시작됐는지 짚어줘.' },
      { name: '교정 코치', role: '올바른 개념 구조로 다시 정리하는 역할', tone: '전문적', learnerLevel: 'EXPERT', additionalRequest: '틀린 부분을 올바른 개념 구조로 다시 설명하고 비교해서 정리해줘.' },
    ],
  },
  {
    id: 'socratic-deep', label: '추천 방 설정 5', title: '심화 탐구형', mode: 'socratic',
    roomName: '000-소크라테스', purpose: '원리와 응용까지 확장 탐구',
    questionIntensity: 'strict', hintPolicy: 'example_hint',
    agents: [
      { name: '원리 질문자', role: '왜 그런지 원리 중심으로 질문하는 역할', tone: '전문적', learnerLevel: 'MASTER', additionalRequest: '단순 암기가 아니라 왜 그렇게 되는지 원리와 근거를 묻는 질문을 해줘.' },
      { name: '응용 확장자', role: '실제 사례와 확장 문제를 제시하는 역할', tone: '독특함', learnerLevel: 'EXPERT', additionalRequest: '배운 개념을 실제 사례나 한 단계 어려운 확장 문제로 연결해 질문해줘.' },
      { name: '한계 점검자', role: '적용 한계와 예외 조건을 검증하는 역할', tone: '냉소적', learnerLevel: 'EXPERT', additionalRequest: '그 개념이 통하지 않는 한계, 예외 조건, 트레이드오프를 검증해줘.' },
    ],
  },
];

const DEBATE_ROOM_PRESETS = [
  {
    id: 'debate-balanced', label: '추천 방 설정 1', title: '찬반 균형 토론형', mode: 'debate',
    roomName: '000-토론', purpose: '찬성·반대·중재로 균형 토론',
    topicMode: 'auto', debateDepth: 'normal',
    agents: [
      { name: '찬성 측', role: '주제에 찬성 근거를 제시하는 역할', tone: '전문적', learnerLevel: 'BACHELOR', additionalRequest: '찬성 입장에서 핵심 근거와 사례를 제시해줘.' },
      { name: '반대 측', role: '주제에 반대 근거를 제시하는 역할', tone: '냉소적', learnerLevel: 'BACHELOR', additionalRequest: '반대 입장에서 전제의 약점과 반박 근거를 제시해줘.' },
      { name: '중재자', role: '양쪽 주장을 비교하고 결론을 정리하는 역할', tone: '효율적', learnerLevel: 'MASTER', additionalRequest: '찬반 논거를 비교하고 균형 잡힌 결론을 정리해줘.' },
    ],
  },
  {
    id: 'debate-critical', label: '추천 방 설정 2', title: '비판 검증형', mode: 'debate',
    roomName: '000-토론', purpose: '전제·근거·논리 비약 검증',
    topicMode: 'auto', debateDepth: 'deep',
    agents: [
      { name: '주장 제시자', role: '하나의 주장을 명확히 제시하는 역할', tone: '효율적', learnerLevel: 'BACHELOR', additionalRequest: '논쟁 가능한 주장을 명확한 근거와 함께 제시해줘.' },
      { name: '비판 검증자', role: '주장 속 전제와 논리적 허점을 검증하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '전제 오류, 근거 부족, 논리적 비약을 찾아 지적해줘.' },
      { name: '결론 정리자', role: '검증 결과를 바탕으로 수정된 결론을 제시하는 역할', tone: '전문적', learnerLevel: 'EXPERT', additionalRequest: '검증 내용을 반영해 더 강한 결론과 보완 논리를 정리해줘.' },
    ],
  },
  {
    id: 'debate-presentation', label: '추천 방 설정 3', title: '발표 질의응답 대비형', mode: 'debate',
    roomName: '000-토론', purpose: '발표·세미나·구술시험 질문 대비',
    topicMode: 'manual', debateDepth: 'normal',
    agents: [
      { name: '발표자 관점', role: '발표자의 논리를 구성하는 역할', tone: '전문적', learnerLevel: 'BACHELOR', additionalRequest: '발표자가 사용할 수 있는 핵심 주장과 근거를 정리해줘.' },
      { name: '질문자 관점', role: '발표에 대한 예상 질문과 반박을 제시하는 역할', tone: '솔직함', learnerLevel: 'MASTER', additionalRequest: '교수나 평가자가 물을 법한 날카로운 질문을 제시해줘.' },
      { name: '평가자 관점', role: '발표 답변을 평가하고 개선하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '답변의 설득력, 근거, 구조를 평가하고 개선 방향을 알려줘.' },
    ],
  },
  {
    id: 'debate-method', label: '추천 방 설정 4', title: '방법론 비교형', mode: 'debate',
    roomName: '000-토론', purpose: '여러 이론·방법·접근법의 장단점 비교',
    topicMode: 'auto', debateDepth: 'deep',
    agents: [
      { name: '방법 A 옹호자', role: '첫 번째 접근법의 장점과 적용 상황을 설명하는 역할', tone: '전문적', learnerLevel: 'BACHELOR', additionalRequest: '첫 번째 이론이나 방법의 장점과 잘 맞는 적용 상황을 근거와 함께 설명해줘.' },
      { name: '방법 B 옹호자', role: '대안 접근법의 관점과 차별점을 제시하는 역할', tone: '독특함', learnerLevel: 'MASTER', additionalRequest: '대안이 되는 이론이나 방법의 관점, 차별점, 강점을 제시해줘.' },
      { name: '비교 평가자', role: '두 방법의 조건과 한계를 비교 정리하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '두 방법의 적용 조건, 한계, 적합한 상황을 비교해 정리해줘.' },
    ],
  },
  {
    id: 'debate-ethics', label: '추천 방 설정 5', title: '윤리·사회적 영향 토론형', mode: 'debate',
    roomName: '000-토론', purpose: '지식·기술·정책이 사회에 미치는 영향 토론',
    topicMode: 'auto', debateDepth: 'deep',
    agents: [
      { name: '긍정 효과 분석가', role: '기대효과와 사회적 가치를 제시하는 역할', tone: '전문적', learnerLevel: 'BACHELOR', additionalRequest: '기대되는 긍정적 효과와 사회적 가치를 근거와 함께 제시해줘.' },
      { name: '위험·한계 분석가', role: '부작용과 윤리 문제를 지적하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '예상되는 부작용, 윤리 문제, 불평등 가능성을 구체적으로 지적해줘.' },
      { name: '균형 판단자', role: '책임 있는 활용 기준을 정리하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '양쪽을 종합해 책임 있는 활용 기준과 판단 근거를 정리해줘.' },
    ],
  },
];

const ROLEPLAY_ROOM_PRESETS = [
  {
    id: 'roleplay-interview', label: '추천 방 설정 1', title: '면접·구술시험 상황극', mode: 'simulation',
    roomName: '000-상황극', purpose: '면접·구술시험처럼 질문과 피드백',
    scenarioType: 'roleplay', difficulty: 'normal',
    agents: [
      { name: '질문자', role: '기본 개념과 동기, 이해도를 묻는 역할', tone: '솔직함', learnerLevel: 'BACHELOR', additionalRequest: '면접이나 구술시험처럼 기본 개념, 동기, 이해도를 질문해줘.' },
      { name: '심화 검증자', role: '답변의 깊이와 적용 가능성을 검증하는 역할', tone: '전문적', learnerLevel: 'MASTER', additionalRequest: '답변의 깊이, 근거, 실제 상황에서의 적용 가능성을 검증하는 질문을 해줘.' },
      { name: '피드백 코치', role: '답변을 개선해주는 역할', tone: '친근함', learnerLevel: 'BACHELOR', additionalRequest: '답변의 부족한 부분을 짚고 더 좋은 답변 예시를 제시해줘.' },
    ],
  },
  {
    id: 'roleplay-professor', label: '추천 방 설정 2', title: '교수 질의응답 상황극', mode: 'simulation',
    roomName: '000-상황극', purpose: '교수의 날카로운 검증 질문 대비',
    scenarioType: 'realistic', difficulty: 'hard',
    agents: [
      { name: '교수 역할', role: '발표 내용의 핵심 개념을 검증하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '발표자가 개념을 정확히 이해했는지 날카롭게 질문해줘.' },
      { name: '근거 검증자', role: '자료, 방법, 근거, 한계를 검증하는 역할', tone: '전문적', learnerLevel: 'EXPERT', additionalRequest: '자료의 근거 부족, 방법의 한계, 대안적 접근을 중심으로 질문해줘.' },
      { name: '답변 코치', role: '교수 질문에 대한 답변을 다듬는 역할', tone: '효율적', learnerLevel: 'BACHELOR', additionalRequest: '질문에 대한 답변 구조를 정리하고 발표자가 말하기 좋은 문장으로 보완해줘.' },
    ],
  },
  {
    id: 'roleplay-seminar', label: '추천 방 설정 3', title: '학술 토의형', mode: 'simulation',
    roomName: '000-상황극', purpose: '여러 관점으로 주제를 학문적으로 토의',
    scenarioType: 'realistic', difficulty: 'normal',
    agents: [
      { name: '개념 정리자', role: '논의 주제의 핵심 개념과 배경을 정리하는 역할', tone: '친근함', learnerLevel: 'BACHELOR', additionalRequest: '논의할 주제의 핵심 개념과 배경을 알기 쉽게 정리해줘.' },
      { name: '관점 제시자', role: '다른 이론·사례·해석 관점을 제시하는 역할', tone: '독특함', learnerLevel: 'MASTER', additionalRequest: '주제에 대한 다른 이론, 사례, 해석 관점을 제시해줘.' },
      { name: '종합 정리자', role: '논의를 구조화하고 결론을 정리하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '오간 논의를 구조화하고 학문적 결론으로 정리해줘.' },
    ],
  },
  {
    id: 'roleplay-case', label: '추천 방 설정 4', title: '사례 기반 문제 해결형', mode: 'simulation',
    roomName: '000-상황극', purpose: '실제 사례·문제 상황을 분석하고 해결 전략 수립',
    scenarioType: 'lab_scenario', difficulty: 'hard',
    agents: [
      { name: '상황 파악자', role: '문제의 조건과 관련 정보를 정리하는 역할', tone: '솔직함', learnerLevel: 'BACHELOR', additionalRequest: '문제 상황의 조건, 원인 후보, 관련 정보를 먼저 정리해줘.' },
      { name: '원인 분석가', role: '개념·자료·맥락으로 원인을 분석하는 역할', tone: '전문적', learnerLevel: 'MASTER', additionalRequest: '관련 개념, 자료, 맥락을 바탕으로 문제의 원인을 분석해줘.' },
      { name: '해결 전략가', role: '해결책과 우선순위, 한계를 정리하는 역할', tone: '효율적', learnerLevel: 'EXPERT', additionalRequest: '가능한 해결책, 우선순위, 한계를 정리해 제시해줘.' },
    ],
  },
  {
    id: 'roleplay-rehearsal', label: '추천 방 설정 5', title: '발표 리허설형', mode: 'simulation',
    roomName: '000-상황극', purpose: '발표 전달력과 예상 질문 대비',
    scenarioType: 'roleplay', difficulty: 'normal',
    agents: [
      { name: '발표자 코치', role: '발표 흐름과 전달력을 개선하는 역할', tone: '친근함', learnerLevel: 'BACHELOR', additionalRequest: '발표 흐름, 도입, 전달력 측면에서 개선점을 코칭해줘.' },
      { name: '날카로운 질문자', role: '교수/평가자 관점의 질문을 제시하는 역할', tone: '냉소적', learnerLevel: 'MASTER', additionalRequest: '교수나 평가자가 던질 법한 날카로운 질문을 제시해줘.' },
      { name: '최종 평가자', role: '점수 관점에서 보완점을 정리하는 역할', tone: '전문적', learnerLevel: 'EXPERT', additionalRequest: '점수 기준으로 강점과 보완점을 정리하고 우선 개선 항목을 알려줘.' },
    ],
  },
];

const ROOM_PRESETS_BY_MODE = {
  socratic: SOCRATIC_ROOM_PRESETS,
  debate: DEBATE_ROOM_PRESETS,
  simulation: ROLEPLAY_ROOM_PRESETS,
};

// 답변 톤(personality enum/레거시 라벨) → 표시 라벨. 레거시 저장값도 정규 7종 라벨로 통일 표시한다.
const toneLabel = (v) => (v == null || v === '' ? '' : canonicalPersonalityLabel(v));

// 추천 방 설정 카드에 표시할 "적용 설정 요약" 칩 문구 배열.
// 톤/수준은 에이전트마다 다르므로 카드에는 모드 공통 세부 설정만 칩으로 노출한다.
const roomPresetSummary = (p) => {
  const out = [];
  if (p.mode === 'socratic') {
    out.push(`질문 ${QUESTION_INTENSITY_LABELS[p.questionIntensity] || p.questionIntensity}`);
    out.push(`힌트 ${HINT_STYLE_LABELS[p.hintPolicy] || p.hintPolicy}`);
  } else if (p.mode === 'debate') {
    out.push(`논제 ${TOPIC_MODE_LABELS[p.topicMode] || p.topicMode}`);
    out.push(`깊이 ${DEBATE_DEPTH_LABELS[p.debateDepth] || p.debateDepth}`);
  } else if (p.mode === 'simulation') {
    out.push(`상황 ${SCENARIO_TYPE_LABELS[p.scenarioType] || p.scenarioType}`);
    out.push(`난이도 ${DIFFICULTY_LABELS[p.difficulty] || p.difficulty}`);
  }
  out.push('에이전트 3인 개별 톤');
  return out;
};

// 방 객체(room/selectedAgent)에서 학습 방식 카드에 표시할 정보를 만든다.
// learningMode가 없으면 fallback(기본 설명 모드 + 안내)을 반환한다.
const buildRoomModeInfo = (room) => {
  const raw = String(room?.learningMode || room?.mode || '').toLowerCase();
  const accent = { debate: '#7C3AED', socratic: '#0EA5E9', simulation: '#1D4ED8', basic: '#6366F1' };

  if (isDebateModeValue(raw)) {
    const c = room?.debateConfig || {};
    const rows = [
      { k: '논제 방식', v: labelOr(TOPIC_MODE_LABELS, c.topicMode, '자동 생성') },
      { k: '토론 깊이', v: labelOr(DEBATE_DEPTH_LABELS, c.debateDepth, '보통') },
    ];
    if (String(c.topicMode).toLowerCase() === 'manual' && c.manualTopic) rows.push({ k: '논제', v: c.manualTopic });
    return { label: '토론 모드', badge: '주장 · 근거 · 반박 · 결론', color: accent.debate,
      desc: 'AI들이 하나의 논제를 두고 찬성·반대·중립 관점에서 주장, 반박, 판정을 진행합니다.', rows };
  }
  if (isSocraticModeValue(raw)) {
    const c = room?.socraticConfig || {};
    return { label: '소크라테스 모드', badge: '질문 · 힌트 · 자기설명', color: accent.socratic,
      desc: 'AI가 정답을 바로 알려주기보다 질문과 힌트로 사용자의 이해를 유도합니다.',
      rows: [
        { k: '질문 강도', v: labelOr(QUESTION_INTENSITY_LABELS, c.questionIntensity, '보통') },
        { k: '힌트 방식', v: labelOr(HINT_STYLE_LABELS, c.hintPolicy, '단계별 힌트') },
      ] };
  }
  if (isSimulationModeValue(raw)) {
    const c = room?.simulationConfig || {};
    return { label: '상황극 모드', badge: '상황 · 선택 · 피드백', color: accent.simulation,
      desc: 'AI가 현실적인 상황을 만들고, 사용자가 선택과 피드백을 통해 개념을 체험하도록 진행합니다.',
      rows: [
        { k: '상황 유형', v: labelOr(SCENARIO_TYPE_LABELS, c.scenarioType, '현실 상황') },
        { k: '난이도', v: labelOr(DIFFICULTY_LABELS, c.difficulty, '보통') },
        { k: '선택지 개수', v: `${Number(c.choiceCount) || 3}개` },
      ] };
  }
  // 기본/검증/협업 또는 모드 정보 없음 → 기본 설명 모드로 표시
  const isMissing = !raw;
  return { label: '기본 설명 모드', badge: '개념 정리 · 예시 · 핵심 요약', color: accent.basic,
    desc: isMissing
      ? '이전 방식으로 생성된 방이라 상세 모드 정보가 없습니다.'
      : 'AI들이 사용자의 질문을 중심으로 개념을 정리하고, 예시와 핵심 요약을 제공합니다.',
    rows: [{ k: '답변 구조', v: '개념 정리 · 예시 · 핵심 요약' }] };
};

const debateDisplayName = (row, fallbackIndex = 0) => {
  const idx = row?.agentIndex ?? row?.fromAgentIndex ?? row?.toAgentIndex ?? fallbackIndex + 1;
  const name = row?.agentName ?? row?.fromAgentName ?? row?.toAgentName ?? row?.fromAgent ?? row?.toAgent ?? 'AI';
  return row?.displayName || `에이전트 ${idx}(${name})`;
};

const normalizeDebateList = (rows, type) => (rows || []).map((row, idx) => {
  if (type === 'feedback') {
    const fromIdx = row.fromAgentIndex ?? idx + 1;
    const toIdx = row.toAgentIndex ?? 1;
    const fromName = row.fromAgentName || row.fromAgent || 'AI';
    const toName = row.toAgentName || row.toAgent || 'AI';
    return {
      fromAgentIndex: fromIdx,
      fromAgentName: fromName,
      toAgentIndex: toIdx,
      toAgentName: toName,
      title: row.title || `에이전트 ${fromIdx}(${fromName}) → 에이전트 ${toIdx}(${toName})`,
      feedback: row.feedback || row.answer || row.content || '',
    };
  }
  const agentIndex = row.agentIndex ?? idx + 1;
  const agentName = row.agentName || row.agent_name || row.name || 'AI';
  return {
    agentIndex,
    agentName,
    displayName: row.displayName || `에이전트 ${agentIndex}(${agentName})`,
    answer: row.answer || row.content || row.feedback || '',
  };
});

const buildDebatePayload = (data) => {
  if (!data) return null;
  const ps = data.processSteps || {};
  const initialAnswers = normalizeDebateList(data.initialAnswers || ps.initialAnswers, 'answer');
  const revisedAnswers = normalizeDebateList(data.revisedAnswers || ps.revisedAnswers, 'answer');
  let peerFeedbacks = data.peerFeedbacks;
  if (!peerFeedbacks && ps.peerFeedback) {
    const nameToIndex = new Map(initialAnswers.map((row) => [row.agentName, row.agentIndex]));
    peerFeedbacks = ps.peerFeedback.map((fb, idx) => {
      const fromName = fb.fromAgent || fb.fromAgentName || 'AI';
      const toName = fb.toAgent || fb.toAgentName || 'AI';
      const fromIdx = nameToIndex.get(fromName) || idx + 1;
      const toIdx = nameToIndex.get(toName) || ((idx + 1) % Math.max(initialAnswers.length, 1)) + 1;
      return {
        fromAgentIndex: fromIdx,
        fromAgentName: fromName,
        toAgentIndex: toIdx,
        toAgentName: toName,
        title: fb.title || `에이전트 ${fromIdx}(${fromName}) → 에이전트 ${toIdx}(${toName})`,
        feedback: fb.feedback || '',
      };
    });
  }
  peerFeedbacks = normalizeDebateList(peerFeedbacks || [], 'feedback');
  const debateSummary = data.debateSummary || ps.debateSummary || '';
  const hasExplicitDebateMode = isDebateModeValue(data.mode || data.learningMode);
  const hasDebateStructure = peerFeedbacks.length > 0 || revisedAnswers.length > 0 || !!debateSummary ||
    (Array.isArray(data.peerFeedbacks) && data.peerFeedbacks.length > 0) ||
    (Array.isArray(data.revisedAnswers) && data.revisedAnswers.length > 0) ||
    (typeof data.debateSummary === 'string' && data.debateSummary.trim().length > 0);
  if (!hasExplicitDebateMode && !hasDebateStructure) return null;
  return {
    initialAnswers: sortByAgentOrder(initialAnswers),
    peerFeedbacks: sortByAgentOrder(peerFeedbacks),
    revisedAnswers: sortByAgentOrder(revisedAnswers),
    debateSummary,
  };
};

// 구조화 토론 단계(debateStages)를 담은 단일 토론 말풍선. 채팅/마인드맵이 동일 stages를 사용한다.
const buildDebateTurnMessage = (acc, parentId, createdAt) => ({
  id: `${parentId}::debate`,
  content: '토론',
  sender: 'AI',
  senderName: '토론',
  createdAt: createdAt || new Date().toISOString(),
  parentId,
  debateStages: Array.isArray(acc?.debateStages) ? acc.debateStages : [],
  debateConfig: acc?.debateConfig || null,
});

// 하위 호환: initialAnswers/peerFeedbacks/revisedAnswers/debateSummary → 구조화 debateStages.
// 역할 정책(에이전트1=반대, 에이전트2=찬성)에 맞춰 매핑한다.
const legacyDebateToStages = (debate) => {
  if (!debate) return null;
  const init = debate.initialAnswers || [];
  const rev = debate.revisedAnswers || [];
  const fbs = debate.peerFeedbacks || [];
  const out = [];
  const mk = (stageType, stageTitle, side, role, agentIndex, agentName, content) =>
    ({ stageType, stageTitle, side, role, agentIndex, agentName, content: content || '' });
  if (init[0]) out.push(mk('OPENING_STATEMENT', '반대측 입론', 'CON', '반대측', 1, init[0].agentName, init[0].answer));
  if (init[1]) out.push(mk('OPENING_STATEMENT', '찬성측 입론', 'PRO', '찬성측', 2, init[1].agentName, init[1].answer));
  const conFb = fbs.find((f) => Number(f.fromAgentIndex) === 1) || fbs[0] || null;
  const proFb = fbs.find((f) => Number(f.fromAgentIndex) === 2 && f !== conFb) || fbs.find((f) => f !== conFb) || null;
  if (conFb) out.push(mk('REBUTTAL', '반대측 반박', 'CON', '반대측', 1, conFb.fromAgentName, conFb.feedback));
  if (proFb) out.push(mk('REBUTTAL', '찬성측 반박', 'PRO', '찬성측', 2, proFb.fromAgentName, proFb.feedback));
  if (rev[0]) out.push(mk('CLOSING_STATEMENT', '반대측 최종 변론', 'CON', '반대측', 1, rev[0].agentName, rev[0].answer));
  if (rev[1]) out.push(mk('CLOSING_STATEMENT', '찬성측 최종 변론', 'PRO', '찬성측', 2, rev[1].agentName, rev[1].answer));
  if (debate.debateSummary) out.push(mk('JUDGEMENT', '중립 판정', 'NEUTRAL', '중립 / 심사위원', 3, '중립', debate.debateSummary));
  return out.length ? out : null;
};

// 메시지에서 구조화 토론 단계 배열을 추출한다(채팅/마인드맵 공통 SSOT).
// 우선순위: message.debateStages → processSteps.debateStages → message.debate.debateStages → 레거시 변환.
const normalizeDebateStages = (message) => {
  if (!message) return null;
  const direct = message.debateStages
    || message.processSteps?.debateStages
    || message.debate?.debateStages;
  if (Array.isArray(direct) && direct.length > 0) {
    return direct.map((s) => ({
      stageType: s.stageType,
      stageTitle: s.stageTitle || s.title || s.stageType,
      side: s.side,
      role: s.role,
      agentIndex: s.agentIndex,
      agentId: s.agentId,
      agentName: s.agentName,
      content: s.content ?? s.text ?? s.answer ?? s.feedback ?? '',
    }));
  }
  const debate = message.debate || buildDebatePayload(message);
  if (!debate) return null;
  // 기본 모드(상호 피드백만 존재)를 토론으로 오인하지 않는다.
  // 진짜 토론 신호: 최종 변론(revisedAnswers) / 심사 판정(debateSummary) / 명시적 토론 모드.
  const strongDebate = (debate.revisedAnswers && debate.revisedAnswers.length > 0)
    || (debate.debateSummary && String(debate.debateSummary).trim().length > 0)
    || isDebateModeValue(message.mode || message.learningMode);
  if (!strongDebate) return null;
  return legacyDebateToStages(debate);
};

// 메시지에서 사용된 debateConfig를 추출한다(액션 프롬프트 컨텍스트용).
const debateConfigOf = (message) =>
  message?.debateConfig || message?.processSteps?.debateConfig || null;

// 소크라테스 단계 메타 (stageType → 제목/색상). 채팅/마인드맵 공통.
const SOCRATIC_STAGE_META = {
  DIAGNOSIS:          { title: '현재 이해도 진단', color: '#2563eb' },
  CORE_CONCEPT:       { title: '핵심 개념 질문',   color: '#2563eb' },
  MISCONCEPTION_CHECK:{ title: '오개념 점검',       color: '#ea580c' },
  HINT:               { title: '단계별 힌트',       color: '#ca8a04' },
  APPLICATION:        { title: '적용 질문',         color: '#059669' },
  COUNTEREXAMPLE:     { title: '반례 질문',         color: '#ea580c' },
  SELF_EXPLANATION:   { title: '자기 설명 유도',     color: '#0d9488' },
  SUMMARY:            { title: '정리 및 다음 학습 방향', color: '#7c3aed' },
  NEXT_STUDY_PLAN:    { title: '다음 학습 방향',     color: '#7c3aed' },
};

// 구조화 소크라테스 단계를 담은 단일 소크라테스 말풍선. 채팅/마인드맵이 동일 steps를 사용한다.
const buildSocraticTurnMessage = (acc, parentId, createdAt) => ({
  id: `${parentId}::socratic`,
  content: '소크라테스 문답',
  sender: 'AI',
  senderName: '소크라테스',
  createdAt: createdAt || new Date().toISOString(),
  parentId,
  isSocratic: true,
  socraticSteps: Array.isArray(acc?.socraticSteps) ? acc.socraticSteps : [],
  socraticConfig: acc?.socraticConfig || null,
});

// 메시지에서 구조화 소크라테스 단계 배열을 추출한다(채팅/마인드맵 공통 SSOT).
// 우선순위: socraticSteps → socratic.socraticSteps → processSteps.socraticSteps → answers[0].socraticSteps → answer를 SUMMARY로 변환.
const normalizeSocraticSteps = (message) => {
  if (!message) return null;
  const direct = message.socraticSteps
    || message.socratic?.socraticSteps
    || message.processSteps?.socraticSteps
    || (Array.isArray(message.answers) && message.answers[0] && message.answers[0].socraticSteps);
  if (Array.isArray(direct) && direct.length > 0) {
    return direct.map((s) => ({
      stageType: s.stageType,
      stageTitle: s.stageTitle || SOCRATIC_STAGE_META[s.stageType]?.title || s.stageType,
      role: s.role,
      agentIndex: s.agentIndex,
      agentName: s.agentName,
      question: s.question,
      hint: s.hint,
      feedback: s.feedback,
      expectedConcept: s.expectedConcept,
      misconceptionDetected: s.misconceptionDetected,
      misconception: s.misconception,
      directAnswerSuppressed: s.directAnswerSuppressed,
      content: s.content ?? s.question ?? s.hint ?? s.feedback ?? '',
    }));
  }
  // fallback: 기존 answer만 있으면 SUMMARY 단일 단계로 변환(긴 정답 카드로 표시 금지).
  const answer = message.content
    || message.answer
    || (Array.isArray(message.answers) && message.answers[0] && message.answers[0].answer);
  if (message.isSocratic && answer) {
    return [{
      stageType: 'SUMMARY', stageTitle: '정리 및 다음 학습 방향', role: '정리자',
      agentIndex: 3, content: answer, directAnswerSuppressed: false,
    }];
  }
  return null;
};

const socraticConfigOf = (message) =>
  message?.socraticConfig || message?.processSteps?.socraticConfig || null;

const simulationConfigOf = (message) =>
  message?.simulationConfig || message?.simulation?.simulationConfig || message?.processSteps?.simulationConfig || DEFAULT_SIMULATION_CONFIG;

const normalizeSimulationStages = (message) => {
  if (!message) return null;
  const direct = message.simulationStages
    || message.simulation?.simulationStages
    || message.processSteps?.simulationStages
    || (Array.isArray(message.answers) && message.answers[0] && message.answers[0].simulationStages);
  if (Array.isArray(direct) && direct.length > 0) {
    return direct.map((s, idx) => ({
      stageType: s.stageType || 'SUMMARY',
      stageTitle: s.stageTitle || SIMULATION_STAGE_META[s.stageType]?.title || s.stageType || '상황극 요약',
      role: s.role,
      agentIndex: s.agentIndex,
      agentName: s.agentName,
      content: s.content ?? s.text ?? s.answer ?? '',
      userRole: s.userRole,
      choices: Array.isArray(s.choices) ? s.choices : [],
      selectedChoiceId: s.selectedChoiceId,
      consequence: s.consequence,
      conceptMapping: Array.isArray(s.conceptMapping) ? s.conceptMapping : [],
      misconceptionTrap: s.misconceptionTrap,
      reflectionQuestion: s.reflectionQuestion,
      nextScenarioPrompt: s.nextScenarioPrompt,
      _idx: idx,
    }));
  }
  const answer = message.content
    || message.answer
    || (Array.isArray(message.answers) && message.answers[0] && message.answers[0].answer);
  if ((message.isSimulation || isSimulationModeValue(message.mode || message.learningMode)) && answer) {
    return [{ stageType: 'SUMMARY', stageTitle: '상황극 요약', role: '결과 해석자', agentIndex: 3, content: answer, choices: [], conceptMapping: [] }];
  }
  return null;
};

const buildSimulationPayload = (data) => {
  const stages = normalizeSimulationStages(data);
  if (!stages || stages.length === 0) return null;
  const choiceStage = stages.find((s) => Array.isArray(s.choices) && s.choices.length > 0);
  const roleStage = stages.find((s) => s.userRole);
  const nextStage = stages.find((s) => ['NEXT_SCENARIO', 'NEXT_BRANCH'].includes(s.stageType));
  return {
    mode: 'simulation',
    simulationConfig: simulationConfigOf(data),
    simulationStages: stages,
    scenarioTitle: data?.scenarioTitle || data?.processSteps?.scenarioTitle || stages.find((s) => s.stageType === 'SCENARIO_SETUP')?.content || '상황극 세션',
    userRole: data?.userRole || data?.processSteps?.userRole || roleStage?.userRole,
    choices: data?.choices || data?.processSteps?.choices || choiceStage?.choices || [],
    nextScenario: data?.nextScenario || data?.processSteps?.nextScenario || nextStage?.nextScenarioPrompt || nextStage?.content,
  };
};

const buildSimulationTurnMessage = (acc, parentId, createdAt) => ({
  id: `${parentId}::simulation`,
  content: '상황극',
  sender: 'AI',
  senderName: '상황극',
  createdAt: createdAt || new Date().toISOString(),
  parentId,
  isSimulation: true,
  simulationStages: Array.isArray(acc?.simulationStages) ? acc.simulationStages : [],
  simulationConfig: acc?.simulationConfig || DEFAULT_SIMULATION_CONFIG,
  scenarioTitle: acc?.scenarioTitle,
  userRole: acc?.userRole,
  choices: acc?.choices,
  nextScenario: acc?.nextScenario,
});

// buildSocraticPayload(data) — 응답/메시지에서 소크라테스 페이로드를 만든다.
const buildSocraticPayload = (data) => {
  const steps = normalizeSocraticSteps(data);
  if (!steps || steps.length === 0) return null;
  const summary = steps.find((s) => s.stageType === 'SUMMARY');
  return {
    mode: 'socratic',
    socraticConfig: socraticConfigOf(data),
    socraticSteps: steps,
    finalSummary: data?.finalSummary || data?.processSteps?.finalSummary || (summary ? summary.content : ''),
    nextStudyPlan: data?.nextStudyPlan || data?.processSteps?.nextStudyPlan || [],
  };
};

// 채팅 화면 소크라테스 렌더러 — 구조화 socraticSteps를 단계별 카드로 표시한다.
// 1차/2차/3차, 반대/찬성/중립 라벨 금지. 긴 정답 단일 카드 금지.
const SocraticRenderer = ({ steps }) => {
  if (!steps || steps.length === 0) return null;
  const cardStyle = { padding: '11px 12px', borderRadius: '8px', background: 'rgba(0,0,0,0.035)', border: '1px solid rgba(0,0,0,0.06)' };
  const metaStyle = { fontSize: '12px', fontWeight: 800, marginBottom: '5px' };
  const bodyStyle = { whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere', color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.55 };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {steps.map((s, idx) => {
        const meta = SOCRATIC_STAGE_META[s.stageType] || { title: s.stageTitle, color: '#0ea5e9' };
        return (
          <div key={`socratic-step-${s.stageType}-${idx}`} style={{ ...cardStyle, borderLeft: `3px solid ${meta.color}` }}>
            <div style={{ ...metaStyle, color: meta.color }}>
              {s.stageTitle || meta.title}{s.agentName ? ` · ${s.agentName}` : (s.role ? ` · ${s.role}` : '')}
            </div>
            <div style={bodyStyle}>{s.content || s.question || s.hint || s.feedback}</div>
            {s.misconception && (
              <div style={{ marginTop: '6px', fontSize: '12px', color: '#ea580c', fontWeight: 700 }}>⚠ 오개념: {s.misconception}</div>
            )}
          </div>
        );
      })}
    </div>
  );
};


const SimulationRenderer = ({ stages, onChoice }) => {
  if (!stages || stages.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {stages.map((s, idx) => {
        const meta = SIMULATION_STAGE_META[s.stageType] || SIMULATION_STAGE_META.SUMMARY;
        const title = s.stageTitle || meta.title;
        const body = s.content || s.consequence || s.misconceptionTrap || s.reflectionQuestion || s.nextScenarioPrompt || '';
        return (
          <div key={`simulation-stage-${s.stageType}-${s.agentIndex ?? 0}-${idx}`} className={`simulation-stage-card simulation-stage-card--${meta.className}`}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', flexWrap: 'wrap' }}>
              <span className="simulation-role-badge">{s.role || '상황극'}</span>
              <span style={{ color: meta.color, fontSize: '12px', fontWeight: 800 }}>{title}</span>
              {s.agentName && <span style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 700 }}>· {s.agentName}</span>}
            </div>
            {s.userRole && <div style={{ fontSize: '12px', fontWeight: 800, color: '#475569', marginBottom: '5px' }}>내 역할: {s.userRole}</div>}
            {body && <div style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere', color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.55 }}>{body}</div>}
            {Array.isArray(s.choices) && s.choices.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '7px', marginTop: '8px' }}>
                {/* 선택지 과다 출력 방어: 최대 20개까지만 노출(요구사항: 5개 내외, 20개 초과 금지) */}
                {s.choices.slice(0, 20).map((choice) => (
                  <button
                    type="button"
                    key={choice.choiceId || choice.label}
                    className="simulation-choice-button"
                    onClick={() => onChoice?.(choice)}
                  >
                    <strong>{choice.label || choice.choiceId}</strong>
                    <span>{choice.text}</span>
                    {choice.expectedConsequence && <small>예상 결과: {choice.expectedConsequence}</small>}
                    {choice.conceptLink && <small>연결 개념: {choice.conceptLink}</small>}
                    {choice.misconceptionRisk && <small>오개념 위험: {choice.misconceptionRisk}</small>}
                  </button>
                ))}
              </div>
            )}
            {Array.isArray(s.conceptMapping) && s.conceptMapping.length > 0 && (
              <ul style={{ margin: '8px 0 0', paddingLeft: '18px', color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.5 }}>
                {s.conceptMapping.map((item, i) => <li key={i}>{item}</li>)}
              </ul>
            )}
            {s.misconceptionTrap && <div style={{ marginTop: '7px', fontSize: '12px', color: '#dc2626', fontWeight: 800 }}>오개념 함정: {s.misconceptionTrap}</div>}
            {s.reflectionQuestion && <div style={{ marginTop: '7px', fontSize: '12px', color: '#a16207', fontWeight: 800 }}>성찰 질문: {s.reflectionQuestion}</div>}
          </div>
        );
      })}
    </div>
  );
};

// side별 강조색 (CON 주황 / PRO 초록 / NEUTRAL 보라 / TOPIC 파랑)
const DEBATE_SIDE_COLOR = { CON: '#ea580c', PRO: '#059669', NEUTRAL: '#7c3aed', TOPIC: '#2563eb' };

// 채팅 화면 토론 렌더러 — 구조화 debateStages를 그대로 표시한다.
// "1차 의견 / 서로 피드백 / 보완 답변 / 토론 정리" 라벨은 절대 쓰지 않는다.
const DebateRenderer = ({ stages }) => {
  if (!stages || stages.length === 0) return null;
  const cardStyle = { padding: '11px 12px', borderRadius: '8px', background: 'rgba(0,0,0,0.035)', border: '1px solid rgba(0,0,0,0.06)' };
  const metaStyle = { fontSize: '12px', fontWeight: 800, marginBottom: '5px' };
  const bodyStyle = { whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere', color: 'var(--color-text-muted)', fontSize: '13px', lineHeight: 1.55 };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {stages.map((s, idx) => {
        const accent = DEBATE_SIDE_COLOR[s.side] || '#64748b';
        return (
          <div key={`debate-stage-${s.stageType}-${s.side}-${idx}`} style={{ ...cardStyle, borderLeft: `3px solid ${accent}` }}>
            <div style={{ ...metaStyle, color: accent }}>
              {s.stageTitle}{s.agentName && s.side !== 'TOPIC' ? ` · ${s.agentName}` : ''}
            </div>
            <div style={bodyStyle}>{s.content}</div>
          </div>
        );
      })}
    </div>
  );
};

// processSteps(전체 map) → 결과 말풍선 배열. 토론 응답이면 토론 4섹션, 아니면 1/2/3 단계.
// ── 내부 단계(검증/피드백) 노출 정책 ──────────────────────────────────────────
// 기본 채팅(basic)은 1차(=노출용 최종) 답변만 top-level로 보여주고, 2차 검증/3차 상호 피드백은
//  내부 단계로 숨긴다(에이전트 수 × 단계 수만큼 카드가 폭발하는 것을 막는다).
// 검증(validation)/협업(collaboration) 모드는 평가/피드백이 모드의 목적이므로 내부 단계를 노출한다.
// (개별 단계 생성 여부는 FastAPI/ai07가 stagePolicy/enable* 플래그로 결정 — 도착하지 않으면 1차만 표시.)
const isInternalVisibleMode = (mode) => {
  const m = String(mode || '').toLowerCase();
  // 기본/빈 모드는 내부 단계(2차 검증·3차 상호 피드백)를 top-level 카드로 노출하지 않는다.
  //  (3에이전트 × 3단계 = 9카드 폭발 방지. 백엔드도 2·3차를 visible=false로 내려보낸다.)
  //  사용자가 명시적으로 평가/협업을 고른 모드에서만 내부 단계를 노출한다.
  return m === 'validation' || m === '검증'
    || m === 'collaboration' || m === 'collaborative' || m === '협업';
};

// 방어적 필터: FastAPI/Spring이 실수로 내부 evaluator 문구를 visible로 흘려도 기본 채팅에선 숨긴다.
// (사용자가 명시적으로 평가/피드백을 요청한 모드에서는 isInternalVisibleMode로 노출 허용)
// 강한(템플릿/디버그) 마커만 사용한다. "보완점/수정 제안" 같은 일반 단어는 정상 답변에도 나올 수 있어
// 오탐(정상 답변 숨김)을 막기 위해 단독으로는 쓰지 않는다.
const INTERNAL_LEAK_PATTERNS = [
  '두 에이전트의 답변을 평가', '답변을 평가해보겠습니다', '1차 답변을 검증', '1차 답변(들)을 검토',
  '내부 검증 결과', '2차 생성 내용', 'PEER_FEEDBACK', 'INTERNAL_VALIDATION', 'RAW_MODEL_OUTPUT', 'ROUTE_DECISION',
];
const looksInternalLeak = (content) => {
  const s = String(content || '');
  return INTERNAL_LEAK_PATTERNS.some((p) => s.includes(p));
};

// ── 경량 마크다운 렌더러 (react-markdown 의존성 없이 raw **, ###, ``` 노출 방지) ──
// 코드블록/인라인코드/굵게/헤딩/리스트만 안전 렌더링한다. 그 외는 평문으로 보여준다.
const renderInlineNodes = (line, keyBase) => {
  const nodes = [];
  const regex = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = regex.exec(line)) !== null) {
    if (m.index > last) nodes.push(line.slice(last, m.index));
    if (m[1] != null) nodes.push(<strong key={`${keyBase}-b${i}`}>{m[1]}</strong>);
    else nodes.push(<code key={`${keyBase}-c${i}`} style={{ background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 4, fontSize: '0.92em' }}>{m[2]}</code>);
    last = m.index + m[0].length;
    i += 1;
  }
  if (last < line.length) nodes.push(line.slice(last));
  return nodes;
};

const RichText = ({ text }) => {
  const src = String(text ?? '');
  if (!src) return null;
  const segments = src.split('```');
  return (
    <>
      {segments.map((seg, si) => {
        if (si % 2 === 1) {
          // 코드블록: 첫 줄이 언어 라벨일 수 있음
          const nl = seg.indexOf('\n');
          const lang = nl > -1 ? seg.slice(0, nl).trim() : '';
          const isLang = nl > -1 && /^[a-zA-Z0-9+#.-]{0,15}$/.test(lang);
          const code = isLang ? seg.slice(nl + 1) : seg;
          return (
            <pre key={`code-${si}`} style={{ background: '#0f172a', color: '#e2e8f0', padding: '10px 12px', borderRadius: 8, overflowX: 'auto', fontSize: 12, lineHeight: 1.5, margin: '6px 0' }}>
              <code>{code.replace(/\n$/, '')}</code>
            </pre>
          );
        }
        const lines = seg.split('\n');
        return (
          <span key={`txt-${si}`}>
            {lines.map((rawLine, li) => {
              const key = `${si}-${li}`;
              const heading = rawLine.match(/^(#{1,6})\s+(.*)$/);
              if (heading) {
                return <div key={key} style={{ fontWeight: 700, margin: '4px 0' }}>{renderInlineNodes(heading[2], key)}</div>;
              }
              const list = rawLine.match(/^\s*[-*]\s+(.*)$/);
              const content = list ? `• ${list[1]}` : rawLine;
              return (
                <React.Fragment key={key}>
                  {renderInlineNodes(content, key)}
                  {li < lines.length - 1 ? <br /> : null}
                </React.Fragment>
              );
            })}
          </span>
        );
      })}
    </>
  );
};

// 인사/욕설/라우팅 등 short direct reply는 마크다운 기호를 제거한 평문으로 표시한다.
const stripMarkdown = (s) => String(s || '')
  .replace(/```[\s\S]*?```/g, '')
  .replace(/\*\*(.+?)\*\*/g, '$1')
  .replace(/`([^`]+)`/g, '$1')
  .replace(/^#{1,6}\s+/gm, '')
  .replace(/^\s*[-*]\s+/gm, '• ')
  .trim();

const buildStageBubbles = (ps, parentId, createdAt, opts = {}) => {
  if (!ps) return [];
  const ts = createdAt || new Date().toISOString();
  const out = [];
  const mk = (key, name, content, extra) => ({
    id: `${parentId}::${name}::${key}::${extra?.idx ?? 0}`,
    content,
    sender: 'AI',
    senderName: name,
    badge: STAGE_BADGES[key],
    badgeKey: key,
    createdAt: ts,
    parentId,
    ...extra,
  });

  // 토론 모드 감지: revisedAnswers 또는 debateSummary가 있으면 토론 응답이다.
  const isDebate = (ps.revisedAnswers && ps.revisedAnswers.length > 0) || !!ps.debateSummary;
  if (isDebate) {
    sortByAgentOrder(ps.initialAnswers).forEach((r, idx) => out.push(mk('d_initial', r.agentName, stepContent(r), { idx })));
    sortByAgentOrder(ps.peerFeedback).forEach((fb, idx) => out.push(mk('d_feedback', fb.fromAgent, stepContent(fb), {
      idx, stageTo: fb.toAgent, pv: fb.personalityValidation || pvForName(ps.personalityValidationSummary, fb.fromAgent),
    })));
    sortByAgentOrder(ps.revisedAnswers).forEach((r, idx) => out.push(mk('d_revised', r.agentName, stepContent(r), { idx })));
    if (ps.debateSummary) out.push(mk('d_summary', '토론 정리', ps.debateSummary, { idx: 0 }));
    return out;
  }

  // 일반 staged 모드 — 1차(최종 답변)는 항상 노출. 2차 검증/3차 피드백은 내부 단계이므로
  // 기본 채팅에서는 숨기고, 검증/협업 모드(showInternal)에서만 노출한다.
  sortByAgentOrder(ps.initialAnswers).forEach((row, idx) => {
    const c = coerceAgentText(stepContent(row), { stage: 'FIRST_DRAFT', agentName: row.agentName, idx });
    out.push(mk('initial', row.agentName, c.text, { idx, provider: row.provider, elapsedMs: row.elapsedMs, isError: !c.ok, validation: extractValidation(row) }));
  });
  if (opts.showInternal) {
    sortByAgentOrder(ps.validatedAnswers).forEach((row, idx) => {
      const c = coerceAgentText(stepContent(row), { stage: 'VALIDATION', agentName: row.agentName, idx });
      out.push(mk('validated', row.agentName, c.text, {
        idx, provider: row.provider, elapsedMs: row.elapsedMs, sources: row.sources || [], isError: !c.ok, validation: extractValidation(row),
      }));
    });
    sortByAgentOrder(ps.peerFeedback).forEach((fb, idx) => {
      const c = coerceAgentText(stepContent(fb), { stage: 'PEER_FEEDBACK', agentName: fb.fromAgent, idx });
      out.push(mk('feedback', fb.fromAgent, c.text, {
        idx, stageTo: fb.toAgent, pv: fb.personalityValidation || pvForName(ps.personalityValidationSummary, fb.fromAgent), isError: !c.ok,
      }));
    });
  }
  return out;
};

// DB 기록(에이전트마다 전체 map을 중복 저장)을 같은 턴당 1회만 결과 말풍선으로 폭발시킨다.
const explodeHistoryToStageBubbles = (history) => {
  if (!Array.isArray(history)) return history;
  const out = [];
  const seenTurn = new Set();
  for (const msg of history) {
    const stages = msg && msg.sender === 'AI' ? normalizeDebateStages(msg) : null;
    if (stages && stages.length > 0) {
      const summary = stages.find((s) => s.stageType === 'JUDGEMENT')?.content || '';
      const debateKey = `${summary}::${stages[0]?.content || ''}`.slice(0, 240);
      const turnKey = msg.parentId ?? `debate::${debateKey}`;
      if (seenTurn.has(turnKey)) continue;
      seenTurn.add(turnKey);
      // debateConfig는 마인드맵 액션 프롬프트용으로 보존한다.
      out.push({ ...msg, debateStages: stages, debateConfig: debateConfigOf(msg), processSteps: undefined, content: msg.content || '토론' });
      continue;
    }
    // 소크라테스 복원: processSteps.socraticSteps가 있으면 같은 턴 1회만 단일 소크라테스 말풍선으로 폭발.
    const socSteps = msg && msg.sender === 'AI' ? normalizeSocraticSteps(msg) : null;
    if (socSteps && socSteps.length > 0) {
      const summary = socSteps.find((s) => s.stageType === 'SUMMARY')?.content || '';
      const socKey = `${summary}::${socSteps[0]?.content || ''}`.slice(0, 240);
      const turnKey = msg.parentId ?? `socratic::${socKey}`;
      if (seenTurn.has(turnKey)) continue;
      seenTurn.add(turnKey);
      out.push({ ...msg, isSocratic: true, socraticSteps: socSteps, socraticConfig: socraticConfigOf(msg), processSteps: undefined, content: msg.content || '소크라테스 문답' });
      continue;
    }
    const simPayload = msg && msg.sender === 'AI' ? buildSimulationPayload(msg) : null;
    if (simPayload && simPayload.simulationStages.length > 0) {
      const simKey = `${simPayload.scenarioTitle || ''}::${simPayload.simulationStages[0]?.content || ''}`.slice(0, 240);
      const turnKey = msg.parentId ?? `simulation::${simKey}`;
      if (seenTurn.has(turnKey)) continue;
      seenTurn.add(turnKey);
      out.push({ ...msg, isSimulation: true, simulationStages: simPayload.simulationStages, simulationConfig: simPayload.simulationConfig, processSteps: undefined, content: msg.content || '상황극' });
      continue;
    }
    const ps = msg && msg.sender === 'AI' ? msg.processSteps : null;
    const hasStages = ps && ((ps.initialAnswers && ps.initialAnswers.length) || (ps.validatedAnswers && ps.validatedAnswers.length) || (ps.peerFeedback && ps.peerFeedback.length));
    if (hasStages) {
      const turnKey = msg.parentId ?? msg.id;
      if (seenTurn.has(turnKey)) continue; // 같은 턴 중복 에이전트 메시지는 건너뜀
      seenTurn.add(turnKey);
      const bubbles = buildStageBubbles(ps, turnKey, msg.createdAt, { showInternal: isInternalVisibleMode(msg.mode || msg.learningMode) });
      if (bubbles.length) { out.push(...bubbles); continue; }
    }
    out.push(msg);
  }
  return out;
};

// ── 마인드맵 전용 토론 노드 변환 ───────────────────────────────────────────────
//  채팅 히스토리를 그대로 마인드맵에 넘기지 않는다. 토론 응답(msg.debate 또는
//  buildDebatePayload(msg))은 논제→입론→반박→재반박→최종변론→판정 트리로 펼치고,
//  일반 메시지는 그대로 둔다. (라이브 응답과 새로고침 복원이 동일 구조를 갖게 한다.)

const debateExcerpt = (text, n = 28) => {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  return t.length > n ? `${t.slice(0, n)}...` : t;
};

// stageType별 카드 제목(찬성측/반대측 접두어 포함)
const debateStageTitle = (side, stageType) => {
  if (stageType === 'TOPIC') return '논제';
  if (stageType === 'JUDGEMENT') return '중립 판정';
  if (stageType === 'NEUTRAL_ANALYSIS') return '중립 쟁점 정리';
  if (stageType === 'NEUTRAL_CHECK') return '중립 검토';
  const prefix = side === 'PRO' ? '찬성측' : side === 'CON' ? '반대측' : side === 'NEUTRAL' ? '중립' : '';
  const base = ({
    OPENING_STATEMENT: '입론',
    REBUTTAL: '반박',
    CROSS_REBUTTAL: '재반박',
    CLOSING_STATEMENT: '최종 변론',
  })[stageType] || stageType;
  return `${prefix} ${base}`.trim();
};

const debateRoleLabel = (side) =>
  side === 'PRO' ? '찬성측' : side === 'CON' ? '반대측'
    : (side === 'JUDGE' || side === 'NEUTRAL') ? '중립' : '논제';

// 구조화 debateStages → 마인드맵 노드 스펙. NEUTRAL(중립) 단계도 지원한다.
const debateStagesToSpecs = (stages) => {
  const sidePrefix = (side) => {
    const s = String(side || '').toUpperCase();
    return s === 'PRO' ? 'pro' : s === 'CON' ? 'con' : 'neutral';
  };
  const keyFor = (stageType, side) => {
    if (stageType === 'TOPIC') return 'topic';
    if (stageType === 'JUDGEMENT') return 'judge';
    if (stageType === 'NEUTRAL_ANALYSIS') return 'neutral_analysis';
    if (stageType === 'NEUTRAL_CHECK') return 'neutral_check';
    const p = sidePrefix(side);
    return {
      OPENING_STATEMENT: `${p}_open`,
      REBUTTAL: `${p}_rebut`,
      CROSS_REBUTTAL: `${p}_cross`,
      CLOSING_STATEMENT: `${p}_close`,
    }[stageType] || `${p}_${String(stageType || '').toLowerCase()}`;
  };
  return (stages || []).map((s) => {
    const stageType = String(s.stageType || '').toUpperCase();
    const side = String(s.side || (stageType === 'TOPIC' ? 'TOPIC' : '')).toUpperCase();
    return {
      key: keyFor(stageType, side),
      stageType,
      side,
      role: debateRoleLabel(side),
      title: s.stageTitle || debateStageTitle(side, stageType),
      agentId: s.agentId,
      agentIndex: s.agentIndex,
      agentName: s.agentName || s.agent_name,
      content: s.content ?? s.text ?? s.answer ?? s.feedback ?? '',
    };
  });
};

// 하위 호환: initialAnswers / peerFeedbacks / revisedAnswers / debateSummary → 토론 단계 스펙.
//  (UI엔 "1차 의견 / 서로 피드백 / 보완 답변" 같은 단어를 절대 노출하지 않는다.)
const legacyDebateToSpecs = (debate, topicText) => {
  const init = debate.initialAnswers || [];
  const rev = debate.revisedAnswers || [];
  const fbs = debate.peerFeedbacks || [];
  const proInit = init[0];
  const conInit = init[1];
  const proRev = rev[0];
  const conRev = rev[1];
  // 반박: fromAgentIndex 1 → 찬성측, 2 → 반대측 (없으면 순서로 분배)
  const proFb = fbs.find((f) => Number(f.fromAgentIndex) === 1) || fbs[0] || null;
  const conFb = fbs.find((f) => Number(f.fromAgentIndex) === 2 && f !== proFb)
    || fbs.find((f) => f !== proFb) || null;

  const specs = [];
  specs.push({ key: 'topic', stageType: 'TOPIC', side: 'TOPIC', role: '논제', title: '논제', content: topicText });
  if (proInit) specs.push({ key: 'pro_open', stageType: 'OPENING_STATEMENT', side: 'PRO', role: '찬성', title: '찬성측 입론', agentName: proInit.agentName, agentIndex: proInit.agentIndex, content: proInit.answer });
  if (conInit) specs.push({ key: 'con_open', stageType: 'OPENING_STATEMENT', side: 'CON', role: '반대', title: '반대측 입론', agentName: conInit.agentName, agentIndex: conInit.agentIndex, content: conInit.answer });
  if (proFb) specs.push({ key: 'pro_rebut', stageType: 'REBUTTAL', side: 'PRO', role: '찬성', title: '찬성측 반박', agentName: proFb.fromAgentName, agentIndex: proFb.fromAgentIndex, content: proFb.feedback });
  if (conFb) specs.push({ key: 'con_rebut', stageType: 'REBUTTAL', side: 'CON', role: '반대', title: '반대측 반박', agentName: conFb.fromAgentName, agentIndex: conFb.fromAgentIndex, content: conFb.feedback });
  if (proRev) specs.push({ key: 'pro_close', stageType: 'CLOSING_STATEMENT', side: 'PRO', role: '찬성', title: '찬성측 최종 변론', agentName: proRev.agentName, agentIndex: proRev.agentIndex, content: proRev.answer });
  if (conRev) specs.push({ key: 'con_close', stageType: 'CLOSING_STATEMENT', side: 'CON', role: '반대', title: '반대측 최종 변론', agentName: conRev.agentName, agentIndex: conRev.agentIndex, content: conRev.answer });
  if (debate.debateSummary) specs.push({ key: 'judge', stageType: 'JUDGEMENT', side: 'JUDGE', role: '심사위원', title: '심사위원 판정', agentName: '심사위원', content: debate.debateSummary });
  return specs;
};

// 토론 단계 스펙 사이의 부모 연결 우선순위(가까운 조상부터). 중간 단계가 없으면 위로 폴백한다.
const DEBATE_PARENT_CHAIN = {
  topic: [],
  con_open: ['topic'],
  pro_open: ['topic'],
  neutral_analysis: ['topic'],
  con_rebut: ['pro_open', 'topic'],
  pro_rebut: ['con_open', 'topic'],
  neutral_check: ['neutral_analysis', 'topic'],
  pro_cross: ['con_rebut', 'con_open', 'topic'],
  con_cross: ['pro_rebut', 'pro_open', 'topic'],
  con_close: ['con_cross', 'con_rebut', 'con_open', 'topic'],
  pro_close: ['pro_cross', 'pro_rebut', 'pro_open', 'topic'],
  judge: ['neutral_check', 'neutral_analysis', 'topic'],
};

// 토론 메시지 1개 → 마인드맵 노드 배열. 안정적인 id를 사용해 새로고침 후에도 동일 구조 재현.
const debateToMindmapNodes = (message, stages, topicText, debateConfig) => {
  const baseId = String(message.id);
  const rootQuestionId = message.parentId != null ? message.parentId : baseId;
  const createdAt = message.createdAt || new Date().toISOString();

  let specs = debateStagesToSpecs(stages || []);
  // TOPIC 단계가 없으면 사용자 질문/논제로 합성 토픽 노드를 맨 앞에 둔다.
  if (!specs.some((s) => s.key === 'topic')) {
    specs = [{ key: 'topic', stageType: 'TOPIC', side: 'TOPIC', role: '논제', title: '논제', content: topicText }, ...specs];
  }
  // 액션 프롬프트 컨텍스트(논제/쟁점 축)
  const topicForCtx = specs.find((s) => s.key === 'topic')?.content || topicText;
  const issueAxes = debateConfig?.issueAxes || [];

  const idFor = (s) => `${baseId}::debate::${s.stageType}::${s.side}::${s.agentId ?? s.agentIndex ?? s.key}`;

  const emittedIdByKey = new Map();
  const nodes = [];
  for (const s of specs) {
    if (!s.content || !String(s.content).trim()) continue;
    const id = idFor(s);
    let parentId;
    if (s.key === 'topic') {
      parentId = rootQuestionId;
    } else {
      const chain = DEBATE_PARENT_CHAIN[s.key] || ['topic'];
      let resolved = null;
      for (const k of chain) {
        if (emittedIdByKey.has(k)) { resolved = emittedIdByKey.get(k); break; }
      }
      parentId = resolved || emittedIdByKey.get('topic') || rootQuestionId;
    }
    emittedIdByKey.set(s.key, id);
    nodes.push({
      id,
      parentId,
      sender: 'AI',
      senderName: s.agentName || s.title,
      content: s.content,
      createdAt,
      nodeType: 'debate',
      stageType: s.stageType,
      stageTitle: s.title,
      side: s.side,
      role: s.role,
      agentId: s.agentId,
      agentName: s.agentName,
      actionContext: {
        stageType: s.stageType,
        side: s.side,
        agentName: s.agentName,
        contentExcerpt: debateExcerpt(s.content),
        topic: debateExcerpt(topicForCtx, 60),
        issueAxes,
      },
    });
  }
  return nodes;
};

// 소크라테스 단계는 직렬 체인으로 연결한다(이전 단계 → 다음 단계).
const socraticToMindmapNodes = (message, steps, socraticConfig) => {
  const baseId = String(message.id);
  const rootQuestionId = message.parentId != null ? message.parentId : baseId;
  const createdAt = message.createdAt || new Date().toISOString();
  const issueGoal = socraticConfig?.goal || '';

  // 세션 루트 노드(나의 질문 아래) → 그 아래에 각 단계를 직렬로 체인.
  const sessionId = `${baseId}::socratic::SESSION::0`;
  const nodes = [{
    id: sessionId, parentId: rootQuestionId, sender: 'AI',
    senderName: '소크라테스 세션', content: '질문·힌트·오개념 점검으로 스스로 답을 찾는 문답 세션',
    createdAt, nodeType: 'socratic', stageType: 'SESSION', stageTitle: '소크라테스 세션',
    role: '세션', agentIndex: 0,
    actionContext: { stageType: 'SESSION', goal: issueGoal },
  }];

  let prevId = sessionId;
  for (const s of steps) {
    if (!s.content && !s.question && !s.hint && !s.feedback) continue;
    const content = s.content || s.question || s.hint || s.feedback || '';
    const id = `${baseId}::socratic::${s.stageType}::${s.agentIndex ?? 0}`;
    nodes.push({
      id, parentId: prevId, sender: 'AI',
      senderName: s.agentName || s.role || '튜터',
      content, createdAt,
      nodeType: 'socratic',
      stageType: s.stageType,
      stageTitle: s.stageTitle || SOCRATIC_STAGE_META[s.stageType]?.title || s.stageType,
      role: s.role,
      agentIndex: s.agentIndex,
      agentName: s.agentName,
      misconception: s.misconception,
      actionContext: {
        stageType: s.stageType,
        contentExcerpt: debateExcerpt(content),
        goal: issueGoal,
      },
    });
    prevId = id;
  }
  return nodes;
};

const simulationStageContent = (s) => {
  if (!s) return '';
  if (s.content) return s.content;
  if (s.userRole) return s.userRole;
  if (s.consequence) return s.consequence;
  if (s.misconceptionTrap) return s.misconceptionTrap;
  if (s.reflectionQuestion) return s.reflectionQuestion;
  if (s.nextScenarioPrompt) return s.nextScenarioPrompt;
  if (Array.isArray(s.conceptMapping) && s.conceptMapping.length) return s.conceptMapping.join('\n');
  return '';
};

const simulationToMindmapNodes = (message, payload) => {
  const baseId = String(message.id);
  const rootQuestionId = message.parentId != null ? message.parentId : baseId;
  const createdAt = message.createdAt || new Date().toISOString();
  const stages = payload?.simulationStages || [];
  const config = payload?.simulationConfig || DEFAULT_SIMULATION_CONFIG;
  const sessionId = `${baseId}::simulation::SESSION::0`;
  const nodes = [{
    id: sessionId,
    parentId: rootQuestionId,
    sender: 'AI',
    senderName: '상황극 세션',
    content: payload?.scenarioTitle || '상황 속 역할을 맡아 선택하고, 결과로 개념을 체험하는 세션',
    createdAt,
    nodeType: 'simulation',
    stageType: 'SESSION',
    stageTitle: '상황극 세션',
    role: '세션',
    agentIndex: 0,
    actionContext: { stageType: 'SESSION' },
    simulationConfig: config,
  }];
  const byStage = new Map();
  let lastStageId = sessionId;
  const parentFor = (stageType) => {
    if (stageType === 'SCENARIO_SETUP') return sessionId;
    if (stageType === 'USER_ROLE') return byStage.get('SCENARIO_SETUP') || sessionId;
    if (stageType === 'SITUATION_CONTEXT') return byStage.get('USER_ROLE') || byStage.get('SCENARIO_SETUP') || sessionId;
    if (stageType === 'CHOICES') return byStage.get('SITUATION_CONTEXT') || lastStageId;
    if (['CONCEPT_MAPPING', 'MISCONCEPTION_TRAP', 'REFLECTION_QUESTION', 'NEXT_SCENARIO'].includes(stageType)) return byStage.get('CHOICES') || lastStageId;
    if (['SELECTED_CHOICE', 'CONSEQUENCE', 'CONCEPT_EXPLANATION', 'RISK_OR_LIMITATION', 'NEXT_BRANCH'].includes(stageType)) return lastStageId;
    return lastStageId;
  };

  for (const s of stages) {
    const content = simulationStageContent(s);
    const stageType = s.stageType || 'SUMMARY';
    const id = `${baseId}::simulation::${stageType}::${s.agentIndex ?? s._idx ?? 0}`;
    const parentId = parentFor(stageType);
    nodes.push({
      id, parentId, sender: 'AI', senderName: s.agentName || s.role || '상황극', content,
      createdAt, nodeType: 'simulation', stageType, stageTitle: s.stageTitle || SIMULATION_STAGE_META[stageType]?.title || stageType,
      role: s.role, agentIndex: s.agentIndex, agentName: s.agentName,
      actionContext: { stageType, contentExcerpt: debateExcerpt(content), choiceLabel: s.selectedChoiceId },
      simulationConfig: config,
    });
    byStage.set(stageType, id);
    lastStageId = id;

    if (Array.isArray(s.choices) && s.choices.length > 0) {
      s.choices.forEach((choice) => {
        const choiceId = choice.choiceId || choice.label;
        const cid = `${baseId}::simulation::CHOICE::${choiceId}`;
        nodes.push({
          id: cid, parentId: id, sender: 'AI', senderName: s.agentName || '사건 진행자',
          content: choice.text || '', createdAt, nodeType: 'simulation', stageType: 'CHOICE', stageTitle: `선택 ${choice.label || choiceId}`,
          role: '선택지', agentIndex: s.agentIndex, agentName: s.agentName, choiceId, label: choice.label || choiceId,
          actionContext: { stageType: 'CHOICE', choiceLabel: choice.label || choiceId, contentExcerpt: debateExcerpt(choice.text) },
          simulationConfig: config,
        });
        [
          ['예상 결과', choice.expectedConsequence],
          ['연결 개념', choice.conceptLink],
          ['오개념 위험', choice.misconceptionRisk],
        ].forEach(([title, text]) => {
          if (!text) return;
          nodes.push({
            id: `${cid}::${title}`, parentId: cid, sender: 'AI', senderName: title, content: text,
            createdAt, nodeType: 'simulation', stageType: title === '예상 결과' ? 'CONSEQUENCE' : title === '연결 개념' ? 'CONCEPT_MAPPING' : 'MISCONCEPTION_TRAP',
            stageTitle: title, role: '선택 분석', choiceId, label: choice.label || choiceId,
            actionContext: { stageType: title, choiceLabel: choice.label || choiceId, contentExcerpt: debateExcerpt(text) },
            simulationConfig: config,
          });
        });
      });
    }
  }
  return nodes;
};

// AI 메시지 중 토론/소크라테스/상황극 메시지만 노드 여러 개로 확장하고, 일반 메시지는 그대로 둔다.
const expandDebateMessagesForMindmap = (messages) => {
  if (!Array.isArray(messages)) return [];
  const byId = new Map(messages.map((m) => [m.id, m]));
  const out = [];
  const seenIds = new Set(); // node.id 기준 중복 방지(SSE 단계+all_complete 동시 도착 대비)
  const pushUnique = (node) => {
    if (node && node.id != null) {
      if (seenIds.has(node.id)) return;
      seenIds.add(node.id);
    }
    out.push(node);
  };
  for (const msg of messages) {
    const stages = msg && msg.sender === 'AI' ? normalizeDebateStages(msg) : null;
    if (stages && stages.length > 0) {
      const parent = msg.parentId != null ? byId.get(msg.parentId) : null;
      const topicText = stages.find((s) => s.stageType === 'TOPIC')?.content
        || (parent && parent.content) || msg.content || '토론 논제';
      debateToMindmapNodes(msg, stages, topicText, debateConfigOf(msg)).forEach(pushUnique);
      continue;
    }
    const socSteps = msg && msg.sender === 'AI' ? normalizeSocraticSteps(msg) : null;
    if (socSteps && socSteps.length > 0) {
      socraticToMindmapNodes(msg, socSteps, socraticConfigOf(msg)).forEach(pushUnique);
      continue;
    }
    const simPayload = msg && msg.sender === 'AI' ? buildSimulationPayload(msg) : null;
    if (simPayload && simPayload.simulationStages.length > 0) {
      simulationToMindmapNodes(msg, simPayload).forEach(pushUnique);
      continue;
    }
    pushUnique(msg);
  }
  return out;
};

// 마인드맵 뷰가 받는 메시지 = 채팅 히스토리를 토론/소크라테스 구조로 확장한 결과.
const buildMindmapMessages = (chatHistory) => expandDebateMessagesForMindmap(chatHistory);

// ── 토론 노드 액션 버튼 클릭 시 입력창에 채워질 프롬프트 ──────────────────────────
const DEBATE_ACTION_PROMPTS = {
  pro_argument: (ex) => `@모두 이 논제 "${ex}"에 대해 찬성측 입장에서 핵심 근거와 논리를 입론으로 정리해줘.`,
  con_argument: (ex) => `@모두 이 논제 "${ex}"에 대해 반대측 입장에서 핵심 근거와 논리를 입론으로 정리해줘.`,
  issue_summary: (ex) => `@모두 이 논제 "${ex}"의 핵심 쟁점을 찬성/반대로 나눠 정리해줘.`,
  con_rebut: (ex) => `@모두 방금 찬성측이 제시한 "${ex}" 주장에 대해, 반대측 입장에서 핵심 전제를 공격하고 논리적 반박을 작성해줘.`,
  pro_rebut: (ex) => `@모두 방금 반대측이 제시한 "${ex}" 주장에 대해, 찬성측 입장에서 반례와 근거를 들어 반박해줘.`,
  con_cross_rebut: (ex) => `@모두 방금 찬성측 반박 "${ex}"에 대해, 반대측 재반박을 작성해줘. 상대 논리의 약점을 직접 지적해야 해.`,
  pro_cross_rebut: (ex) => `@모두 방금 반대측 반박 "${ex}"에 대해, 찬성측 재반박을 작성해줘. 상대 논리의 약점을 직접 지적해야 해.`,
  strengthen_pro: (ex) => `@모두 찬성측 주장 "${ex}"을 더 강하게 만들 수 있는 추가 근거, 사례, 조건을 제시해줘.`,
  strengthen_con: (ex) => `@모두 반대측 주장 "${ex}"을 더 강하게 만들 수 있는 추가 근거, 사례, 조건을 제시해줘.`,
  find_exception: (ex) => `@모두 찬성측 주장 "${ex}"이 성립하지 않는 예외 조건이나 한계를 찾아줘.`,
  find_counterexample: (ex) => `@모두 반대측 주장 "${ex}"을 검증할 수 있는 반례나 실제 사례를 찾아줘.`,
  check_logic_gap: (ex) => `@모두 방금 주장 "${ex}"의 논리적 허점이나 비약을 찾아 구체적으로 지적해줘.`,
  add_evidence: (ex) => `@모두 방금 주장 "${ex}"을 뒷받침할 구체적 근거와 사례, 출처를 추가해줘.`,
  improve_persuasion: (ex) => `@모두 방금 최종 변론 "${ex}"의 설득력을 높일 수 있도록 논리 구조와 표현을 강화해줘.`,
  summarize_claim: (ex) => `@모두 방금 변론 "${ex}"의 핵심 주장을 한눈에 보이도록 요약해줘.`,
  judge: () => `@모두 지금까지의 찬성측과 반대측 주장을 기준으로 논리성, 근거성, 반박력, 설득력을 평가해서 심사위원 판정을 내려줘.`,
  explain_judgement: (ex) => `@모두 방금 판정 "${ex}"의 근거를 더 자세히 풀어줘. 어떤 쟁점에서 승패가 갈렸는지 설명해줘.`,
  alternative_judgement: (ex) => `@모두 방금 판정 "${ex}"과 반대로 판단할 수 있는 가능성을 검토해줘. 어떤 기준을 바꾸면 다른 판정이 가능한지 설명해줘.`,
  learning_summary: () => `@모두 이 토론을 학습 관점에서 정리해줘. 핵심 개념, 찬반 쟁점, 시험/실무에서 주의할 점으로 나눠줘.`,
};

const buildDebateActionPrompt = (node, actionType) => {
  const ctx = node?.actionContext || {};
  const ex = ctx.contentExcerpt || debateExcerpt(node?.content);
  const fn = DEBATE_ACTION_PROMPTS[actionType];
  const base = fn ? fn(ex) : `@모두 방금 "${ex}" 내용에 이어서 토론을 계속 진행해줘.`;
  // 현재 논제/쟁점 축을 프롬프트에 주입해 토론 맥락을 유지한다(@모두 바로 뒤에 삽입).
  const axes = Array.isArray(ctx.issueAxes) && ctx.issueAxes.length ? ctx.issueAxes.join(', ') : '';
  if (!ctx.topic) return base;
  const prefix = `현재 토론 논제는 "${ctx.topic}"${axes ? `이고, 쟁점 축은 ${axes}` : ''}입니다. `;
  return base.startsWith('@모두 ') ? base.replace('@모두 ', `@모두 ${prefix}`) : `${prefix}${base}`;
};

// ── 소크라테스 노드 액션 버튼 클릭 시 입력창에 채워질 프롬프트 ──────────────────────
const SOCRATIC_ACTION_PROMPTS = {
  easier_question: (ex) => `@모두 방금 소크라테스 질문 "${ex}"을 더 쉬운 질문으로 바꿔줘. 정답은 바로 말하지 말고 사용자가 답하게 유도해줘.`,
  harder_question: (ex) => `@모두 방금 질문 "${ex}"을 더 깊고 어려운 질문으로 바꿔줘. 정답은 바로 말하지 마.`,
  example_question: (ex) => `@모두 방금 개념 "${ex}"을 예시 상황으로 바꿔 질문해줘. 정답은 바로 말하지 마.`,
  request_hint: (ex) => `@모두 방금 질문 "${ex}"에 대해 정답을 바로 말하지 말고 단계별 힌트만 제공해줘.`,
  counterexample_question: (ex) => `@모두 방금 개념 "${ex}"에 대해 반례를 이용한 소크라테스 질문을 만들어줘. 정답은 바로 말하지 마.`,
  re_explain: (ex) => `@모두 방금 내용 "${ex}"을 내가 다시 설명해볼 수 있도록 유도 질문을 만들어줘.`,
  next_hint: (ex) => `@모두 방금 힌트 "${ex}"에 이어서 다음 단계 힌트만 하나 더 제공해줘. 정답 전체는 말하지 마.`,
  example_hint: (ex) => `@모두 방금 개념 "${ex}"을 이해할 수 있는 예시 힌트를 제공해줘. 정답 전체는 말하지 마.`,
  reveal_partial: (ex) => `@모두 방금 질문 "${ex}"에 대해 정답의 일부만 살짝 공개하고, 나머지는 내가 채우도록 질문으로 남겨줘.`,
  apply_code: (ex) => `@모두 방금 개념 "${ex}"을 아주 작은 코드 예제로 적용할 수 있도록 질문을 만들어줘. 정답 코드를 바로 주지 말고 빈칸이나 선택지를 활용해줘.`,
  apply_practical: (ex) => `@모두 방금 개념 "${ex}"을 실무 사례에 적용하는 질문을 만들어줘. 정답은 바로 말하지 마.`,
  to_exam: (ex) => `@모두 방금 개념 "${ex}"을 시험 문제(객관식/단답)로 바꿔줘. 정답은 마지막에 숨겨서 제공해줘.`,
  evaluate_answer: () => `@모두 내가 다음에 작성할 답변을 개념 정확성, 빠진 개념, 오개념 가능성 기준으로 평가해줘. 바로 정답을 주지 말고 부족한 부분을 질문으로 짚어줘.`,
  find_weakness: (ex) => `@모두 방금 내용 "${ex}"에서 내가 약한 개념이나 빠뜨린 부분을 찾아 질문으로 짚어줘.`,
  next_question: (ex) => `@모두 방금 내용 "${ex}"을 바탕으로 다음에 스스로 생각해볼 질문 1개를 만들어줘.`,
  make_study_plan: () => `@모두 지금까지의 소크라테스 문답을 바탕으로 내가 다음에 무엇을 어떤 순서로 공부하면 좋을지 학습 계획을 만들어줘.`,
  make_quiz: () => `@모두 지금까지의 소크라테스 문답을 바탕으로 퀴즈 3개를 만들어줘. 정답은 마지막에 숨겨서 제공해줘.`,
  make_review: () => `@모두 지금까지의 핵심 개념으로 복습용 질문 3개를 만들어줘. 정답은 바로 주지 말고 내가 답하게 해줘.`,
};

const buildSocraticActionPrompt = (node, actionType) => {
  const ctx = node?.actionContext || {};
  const ex = ctx.contentExcerpt || debateExcerpt(node?.content);
  const fn = SOCRATIC_ACTION_PROMPTS[actionType];
  return fn ? fn(ex) : `@모두 방금 "${ex}" 내용에 이어서 소크라테스 질문을 하나 더 던져줘. 정답은 바로 말하지 마.`;
};

const SIMULATION_ACTION_PROMPTS = {
  expand_background: () => '@모두 상황극 모드에서 현재 배경을 더 자세히 만들고, 조건과 등장인물을 보강해줘.',
  easier_scenario: () => '@모두 상황극 모드에서 같은 개념을 더 쉬운 상황으로 바꿔줘. 정답/오답 채점이 아니라 선택과 결과 중심으로 보여줘.',
  harder_scenario: () => '@모두 상황극 모드에서 같은 개념을 더 어려운 상황으로 확장해줘. 제약 조건과 돌발 변수를 추가해줘.',
  change_role: () => '@모두 상황극 모드에서 내 역할을 바꿔서 다시 진행해줘. 선택지와 결과 변화도 새 역할에 맞춰줘.',
  observer_view: () => '@모두 상황극 모드에서 나를 관찰자 시점으로 바꿔 같은 상황을 다시 보여줘.',
  decision_view: () => '@모두 상황극 모드에서 나를 의사결정자 시점으로 바꿔 선택과 결과를 이어가줘.',
  choose: (label) => `@모두 상황극 모드에서 "${label}" 선택을 진행해줘. 선택 결과, 개념 연결, 오개념 위험, 다음 분기를 보여줘.`,
  preview: (label) => `@모두 "${label}" 선택을 했을 때 예상 결과를 설명해줘. 정답/오답 채점이 아니라 상황 변화 중심으로 보여줘.`,
  risk: (label) => `@모두 "${label}" 선택에 숨어 있는 오개념이나 위험한 전제를 분석해줘.`,
  why_result: () => '@모두 상황극 모드에서 왜 이런 결과가 나왔는지 개념과 원리로 연결해줘.',
  compare_choices: () => '@모두 방금 선택과 다른 선택지를 비교해서 어떤 개념 차이가 있는지 설명해줘.',
  connect_concept: () => '@모두 상황극 모드에서 이 결과를 핵심 개념, 원리, 한계로 연결해줘.',
  summarize_concept: () => '@모두 상황극 모드에서 핵심 개념만 짧게 정리해줘. 퀴즈처럼 채점하지 마.',
  expand_case: () => '@모두 같은 개념을 다른 전공/현실 사례의 상황극으로 바꿔줘.',
  major_context: () => '@모두 이 상황극을 전공 맥락에서 다시 연결해줘.',
  dig_trap: () => '@모두 상황극 모드에서 이 오개념 함정을 더 깊게 파고들고 반례를 보여줘.',
  counterexample: () => '@모두 이 오개념을 깨는 반례 상황을 하나 만들어줘.',
  safe_rule: () => '@모두 같은 상황에서 안전하게 판단할 수 있는 기준을 만들어줘.',
  hint: () => '@모두 상황극 모드에서 성찰 질문에 대한 힌트만 줘. 정답 채점으로 만들지 마.',
  evaluate_reflection: () => '@모두 내가 다음에 쓸 답변을 상황 변화, 개념 연결, 오개념 위험 기준으로 평가해줘.',
  next_question: () => '@모두 이 상황극의 다음 질문을 만들어줘.',
  next_branch: () => '@모두 상황극 모드에서 다음 분기를 진행해줘. 선택지와 결과 변화를 포함해줘.',
  raise_difficulty: () => '@모두 상황극 모드에서 난이도를 한 단계 올려 다음 분기를 진행해줘.',
  change_domain: () => '@모두 같은 개념을 다른 분야의 상황극으로 바꿔 다음 분기를 만들어줘.',
};

const buildSimulationActionPrompt = (node, actionType) => {
  const label = node?.label || node?.choiceId || node?.actionContext?.choiceLabel || '이 선택';
  const map = {
    expand_background: SIMULATION_ACTION_PROMPTS.expand_background,
    easier_scenario: SIMULATION_ACTION_PROMPTS.easier_scenario,
    harder_scenario: SIMULATION_ACTION_PROMPTS.harder_scenario,
    change_role: SIMULATION_ACTION_PROMPTS.change_role,
    observer_view: SIMULATION_ACTION_PROMPTS.observer_view,
    decision_view: SIMULATION_ACTION_PROMPTS.decision_view,
    choose: () => SIMULATION_ACTION_PROMPTS.choose(label),
    preview: () => SIMULATION_ACTION_PROMPTS.preview(label),
    risk: () => SIMULATION_ACTION_PROMPTS.risk(label),
    why_result: SIMULATION_ACTION_PROMPTS.why_result,
    compare_choices: SIMULATION_ACTION_PROMPTS.compare_choices,
    connect_concept: SIMULATION_ACTION_PROMPTS.connect_concept,
    summarize_concept: SIMULATION_ACTION_PROMPTS.summarize_concept,
    expand_case: SIMULATION_ACTION_PROMPTS.expand_case,
    major_context: SIMULATION_ACTION_PROMPTS.major_context,
    dig_trap: SIMULATION_ACTION_PROMPTS.dig_trap,
    counterexample: SIMULATION_ACTION_PROMPTS.counterexample,
    safe_rule: SIMULATION_ACTION_PROMPTS.safe_rule,
    hint: SIMULATION_ACTION_PROMPTS.hint,
    evaluate_reflection: SIMULATION_ACTION_PROMPTS.evaluate_reflection,
    next_question: SIMULATION_ACTION_PROMPTS.next_question,
    next_branch: SIMULATION_ACTION_PROMPTS.next_branch,
    raise_difficulty: SIMULATION_ACTION_PROMPTS.raise_difficulty,
    change_domain: SIMULATION_ACTION_PROMPTS.change_domain,
  };
  return (map[actionType] || SIMULATION_ACTION_PROMPTS.next_branch)();
};

// (제거됨) ProcessStepsAccordion — 단계 펼침/접힘 UI는 더 이상 사용하지 않는다.
//  processSteps는 내부 저장/복원용 데이터로만 쓰고, 사용자 화면에는 결과 카드(1차/2차/3차·토론)만 표시한다.

// 로딩 문구는 생성 과정을 노출하지 않고 단일 메시지("답변 작성 중...")만 표시한다.
const StagedTypingLabel = () => <>답변 작성 중...</>;

const parsePersonaTag = (persona, tagName) => {
  const match = String(persona || '').match(new RegExp(`\\[${tagName}:\\s*([^\\]]+)\\]`));
  return match ? match[1].trim() : '';
};

// 기록 로드 시에도 라이브와 동일하게 1→2→3 단계 말풍선으로 펼쳐 보여준다(상세과정 클릭 불필요).
const hydrateHistoryProcessSteps = (history) => explodeHistoryToStageBubbles(history);

const getAgentId = (agent) => agent?.id ?? agent?.agentId;

// ── 방(room)별 채팅 히스토리 영속화 ─────────────────────────────────────────────
// key는 반드시 userId + roomId(=agent.id, 안정 DB id) 조합으로 분리한다.
//  - 전역 단일 messages 덮어쓰기 금지 / agent index 기반 저장 금지 / agentId 없는 key 금지.
// 새로고침 후에도 같은 방의 대화가 유지되도록 localStorage에 방 단위로 보관한다(서버가 정본).
const CHAT_PERSIST_PREFIX = 'sb_chat_v1';
const CHAT_PERSIST_CAP = 80; // 방당 보관 최대 메시지 수(quota 방어, 서버가 전체 정본 보유)
const chatStorageKey = (userId, roomId) => `${CHAT_PERSIST_PREFIX}:${userId ?? 'anon'}:${roomId}`;
const readPersistedHistory = (userId, roomId) => {
  if (!roomId) return null;
  try {
    const raw = localStorage.getItem(chatStorageKey(userId, roomId));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : null;
  } catch { return null; }
};
const writePersistedHistory = (userId, roomId, list) => {
  if (!roomId) return;
  try {
    const arr = Array.isArray(list) ? list : [];
    const tail = arr.length > CHAT_PERSIST_CAP ? arr.slice(arr.length - CHAT_PERSIST_CAP) : arr;
    localStorage.setItem(chatStorageKey(userId, roomId), JSON.stringify(tail));
  } catch { /* quota/직렬화 실패는 무시 — 서버 조회가 폴백 */ }
};
// 방 전환/새로고침 시 서버 이력과 로컬 캐시를 합친다.
//  - 서버가 로컬보다 같거나 많으면 서버를 정본으로 사용(중복 방지).
//  - 서버가 더 적으면(스트리밍분 미영속 등) 로컬 캐시를 유지해 "대화 사라짐"을 막는다.
const reconcileHistory = (server, local) => {
  const s = Array.isArray(server) ? server : [];
  const l = Array.isArray(local) ? local : [];
  return s.length >= l.length ? s : l;
};

// 그룹/카드/세션 제목은 유저가 생성 시 입력한 roomName을 그대로 사용한다.
// 내부 roomId/agentId/DB id는 건드리지 않고 표시명만 roomName으로 렌더. roomName이 없을 때만 기본 브랜드명.
const STUDYBRIDGE_ROOM_TITLE = '스터디 브릿지';
// 표시 우선순위: 사용자가 입력한 방 이름(roomName) → name → title → groupName → (없을 때만) 브랜드 폴백.
const getDisplayRoomTitle = (room) =>
  room?.roomName || room?.name || room?.title || room?.groupName || STUDYBRIDGE_ROOM_TITLE;

// ── 빈/내부진단 응답 방어 (문제2) ──────────────────────────────────────────────
// FastAPI가 content로 흘려보내는 내부 진단 문구("'qwen3:14b' 모델이 빈 응답을 반환했습니다" 등)나
// 빈/blank 응답을 일반 에이전트 답변처럼 노출하지 않는다. 사용자에겐 짧은 안내만, 콘솔엔 추적 메타.
const EMPTY_AGENT_TEXT_PATTERNS = [
  /빈\s*응답을\s*반환/, /모델이\s*빈\s*응답/, /응답이\s*비어/,
  /empty\s*response/i, /returned\s+an?\s+empty/i, /no\s+(valid\s+)?response\s+(was\s+)?generated/i,
  // 내부 인증/키/스택트레이스 등 시스템 오류 문구가 답변 본문으로 새어 나오지 않게 차단한다.
  /Authorization\s*헤더/i, /AI\s*서버\s*인증/i, /인증에?\s*실패/, /OPENAI_API_KEY/i, /TAVILY_API_KEY/i,
  /Traceback\s*\(most recent\s*call/i, /Internal\s*Server\s*Error/i,
  /Connection\s*refused/i, /\bECONNREFUSED\b/i,
];
const FAILED_AGENT_TEXT = '응답 생성에 실패했습니다. 다시 시도해 주세요.';
const isUnusableAgentText = (raw) => {
  const t = String(raw ?? '').trim();
  if (!t) return true;
  return EMPTY_AGENT_TEXT_PATTERNS.some((re) => re.test(t));
};
// {ok, text}: ok=false면 본문 대신 짧은 실패 안내를 쓰고 isError로 표시한다(추적 로그 동반).
const coerceAgentText = (raw, ctx) => {
  if (isUnusableAgentText(raw)) {
    // 개발/운영 콘솔 모두에 원인 추적 메타를 남긴다(원문은 미리보기만).
    console.warn('[StudyMate][empty-response]', { ...(ctx || {}), preview: String(raw ?? '').slice(0, 80) });
    return { ok: false, text: FAILED_AGENT_TEXT };
  }
  return { ok: true, text: String(raw) };
};

// ── AI 환각 검증 결과 정규화/표시 (문제5) ──────────────────────────────────────
// ai07이 추후 validation/hallucinationCheck/factualityScore/riskLevel/unsupportedClaims/evidenceNotes를
// 내려보내더라도 프론트가 깨지지 않게 안전 정규화한다. 값이 하나도 없으면 null(표시 안 함).
const extractValidation = (o) => {
  if (!o || typeof o !== 'object') return null;
  const v = (o.validation && typeof o.validation === 'object') ? o.validation
    : (o.hallucinationCheck && typeof o.hallucinationCheck === 'object') ? o.hallucinationCheck
      : (o.hallucination_check && typeof o.hallucination_check === 'object') ? o.hallucination_check
        : o;
  const score = v.factualityScore ?? v.factuality_score ?? v.factuality;
  const risk = v.riskLevel ?? v.risk_level ?? v.risk ?? v.hallucinationRisk ?? v.hallucination_risk;
  const unsupported = v.unsupportedClaims ?? v.unsupported_claims;
  const contra = v.contradictions ?? v.contradiction;
  const missing = v.missingEvidenceNotes ?? v.missing_evidence_notes;
  const notesRaw = v.evidenceNotes ?? v.evidence_notes ?? v.notes;
  const hintRaw = v.safeRevisionHint ?? v.safe_revision_hint;
  const numScore = (typeof score === 'number') ? score
    : (score != null && score !== '' && !Number.isNaN(Number(score))) ? Number(score) : null;
  const toList = (x) => Array.isArray(x) ? x.filter(Boolean).map(String)
    : (typeof x === 'string' && x.trim()) ? [x.trim()] : [];
  const claims = toList(unsupported);
  const contradictions = toList(contra);
  // 검토 메모 = evidenceNotes + missingEvidenceNotes를 사람이 읽기 쉬운 한 목록으로 합친다.
  const notes = [...toList(notesRaw), ...toList(missing)];
  const hint = (typeof hintRaw === 'string' && hintRaw.trim()) ? hintRaw.trim() : null;
  if (numScore == null && risk == null && claims.length === 0 && contradictions.length === 0 && notes.length === 0 && !hint) return null;
  return {
    factualityScore: numScore,
    riskLevel: risk != null ? String(risk).toLowerCase() : null,
    unsupportedClaims: claims,
    contradictions,
    evidenceNotes: notes,
    safeRevisionHint: hint,
  };
};

const VALIDATION_RISK_STYLE = {
  high: { bg: '#fef2f2', border: '#fecaca', color: '#b91c1c', label: '높음' },
  medium: { bg: '#fffbeb', border: '#fde68a', color: '#b45309', label: '중간' },
  low: { bg: '#f0fdf4', border: '#bbf7d0', color: '#15803d', label: '낮음' },
};
// 검증 결과를 사람이 읽을 수 있는 카드로 렌더(원시 JSON 비노출). high 위험은 본문과 분리된 경고 배지로 강조.
const ValidationResult = ({ data }) => {
  if (!data) return null;
  const risk = (data.riskLevel && VALIDATION_RISK_STYLE[data.riskLevel]) ? data.riskLevel : null;
  const rs = risk ? VALIDATION_RISK_STYLE[risk] : null;
  const scorePct = (typeof data.factualityScore === 'number')
    ? Math.round(data.factualityScore <= 1 ? data.factualityScore * 100 : data.factualityScore) : null;
  return (
    <div style={{ marginTop: '8px', border: '1px solid #e5e7eb', borderRadius: '10px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', background: '#f8fafc', borderBottom: '1px solid #eef2f7' }}>
        <ShieldCheck size={14} color="#475569" />
        <span style={{ fontSize: '11.5px', fontWeight: 800, color: '#334155' }}>검증 결과</span>
        {risk === 'high' && (
          <span style={{ marginLeft: 'auto', fontSize: '10px', fontWeight: 800, padding: '2px 8px', borderRadius: '999px', background: rs.bg, border: `1px solid ${rs.border}`, color: rs.color }}>
            ⚠ 환각 위험 {rs.label}
          </span>
        )}
      </div>
      <div style={{ padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {(scorePct != null || (rs && risk !== 'high')) && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {scorePct != null && (
              <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '6px', background: '#eef2ff', color: '#4338ca' }}>
                사실성 {scorePct}%
              </span>
            )}
            {rs && risk !== 'high' && (
              <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '6px', background: rs.bg, color: rs.color }}>
                위험도 {rs.label}
              </span>
            )}
          </div>
        )}
        {data.unsupportedClaims.length > 0 && (
          <div>
            <div style={{ fontSize: '10.5px', fontWeight: 700, color: '#9ca3af', marginBottom: '2px' }}>근거가 부족한 주장</div>
            <ul style={{ margin: 0, paddingLeft: '16px' }}>
              {data.unsupportedClaims.slice(0, 5).map((c, i) => (
                <li key={i} style={{ fontSize: '11.5px', color: '#475569', lineHeight: 1.5 }}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {Array.isArray(data.contradictions) && data.contradictions.length > 0 && (
          <div>
            <div style={{ fontSize: '10.5px', fontWeight: 700, color: '#9ca3af', marginBottom: '2px' }}>모순/충돌</div>
            <ul style={{ margin: 0, paddingLeft: '16px' }}>
              {data.contradictions.slice(0, 5).map((c, i) => (
                <li key={i} style={{ fontSize: '11.5px', color: '#475569', lineHeight: 1.5 }}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {data.evidenceNotes.length > 0 && (
          <div>
            <div style={{ fontSize: '10.5px', fontWeight: 700, color: '#9ca3af', marginBottom: '2px' }}>검토 메모</div>
            <ul style={{ margin: 0, paddingLeft: '16px' }}>
              {data.evidenceNotes.slice(0, 5).map((c, i) => (
                <li key={i} style={{ fontSize: '11.5px', color: '#475569', lineHeight: 1.5 }}>{c}</li>
              ))}
            </ul>
          </div>
        )}
        {data.safeRevisionHint && (
          <div style={{ fontSize: '11.5px', color: '#475569', lineHeight: 1.5 }}>
            <span style={{ fontWeight: 700, color: '#9ca3af' }}>보완 제안 </span>{data.safeRevisionHint}
          </div>
        )}
      </div>
    </div>
  );
};

// 항상 표준 enum(INTRO|BACHELOR|MASTER|DOCTOR|EXPERT)으로 반환. 표시에는 knowledgeLevelLabel()을 쓴다.
const getAgentKnowledgeLevel = (agent) => {
  return normalizeKnowledgeLevel(
    agent?.knowledgeLevel
    || agent?.knowledge_level
    || parsePersonaTag(agent?.persona, '지식수준')
  );
};

const getAgentPersonality = (agent) => {
  return agent?.personality
    || agent?.style
    || agent?.tone
    || parsePersonaTag(agent?.persona, '성격')
    || '전문적';
};

const getAgentStyleTheme = (personality) => {
  const normalized = String(personality || '').trim();
  switch (normalized) {
    case '전문적':
      return {
        bg: 'rgba(219, 234, 254, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🎓',
        tagBg: '#DBEAFE',
        accent: '#2563EB'
      };
    case '친근함':
      return {
        bg: 'rgba(254, 215, 170, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '✨',
        tagBg: '#FFEDD5',
        accent: '#EA580C'
      };
    case '솔직함':
      return {
        bg: 'rgba(209, 250, 229, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🎤',
        tagBg: '#D1FAE5',
        accent: '#059669'
      };
    case '독특함':
      return {
        bg: 'rgba(237, 233, 254, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '👽',
        tagBg: '#EDE9FE',
        accent: '#7C3AED'
      };
    case '효율적':
      return {
        bg: 'rgba(243, 244, 246, 0.65)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '⏱️',
        tagBg: '#F3F4F6',
        accent: '#374151'
      };
    case '냉소적':
      return {
        bg: 'rgba(254, 228, 230, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '😈',
        tagBg: '#FFE4E6',
        accent: '#E11D48'
      };
    default:
      return {
        bg: 'rgba(243, 244, 246, 0.5)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🤖',
        tagBg: '#E5E7EB',
        accent: '#4B5563'
      };
  }
};

const buildCanonicalAgentPayload = (agent) => {
  // 저장된 레거시 라벨(친근하게/냉철하게 등)도 정규 7종 라벨로 통일한다.
  const personalityKey = normalizePersonalityKey(agent.personality);
  const personality = canonicalPersonalityLabel(personalityKey);
  const temperature = personalityTemperature(personalityKey);
  const knowledgeLevel = normalizeKnowledgeLevel(agent.knowledgeLevel); // enum value (INTRO/BACHELOR/...)
  const customInstruction = String(agent.customInstruction || '').trim();
  const goal = String(agent.goal || '사용자의 학습을 돕는다').trim();
  const personaBody = customInstruction || goal;
  const agentPreset = String(agent.agentPreset || '').trim();
  // agentPreset은 Agent 엔티티 컬럼이 없어 persona [프리셋: X] 태그로 인코딩(마이그레이션 없이 영속/복원).
  const presetTag = agentPreset ? `[프리셋: ${agentPreset}] ` : '';

  return {
    name: String(agent.name || '').trim(),
    role: String(agent.role || '').trim() || deriveRole(personality),
    agentPreset,
    personality,
    // canonical key + temperature를 함께 전달(FastAPI/Spring이 key를 우선 사용).
    personalityStyle: personalityKey,
    temperature,
    personalityStrength: agent.personalityStrength || 'extreme',
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    knowledgeLevelLabel: knowledgeLevelLabel(knowledgeLevel),
    goal,
    customInstruction,
    custom_instruction: customInstruction,
    persona: `${presetTag}[지식수준: ${knowledgeLevel}] [성격: ${personality}] ${personaBody}`,
  };
};

// ─────────────────────────────────────────────────────────────────────────────
// 교수님들과 대화 — 안전한 상호작용(hotspot → 액션 → 대상) 설정.
//   · 기존 채팅/SSE/후속질문 payload schema는 건드리지 않는다(promptText에만 반영).
//   · 단순 React state + CSS animation으로 "교수들이 서로 반응하는" 느낌만 준다.
// ─────────────────────────────────────────────────────────────────────────────

// actionMode → 교수 3인 말풍선 문구.
const PROFESSOR_BUBBLES = {
  default: ['궁금한 내용을 질문하면 함께 도와드려요!', '핵심 개념을 정리해볼게요.', '필요하면 반박·비교·예시로 확장할 수 있어요.'],
  detail: ['먼저 원리를 더 깊게 풀어보겠습니다.', '중요 개념을 단계별로 정리할게요.', '놓치기 쉬운 예외 조건도 보겠습니다.'],
  rebuttal: ['그 설명에는 논리적 빈틈이 있습니다.', '반례와 한계를 기준으로 다시 보겠습니다.', '왜 부족한지 쉽게 짚어볼게요.'],
  compare: ['비슷한 개념과 차이를 비교하겠습니다.', '장단점을 기준으로 나눠보겠습니다.', '실제 사용 상황까지 연결해볼게요.'],
  example: ['쉬운 예시부터 들어보겠습니다.', '실무에서 어떻게 쓰이는지 보겠습니다.', '필요하면 코드나 구조 예시로 확장할게요.'],
  why: ['왜 그렇게 되는지 질문으로 파고들겠습니다.', '전제부터 차근차근 확인해볼게요.', '스스로 답을 찾을 수 있게 유도하겠습니다.'],
  assumption: ['답변 안에 숨은 전제를 확인하겠습니다.', '논리가 기대고 있는 조건을 분리해볼게요.', '이 전제가 깨지면 결론도 달라질 수 있습니다.'],
  counterQuestion: ['반대로 질문을 던져보겠습니다.', '이 관점에서 다시 생각해보면 어떨까요?', '스스로 검증할 수 있는 질문을 만들겠습니다.'],
  defense: ['반박에 대한 방어 논리를 세워보겠습니다.', '기존 설명이 유효한 조건을 정리하겠습니다.', '어디까지는 맞고 어디부터 약한지 나누겠습니다.'],
  judge: ['양쪽 관점을 기준으로 판정하겠습니다.', '근거의 강도를 비교해볼게요.', '최종적으로 어떤 설명이 더 타당한지 정리합니다.'],
  roleplay: ['상황극 방식으로 장면을 열어보겠습니다.', '등장인물의 입장에서 반응해볼게요.', '맥락에 맞는 대사와 행동으로 설명하겠습니다.'],
  choice: ['선택지를 나눠서 보여드리겠습니다.', '각 선택의 결과를 비교해볼게요.', '다음 행동을 고르기 쉽게 정리하겠습니다.'],
  reaction: ['상황에 대한 반응을 보여드리겠습니다.', '교수별 관점으로 다르게 반응해볼게요.', '왜 그런 반응이 나오는지도 설명하겠습니다.'],
};

// actionMode → 트리 루트 제목.
const PROFESSOR_ROOT_TITLE_BY_ACTION = {
  default: '전체 의견', detail: '전체 상세 설명', rebuttal: '전체 반박', compare: '전체 비교',
  example: '전체 예시', why: '전체 소크라테스 질문', assumption: '전체 전제 검토',
  counterQuestion: '전체 역질문', defense: '전체 방어 논리', judge: '전체 판정',
  roleplay: '전체 상황극', choice: '전체 선택지', reaction: '전체 반응',
};

// 학습 모드별 1단계 액션 메뉴.
const PROFESSOR_ACTIONS_BY_MODE = {
  basic: [
    { key: 'detail', label: '더 자세히', icon: '↻', tone: 'detail' },
    { key: 'rebuttal', label: '반박', icon: '⚔️', tone: 'rebuttal' },
    { key: 'compare', label: '비교', icon: '⚖️', tone: 'compare' },
    { key: 'example', label: '예시', icon: '💡', tone: 'example' },
  ],
  socratic: [
    { key: 'why', label: '왜?', icon: '❓', tone: 'socratic' },
    { key: 'assumption', label: '전제 검토', icon: '🔎', tone: 'socratic' },
    { key: 'counterQuestion', label: '역질문', icon: '💬', tone: 'socratic' },
    { key: 'example', label: '예시', icon: '💡', tone: 'example' },
  ],
  debate: [
    { key: 'rebuttal', label: '반박', icon: '⚔️', tone: 'rebuttal' },
    { key: 'defense', label: '방어', icon: '🛡️', tone: 'defense' },
    { key: 'compare', label: '비교', icon: '⚖️', tone: 'compare' },
    { key: 'judge', label: '판정', icon: '🏛️', tone: 'judge' },
  ],
  simulation: [
    { key: 'roleplay', label: '상황극', icon: '🎭', tone: 'simulation' },
    { key: 'choice', label: '선택지', icon: '🧭', tone: 'simulation' },
    { key: 'reaction', label: '반응', icon: '💬', tone: 'simulation' },
    { key: 'example', label: '예시', icon: '💡', tone: 'example' },
  ],
};

// learningMode 값(영문/한글 혼재) → 4종 정규화.
const normalizeLearningMode = (mode) => {
  const value = String(mode || '').toLowerCase();
  if (value.includes('socratic') || value.includes('소크라테스')) return 'socratic';
  if (value.includes('debate') || value.includes('토론')) return 'debate';
  if (value.includes('simulation') || value.includes('상황극')) return 'simulation';
  return 'basic';
};

// 2단계 대상 선택 — 실제 에이전트 이름이 있으면 사용, 없으면 fallback.
const getProfessorTargets = (agents = []) => [
  { key: 'all', label: '모두' },
  { key: 'agent1', label: agents?.[0]?.name || '에이전트1' },
  { key: 'agent2', label: agents?.[1]?.name || '에이전트2' },
  { key: 'agent3', label: agents?.[2]?.name || '에이전트3' },
];

// hotspot key(agent1/2/3) → 대상 인덱스 매핑(targetKey와 동일 키 체계 재사용).
const PROFESSOR_HOTSPOT_POS = { agent1: 'left', agent2: 'center', agent3: 'right' };

// professor actionKey → 기존 후속질문 actionType(handleNodeAction 재사용용).
const PROFESSOR_ACTION_TO_NODE_ACTION = {
  detail: 'detail', rebuttal: 'criticize', compare: 'compare', example: 'support',
  why: 'detail', assumption: 'criticize', counterQuestion: 'detail',
  defense: 'support', judge: 'compare', roleplay: 'detail', choice: 'detail', reaction: 'detail',
};

// 후속질문 actionType → professor actionMode(채팅 하단 버튼 통합용).
const NODE_ACTION_TO_PROFESSOR_ACTION = {
  detail: 'detail', criticize: 'rebuttal', compare: 'compare', support: 'example',
};

// actionKey + targetKey → 후속질문 promptText. API schema는 바꾸지 않고 문구에만 반영한다.
const buildProfessorActionPrompt = ({ actionKey, targetKey, baseText }) => {
  const actionLabelMap = {
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
  const targetLabelMap = {
    all: '모든 에이전트가 각자 관점으로 답변해 주세요.',
    agent1: '1번 에이전트 관점 중심으로 답변해 주세요.',
    agent2: '2번 에이전트 관점 중심으로 답변해 주세요.',
    agent3: '3번 에이전트 관점 중심으로 답변해 주세요.',
  };
  const excerpt = baseText
    ? (baseText.length > 60 ? baseText.substring(0, 60).replace(/\n/g, ' ') + '...' : baseText.replace(/\n/g, ' '))
    : '';
  return `@모두 ${actionLabelMap[actionKey] || actionLabelMap.detail}
${targetLabelMap[targetKey] || targetLabelMap.all}${excerpt ? `

기준 내용:
${excerpt}` : ''}`;
};

export default function StudyMate() {
  const { userId, user } = useAuth();

  // 플랜별 방(AI 그룹) 생성 한도 — 백엔드 resolveRoomLimit과 동일 게이트(ADMIN/ROOT/PREMIUM=10, FREE=3).
  const roomLimit = ['ADMIN', 'ROOT', 'PREMIUM'].includes((user?.role || '').trim().toUpperCase()) ? 10 : 3;

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  // 마인드맵 뷰가 받는 메시지(토론은 구조화 노드로 확장). chatHistory가 바뀔 때만 재계산한다.
  const mindmapMessages = React.useMemo(() => buildMindmapMessages(chatHistory), [chatHistory]);
  // 중앙 상단 탭: 'chat'(채팅) | 'professor'(교수님들과 대화). 기존 마인드맵 트리 로직을
  // 그대로 재사용하되, 사용자 화면에는 "마인드맵"을 노출하지 않는다.
  const PROFESSOR_TAB_VALUE = 'professor';
  const [viewTab, setViewTab] = useState('chat'); // 'chat' | 'professor'
  const isProfessorTab = viewTab === PROFESSOR_TAB_VALUE;
  // 교수님들과 대화 트리 최상단 라벨(액션에 따라 전체 의견/전체 반박/전체 비교/전체 예시로 갱신)
  const [professorTreeTitle, setProfessorTreeTitle] = useState('전체 의견');
  // 현재 교수 액션 모드(말풍선 문구·강조색·루트 제목을 함께 좌우). 13종 + default.
  const [professorActionMode, setProfessorActionMode] = useState('default');
  // 마지막으로 선택한 액션/대상(트리 강조·필터 기준).
  const [professorSelectedAction, setProfessorSelectedAction] = useState('default');
  const [professorSelectedTarget, setProfessorSelectedTarget] = useState('all');
  // 교수 hotspot 클릭 시 뜨는 2단계 floating menu 상태.
  const [professorMenuState, setProfessorMenuState] = useState({
    open: false, step: 'action', professorKey: null, actionKey: null, anchor: null,
  });
  const [message, setMessage] = useState('');
  
  // 멘션(@) 관련 상태
  const [showMentionPopup, setShowMentionPopup] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [bookmarkedIds, setBookmarkedIds] = useState(new Set());
  const [toastMsg, setToastMsg] = useState('');
  
  // 패널 토글 상태
  const [isLeftOpen, setIsLeftOpen] = useState(true);
  const [isRightOpen, setIsRightOpen] = useState(true);

  // 더 자세히 요청 시, 다음 AI 응답을 어떤 노드의 자식로 연결할지 추적
  const pendingDetailParentId = React.useRef(null);
  
  // 개별 채팅방별 캐시 및 상태 관리
  const [roomHistories, setRoomHistories] = useState({}); // { [roomId]: messages[] }
  const [typingRooms, setTypingRooms] = useState({});     // { [roomId]: boolean }
  const [roomDrafts, setRoomDrafts] = useState({});       // { [roomId]: string }

  const [showModal, setShowModal] = useState(false);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  // 메시지 헤더 클릭 시 "이 답변: ○○ 모드"를 펼쳐 보일 대상 메시지 id (토글)

  const selectedAgentIdRef = useRef(null);
  useEffect(() => {
    selectedAgentIdRef.current = getAgentId(selectedAgent);
  }, [selectedAgent]);

  // 동시 전송/중복 요청 방어.
  //  - typingRooms(state)는 setState가 비동기라 Enter키 + 전송버튼 동시 입력을 못 막는다.
  //    → ref로 동기적으로 잠가 같은 방에 같은 질문이 두 번 전송되는 것을 차단한다(StrictMode 재호출 포함).
  //  - activeRequestRef: 방별 현재 활성 requestId. 방을 바꾼 뒤 늦게 도착하는 이전 스트림 이벤트는 무시한다.
  const sendingRoomsRef = useRef(new Set());
  const activeRequestRef = useRef({});
  // 같은 질문을 연속으로 보내면(=다시 생성) attempt를 올려 백엔드가 이전 답변을 재사용하지 않게 한다.
  const regenTrackRef = useRef({});

  // ── 탭 전환/스트림 종료 시 client-side reconciliation용 상태 미러 ─────────────────
  //  이벤트 리스너(visibilitychange)나 비동기 종료 콜백은 클로저로 stale state를 잡으므로
  //  최신 값을 ref로 미러링해 둔다(새로고침 의존 없이 서버 영속본과 화면을 맞추기 위함).
  const roomHistoriesRef = useRef({});
  useEffect(() => { roomHistoriesRef.current = roomHistories; }, [roomHistories]);
  const typingRoomsRef = useRef({});
  useEffect(() => { typingRoomsRef.current = typingRooms; }, [typingRooms]);
  // 방별 마지막 턴 시작/완료 시각(ms). 탭 복귀 시 '최근 진행 턴'만 보정 대상으로 삼는다.
  const lastTurnAtRef = useRef({});

  // 토론/상황극 멀티턴 상태(논제/시나리오/선택)를 방별로 보관해 다음 요청에 echo한다.
  //  ai07가 응답에 실어 주는 debateState/selectedTopic/simulationState/scenarioId/turnIndex를 캡처해
  //  두었다가 같은 방의 다음 메시지 payload에 그대로 다시 싣는다(매 턴 TOPIC_SELECTION/선택지 반복 방지).
  const convStateRef = useRef({});

  // 에이전트는 최소 1명, 최대 3명. createdAgents 배열 길이가 곧 현재 에이전트 수다(+/- 및 캐러셀 ›로 조절).
  const [createdAgents, setCreatedAgents] = useState(makeDefaultAgents());
  // 현재 선택된 추천 방 설정 카드 id(시각적 강조용 + 에이전트 재추가 시 원래 프리셋 agent 복원에 사용)
  const [selectedPresetId, setSelectedPresetId] = useState(null);
  // 모달 단계: 0=방 기본/모드/추천 방 설정, 1~3=AI 학습메이트 #1/#2/#3 설정 화면.
  // 오른쪽 큰 › / 왼쪽 큰 ‹ 로 화면 단계 전체를 옆으로 넘긴다.
  const [modalStep, setModalStep] = useState(0);
  // 추천 방 설정 가로 캐러셀 — 한 번에 카드 1개만 보여주고 < > 로 넘긴다(모드별 프리셋 5개).
  const [presetCarouselIndex, setPresetCarouselIndex] = useState(0);
  const [roomName, setRoomName] = useState('');
  // 학습 진행 모드: basic(기본 채팅) / socratic(소크라테스) / debate(토론) / simulation(상황극)
  const [learningMode, setLearningMode] = useState('basic');
  // 토론 모드 논제/구조 설정 (생성 모달 + 메시지 전송에 사용)
  const [debateConfig, setDebateConfig] = useState(DEFAULT_DEBATE_CONFIG);
  // 소크라테스 문답 설정 (생성 모달 + 메시지 전송에 사용)
  const [socraticConfig, setSocraticConfig] = useState(DEFAULT_SOCRATIC_CONFIG);
  // 상황극 설정 (생성 모달 + 메시지 전송에 사용)
  const [simulationConfig, setSimulationConfig] = useState(DEFAULT_SIMULATION_CONFIG);

  // ── 에이전트 인원/캐러셀 컨트롤 (1~3명) ──────────────────────────────────────
  // 현재 선택된 추천 방 설정 프리셋 객체(없으면 null).
  const currentRoomPreset = () =>
    (ROOM_PRESETS_BY_MODE[learningMode] || []).find((p) => p.id === selectedPresetId) || null;
  // 새로 추가할 에이전트: 프리셋이 선택돼 있으면 해당 위치의 프리셋 agent를 복원, 없으면 기본 에이전트.
  const makeNextAgent = (index) => {
    const presetAgent = currentRoomPreset()?.agents?.[index];
    return presetAgent ? mapPresetAgentToCreatedAgent(presetAgent) : createDefaultAgent(index);
  };
  // index 위치에 에이전트가 없고 3명 미만이면, 그 자리까지 새 에이전트를 채워 생성한다(› 자동 생성용).
  const ensureAgentExists = (index) => {
    setCreatedAgents((prev) => {
      const normalized = normalizeAgents(prev);
      if (normalized[index]) return normalized;
      if (normalized.length >= MAX_AGENT_COUNT) return normalized;
      const next = [...normalized];
      while (next.length <= index && next.length < MAX_AGENT_COUNT) {
        next.push(makeNextAgent(next.length));
      }
      return next;
    });
  };
  // 오른쪽 큰 › : 0단계 → AI 학습메이트 #1, #N → #N+1.
  // 다음 에이전트가 아직 없고 3명 미만이면 자동 생성한 뒤 이동한다(#3에서는 더 이동하지 않음).
  const goNextModalStep = () => {
    if (modalStep === 0) {
      ensureAgentExists(0); // #1은 항상 최소 1명이 있어 보장됨
      setModalStep(1);
      return;
    }
    if (modalStep >= MAX_AGENT_COUNT) return; // #3에서는 멈춤
    ensureAgentExists(modalStep); // 다음 에이전트(index = modalStep) 보장
    setModalStep(modalStep + 1);
  };
  // 왼쪽 큰 ‹ : 이전 단계로(0단계에서는 멈춤).
  const goPrevModalStep = () => setModalStep((prev) => Math.max(0, prev - 1));
  // 에이전트 단계의 작은 + : 마지막에 에이전트를 추가하고 그 단계로 이동(최대 3명).
  const addAgent = () => {
    const list = normalizeAgents(createdAgents);
    if (list.length >= MAX_AGENT_COUNT) return;
    const next = [...list, makeNextAgent(list.length)];
    setCreatedAgents(next);
    setModalStep(next.length); // 새 에이전트 단계로 이동(step = index + 1)
  };
  // 에이전트 단계의 작은 - : 마지막 에이전트를 제거(최소 1명 유지). 현재 단계가 범위를 벗어나면 보정한다.
  const removeAgent = () => {
    const list = normalizeAgents(createdAgents);
    if (list.length <= MIN_AGENT_COUNT) return;
    const next = list.slice(0, list.length - 1);
    setCreatedAgents(next);
    setModalStep((s) => Math.min(s, next.length));
  };

  // ── 추천 방 설정 가로 캐러셀 컨트롤 ──────────────────────────────────────────
  // 현재 모드의 추천 방 설정 목록(없으면 빈 배열).
  const currentRoomPresets = () => ROOM_PRESETS_BY_MODE[learningMode] || [];
  // 이전 추천 방 설정 카드로 이동(첫 카드면 유지).
  const goPrevPreset = () => setPresetCarouselIndex((p) => Math.max(0, p - 1));
  // 다음 추천 방 설정 카드로 이동(마지막 카드면 유지).
  const goNextPreset = () =>
    setPresetCarouselIndex((p) => Math.min(p + 1, Math.max(0, currentRoomPresets().length - 1)));

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (userId) {
      loadAgents();
    } else {
      setAgents([]);
      setSelectedAgent(null);
      setChatHistory([]);
      setRoomHistories({});
      setTypingRooms({});
      setRoomDrafts({});
    }
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, typingRooms]);

  // 방별 채팅 히스토리를 localStorage에 write-through 영속화(새로고침 후 같은 방 대화 유지).
  // key는 userId+roomId 조합으로 분리되어 방 간 충돌이 없다.
  useEffect(() => {
    if (!userId) return;
    for (const [rid, list] of Object.entries(roomHistories)) {
      if (Array.isArray(list) && list.length) writePersistedHistory(userId, rid, list);
    }
  }, [roomHistories, userId]);

  const loadAgents = async () => {
    try {
      const data = await agentService.getAgents(userId);
      setAgents(data || []);
    } catch (err) {
      console.error('에이전트 목록 조회 실패:', err);
    }
  };

  const handleOpenModal = () => {
    if (!userId) return;
    setCreatedAgents(makeDefaultAgents());
    setSelectedPresetId(null);
    setModalStep(0);
    setPresetCarouselIndex(0);
    setRoomName('');
    setLearningMode('basic');
    setDebateConfig(DEFAULT_DEBATE_CONFIG);
    setSocraticConfig(DEFAULT_SOCRATIC_CONFIG);
    setSimulationConfig(DEFAULT_SIMULATION_CONFIG);
    setShowModal(true);
  };

  // 추천 방 설정 카드 클릭 → 세부 설정 + 답변 톤/학습자 수준/추가 요청 + 에이전트 3명을 한 번에 반영.
  // 이미 사용자가 수정한 값이 있어도 프리셋 값으로 덮어쓴다(요구사항: 프리셋 우선 통일).
  const applyRoomPreset = (preset) => {
    setSelectedPresetId(preset.id);
    setLearningMode(preset.mode);
    setRoomName(preset.roomName);
    if (preset.mode === 'socratic') {
      setSocraticConfig((c) => ({ ...c, questionIntensity: preset.questionIntensity, hintPolicy: preset.hintPolicy }));
    } else if (preset.mode === 'debate') {
      setDebateConfig((c) => ({ ...c, topicMode: preset.topicMode, debateDepth: preset.debateDepth }));
    } else if (preset.mode === 'simulation') {
      setSimulationConfig((c) => ({ ...c, scenarioType: preset.scenarioType, difficulty: preset.difficulty }));
    }
    // 프리셋의 추천 에이전트(최대 3명)로 교체. 이후 사용자가 + / - 로 1~3명으로 조절할 수 있고,
    // 줄였다가 다시 늘리면 makeNextAgent가 해당 위치의 프리셋 agent를 복원한다.
    setCreatedAgents((preset.agents || []).slice(0, MAX_AGENT_COUNT).map(mapPresetAgentToCreatedAgent));
    // 추천 방 설정을 누른 직후에는 0단계를 유지한다. 사용자가 오른쪽 큰 › 로 #1부터 확인한다.
    setModalStep(0);
  };

  const handleCreateAgent = async (e) => {
    e.preventDefault();
    if (agents.length >= roomLimit) {
      alert(`생성된 학습방은 최대 ${roomLimit}개까지 가질 수 있습니다.`);
      return;
    }

    // 현재 사용자가 설정한 인원(1~3명)을 그대로 사용 — payload agents 길이 = 화면에 보이는 에이전트 수.
    const selectedAgents = normalizeAgents(createdAgents);

    for (const agent of selectedAgents) {
      if (agent.customInstruction && agent.customInstruction.trim().length < 5 && agent.customInstruction.trim().length > 0) {
        alert('에이전트 설명 또는 추가 요구사항은 공백이거나 최소 5자 이상이어야 합니다.');
        return;
      }
    }

    const payloadAgents = selectedAgents.map(agent => buildCanonicalAgentPayload(agent));
    // 표시명은 항상 '스터디 브릿지'로 고정되므로, 저장되는 기본 roomName도 동일하게 맞춘다.
    const finalRoomName = roomName.trim() || STUDYBRIDGE_ROOM_TITLE;

    const payload = {
      roomName: finalRoomName,
      agents: payloadAgents,
      learningMode,
      // 토론/소크라테스 모드일 때만 해당 설정을 함께 저장 요청한다.
      debateConfig: learningMode === 'debate' ? debateConfig : null,
      socraticConfig: learningMode === 'socratic' ? socraticConfig : null,
      simulationConfig: learningMode === 'simulation' ? simulationConfig : null,
    };

    try {
      console.debug('[StudyMate] create agent room payload', payload);
      await agentService.createAgent(userId, payload);
      setShowModal(false);
      setCreatedAgents(makeDefaultAgents());
      setSelectedPresetId(null);
      setModalStep(0);
      setRoomName('');
      setLearningMode('basic');
      setDebateConfig(DEFAULT_DEBATE_CONFIG);
      setSocraticConfig(DEFAULT_SOCRATIC_CONFIG);
      setSimulationConfig(DEFAULT_SIMULATION_CONFIG);
      await loadAgents();
    } catch (err) {
      console.error('에이전트 스터디방 생성 실패:', err);
      alert(err.message || '에이전트 스터디방 생성에 실패했습니다.');
    }
  };

  const handleDeleteAgent = async (e, agentId) => {
    e.stopPropagation();
    if (!window.confirm('정말 이 에이전트 스터디방을 삭제하시겠습니까? 모든 대화 내용이 완전히 삭제됩니다.')) return;

    try {
      await agentService.deleteAgent(userId, agentId);
      if (getAgentId(selectedAgent) === agentId) {
        setSelectedAgent(null);
        setChatHistory([]);
      }
      await loadAgents();
    } catch (err) {
      console.error('에이전트 삭제 실패:', err);
      alert('삭제에 실패했습니다.');
    }
  };

  const selectAgent = async (agent) => {
    const agentId = getAgentId(agent);
    setSelectedAgent(agent);
    // 방에 저장된 학습 진행 모드를 라디오 상태에 복원한다. 서버가 항상 basic/socratic/debate를
    // 내려주므로 그 값을 우선하고, (구버전 응답 등으로) 없으면 basic으로 둔다.
    if (agent?.learningMode) {
      setLearningMode(agent.learningMode);
    } else {
      setLearningMode('basic');
    }
    // [검증용] 서버 응답에 learningMode가 실제로 내려오는지 확인 (토론/소크라테스 방 복원 디버깅)
    console.debug('[StudyMate] selectAgent learningMode=', agent?.learningMode, 'room=', agent);

    // 1. 이전 방의 질문이 보이지 않도록 즉각적으로 해당 방의 캐시된 기록을 UI에 노출.
    //    메모리 캐시가 비어 있으면 localStorage 영속본으로 시드 → 새로고침 직후에도 즉시 복원.
    const memCached = roomHistories[agentId];
    const cachedHistory = (Array.isArray(memCached) && memCached.length)
      ? memCached
      : (readPersistedHistory(userId, agentId) || []);
    setChatHistory(cachedHistory);
    if ((!Array.isArray(memCached) || !memCached.length) && cachedHistory.length) {
      // 영속본을 메모리 캐시에도 올려 두어 방 재전환 시 재조회 없이 보존되게 한다.
      setRoomHistories(prev => ({ ...prev, [agentId]: cachedHistory }));
    }

    // 2. 해당 방의 드래프트가 존재하면 입력 폼에 로드
    setMessage(roomDrafts[agentId] || '');

    // 3. 최신 채팅 이력을 비동기 조회하여 동기화
    try {
      const rawHistory = await agentService.getChatHistory(userId, agentId);
      // DB에 저장된 processSteps(전체 map)를 그대로 사용해 아코디언을 복원 (슬라이스 없이 전원 표시)
      const history = hydrateHistoryProcessSteps(rawHistory);
      // 서버 이력과 로컬 캐시를 합친다. 서버가 더 적으면(미영속 스트리밍분) 캐시를 유지해 유실 방지.
      const reconciled = reconcileHistory(history, cachedHistory);
      // 캐시 갱신 + 영속화
      setRoomHistories(prev => ({ ...prev, [agentId]: reconciled }));
      writePersistedHistory(userId, agentId, reconciled);

      // 비동기 복귀 시점에도 여전히 이 방이 활성화되어 있을 때만 UI에 반영하여 다른 방 간섭 방지
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory(reconciled);
      }
    } catch (err) {
      console.error('채팅 이력 조회 실패:', err);
      if (selectedAgentIdRef.current === agentId) {
        // 에러가 발생해도 이전 캐시를 그대로 보여줍니다.
      }
    }
  };

  // ── 명시적 client-side reconciliation ──────────────────────────────────────────
  //  탭 복귀/스트림 종료 시 서버 영속본을 조회해 화면과 맞춘다. 새로고침에 의존하지 않는다.
  //  reconcileHistory는 '더 긴 쪽'을 채택하므로, 라이브로 먼저 그려진 partial(1차/2차/3차)을
  //  서버 미영속분으로 덮어써 유실시키지 않는다(서버가 더 완전하면 서버가, 라이브가 더 길면 라이브가 남는다).
  const reconcileRoomFromServer = async (agentId, reason = '') => {
    if (!agentId || !userId) return;
    try {
      const rawHistory = await agentService.getChatHistory(userId, agentId);
      const history = hydrateHistoryProcessSteps(rawHistory);
      const cached = roomHistoriesRef.current[agentId] || readPersistedHistory(userId, agentId) || [];
      const reconciled = reconcileHistory(history, cached);
      setRoomHistories((prev) => ({ ...prev, [agentId]: reconciled }));
      writePersistedHistory(userId, agentId, reconciled);
      if (selectedAgentIdRef.current === agentId) setChatHistory(reconciled);
      if (import.meta.env.DEV) {
        console.debug('[StudyMate] reconcileRoomFromServer', { agentId, reason, server: history.length, cached: cached.length, applied: reconciled.length });
      }
    } catch (err) {
      console.warn('[StudyMate] reconcileRoomFromServer 실패', { agentId, reason, err });
    }
  };

  // 탭 복귀(visibilitychange→visible) 보정.
  //  - hidden 진입 시에는 스트림(reader.read 루프)을 절대 끊지 않는다. 보정은 복귀 시에만 수행한다.
  //  - 백그라운드 탭이 렌더/연결을 제한해 1차/2차/3차가 멈춘 것처럼 보이면, 진행 중이던(또는 방금 끝난)
  //    방의 서버 저장본을 조회해 누락 stage를 채워 넣는다.
  useEffect(() => {
    const onVisibility = () => {
      if (document.visibilityState !== 'visible') return;
      const agentId = selectedAgentIdRef.current;
      if (!agentId) return;
      const streaming = !!typingRoomsRef.current[agentId];
      const recent = (Date.now() - (lastTurnAtRef.current[agentId] || 0)) < 120000;
      if (streaming || recent) {
        reconcileRoomFromServer(agentId, streaming ? 'visible-streaming' : 'visible-recent');
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  const sendMessage = async (e, directMessage = null) => {
    if (e) e.preventDefault();
    const agentId = getAgentId(selectedAgent);
    // 목표 F: 최소 정제만 수행(공백 정리). 사용자 내용(코드/명령/마크다운)은 보존한다.
    const inputMsg = sanitizeQuestion(directMessage || message);
    // 빈 입력/방 미선택은 조용히 무시(보존할 입력값 자체가 없음).
    if (!inputMsg || !selectedAgent) return;
    // ── BUG-03 메시지 유실 방지 ──
    // 스트리밍 중(typingRooms) 또는 진행 중 전송 lock(sendingRoomsRef)일 때는 새 전송을 막되,
    // 사용자 입력(draft)은 절대 비우지 않는다. 차단 사실을 안내 토스트로 알린다.
    //  - typingRooms: 스트리밍 상태(state). all_complete/error 시 finally에서 해제.
    //  - sendingRoomsRef: state 갱신 전에 들어오는 두 번째 호출(Enter+버튼 동시/더블클릭/StrictMode)을
    //    즉시 막는 동기 가드.
    if (typingRooms[agentId] || sendingRoomsRef.current.has(agentId)) {
      if (import.meta.env.DEV) console.debug('[StudyMate] 전송 차단(스트리밍/전송중) — draft 보존', { agentId });
      // 일반 입력은 message/roomDrafts에 그대로 남아 보존되지만, 빠른 액션(directMessage)으로
      // 들어온 텍스트는 입력창에 없을 수 있으므로 입력창/draft에 복원해 유실을 막는다.
      if (directMessage) {
        setMessage(directMessage);
        if (agentId) setRoomDrafts((prev) => ({ ...prev, [agentId]: directMessage }));
      }
      setToastMsg('현재 답변 생성 중입니다. 완료 후 전송해주세요.');
      setTimeout(() => setToastMsg(''), 2500);
      return;
    }
    sendingRoomsRef.current.add(agentId);

    // 이번 전송만의 고유 requestId. 방을 바꾼 뒤 늦게 도착하는 이전 요청 이벤트는 무시한다.
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeRequestRef.current[agentId] = requestId;
    // 탭 복귀 보정의 '최근 진행 턴' 판정 기준. 시작 시각을 기록(완료 시 갱신).
    lastTurnAtRef.current[agentId] = Date.now();
    // 성능 측정: client request start. 첫 이벤트/all_complete까지의 지연을 콘솔에서 분리 확인한다.
    const perfT0 = Date.now();
    let perfFirstEvent = 0;
    const isActiveRequest = () => activeRequestRef.current[agentId] === requestId;

    const userMsg = {
      id: `${requestId}`,
      content: inputMsg,
      sender: 'USER',
      createdAt: new Date().toISOString(),
      parentId: pendingDetailParentId.current || undefined
    };

    // 1. 현재 화면에 즉시 사용자 메시지 추가
    setChatHistory((prev) => [...prev, userMsg]);
    // 2. 해당 방의 캐시된 히스토리에도 사용자 메시지 추가
    setRoomHistories((prev) => ({
      ...prev,
      [agentId]: [...(prev[agentId] || []), userMsg]
    }));
    // 3. 입력 폼 비우기 및 드래프트 캐시 비우기
    setMessage('');
    setRoomDrafts((prev) => ({ ...prev, [agentId]: '' }));
    // 4. 해당 방의 타이핑/로딩 상태 활성화 (전체 방 블로킹 X)
    setTypingRooms((prev) => ({ ...prev, [agentId]: true }));

    // ── 소크라테스 카드 게이팅(정책: 명시 요청 시에만) ─────────────────────────────
    // 라디오로 '소크라테스'를 골랐다는 사실만으로는 카드를 만들지 않는다. 사용자가 이번 메시지에서
    // 명시적으로 단계별 문답/카드 학습을 요청했을 때만 소크라테스로 처리하고, 그 외에는 일반(basic)
    // 답변으로 내려 카드 폭발("SSH가 뭐야?"류)을 막는다. 토론/상황극 모드는 영향 없음.
    const baseLearningMode = learningMode || selectedAgent?.learningMode || 'basic';
    const explicitSocratic = isExplicitSocraticRequest(inputMsg);
    const activeLearningMode = explicitSocratic
      ? 'socratic'
      : (isSocraticModeValue(baseLearningMode) ? 'basic' : baseLearningMode);
    if (import.meta.env.DEV) console.debug('[StudyMate] socratic gate', { baseLearningMode, explicitSocratic, activeLearningMode });
    // 소크라테스 모드: 사용자가 방금 입력한 내용을 시도 답변(userAttempt)으로도 보내 오개념을 좁혀간다.
    // RAG 자료가 방에 연결돼 있으면 materialId도 함께 보낸다.
    const turnExtras = {};
    if (activeLearningMode === 'socratic') {
      turnExtras.userAttempt = inputMsg;
      // 소크라테스 문답 설정 전송. 방 저장값(selectedAgent.socraticConfig)이 있으면 우선, 없으면 현재 설정.
      turnExtras.socraticConfig = selectedAgent?.socraticConfig || socraticConfig;
    }
    // 토론 모드: 논제/구조 설정을 함께 전송한다(프론트 → Spring → FastAPI).
    if (activeLearningMode === 'debate') turnExtras.debateConfig = selectedAgent?.debateConfig || debateConfig;
    if (activeLearningMode === 'simulation') turnExtras.simulationConfig = selectedAgent?.simulationConfig || simulationConfig || DEFAULT_SIMULATION_CONFIG;
    const roomMaterialId = selectedAgent?.materialId ?? selectedAgent?.material_id;
    if (roomMaterialId) turnExtras.materialId = roomMaterialId;

    // ── 멀티턴 대화 상태 echo (토론 논제/상황극 선택 진행 유지) ──────────────────
    //  직전 응답에서 캡처한 상태(convStateRef)를 같은 방의 다음 요청 payload에 다시 싣는다.
    //  이게 빠지면 ai07가 매 턴 TOPIC_SELECTION/선택지 제시로 되돌아가 같은 논제·선택지를 반복한다.
    const savedConv = convStateRef.current[agentId] || {};
    if (activeLearningMode === 'debate') {
      if (savedConv.debateState != null) turnExtras.debateState = savedConv.debateState;
      if (savedConv.selectedTopic) turnExtras.selectedTopic = savedConv.selectedTopic;
      if (savedConv.debateSessionId) turnExtras.debateSessionId = savedConv.debateSessionId;
      if (typeof savedConv.turnIndex === 'number') turnExtras.turnIndex = savedConv.turnIndex;
    }
    if (activeLearningMode === 'simulation') {
      if (savedConv.simulationState != null) turnExtras.simulationState = savedConv.simulationState;
      if (savedConv.scenarioId) turnExtras.scenarioId = savedConv.scenarioId;
      if (typeof savedConv.turnIndex === 'number') turnExtras.turnIndex = savedConv.turnIndex;
      if (savedConv.selectedChoice) turnExtras.selectedChoice = savedConv.selectedChoice;
      if (Array.isArray(savedConv.previousChoices) && savedConv.previousChoices.length) {
        turnExtras.previousChoices = savedConv.previousChoices;
      }
    }
    // 상황극: 이번 턴에 소비한 선택은 다음 턴 previousChoices로 옮기고 selectedChoice는 비운다(턴 인덱스 +1).
    //  (turnExtras에는 이미 값으로 복사됐으므로 ref만 갱신해도 이번 요청에는 영향 없다.)
    if (activeLearningMode === 'simulation' && savedConv.selectedChoice) {
      const pc = Array.isArray(savedConv.previousChoices) ? savedConv.previousChoices.slice() : [];
      pc.push(savedConv.selectedChoice);
      convStateRef.current[agentId] = {
        ...savedConv,
        previousChoices: pc,
        selectedChoice: null,
        turnIndex: (typeof savedConv.turnIndex === 'number' ? savedConv.turnIndex : 0) + 1,
      };
    }
    // 응답(SSE 이벤트/all_complete/blocking)에서 멀티턴 상태 토큰을 캡처해 방별로 누적 저장한다.
    //  ai07가 보내는 키는 camelCase/snake_case 혼재 가능성이 있어 둘 다 받는다(가산적·방어적).
    const captureConvState = (d) => {
      if (!d || typeof d !== 'object') return;
      const prevState = convStateRef.current[agentId] || {};
      const next = { ...prevState };
      const setIf = (k, v) => { if (v !== undefined && v !== null && v !== '') next[k] = v; };
      setIf('debateState', d.debateState ?? d.debate_state);
      setIf('selectedTopic', d.selectedTopic ?? d.selected_topic);
      setIf('debateSessionId', d.debateSessionId ?? d.debate_session_id ?? d.sessionId);
      setIf('simulationState', d.simulationState ?? d.simulation_state);
      setIf('scenarioId', d.scenarioId ?? d.scenario_id);
      const ti = d.turnIndex ?? d.turn_index;
      if (typeof ti === 'number') next.turnIndex = ti;
      convStateRef.current[agentId] = next;
    };

    // ── 기본 질문 모드 단계 정책 ──────────────────────────────────────────────
    // 기본 모드에서도 1차 답변에 그치지 않고 2차 심화/3차 상호 피드백/환각 검증까지 받도록
    // stage 정책 플래그를 함께 전달한다(개별 단계 생성 여부는 FastAPI/ai07가 결정).
    if (activeLearningMode === 'basic') {
      turnExtras.stagePolicy = 'full';
      turnExtras.enableDeepening = true;
      turnExtras.enablePeerFeedback = true;
      turnExtras.enableHallucinationValidation = true;
    }

    // 다시 생성 처리: 직전과 같은 질문이면 attempt를 증가시키고 forceRegenerate로 cache 우회/변형을 유도한다.
    const regenTrack = regenTrackRef.current[agentId];
    const regenerateAttempt = (regenTrack && regenTrack.question === inputMsg)
      ? (regenTrack.attempt + 1)
      : 1;
    regenTrackRef.current[agentId] = { question: inputMsg, attempt: regenerateAttempt };
    turnExtras.messageId = requestId;
    turnExtras.regenerateAttempt = regenerateAttempt;
    turnExtras.forceRegenerate = regenerateAttempt > 1;

    // 이번 턴의 AI 메시지를 통째로 교체(누적 갱신)한다. 단계 도착마다 호출된다.
    //  - parentId(=userMsg.id) 기준으로 이 턴의 기존 AI 메시지를 제거 후 재삽입하므로,
    //    같은 이벤트가 여러 번 와도 append되지 않고 항상 1세트만 유지된다(upsert).
    //  - 더 새로운 요청이 시작됐으면(stale) 무시한다.
    const setTurnAiMessages = (rawAiMsgs) => {
      if (!isActiveRequest()) {
        if (import.meta.env.DEV) console.debug('[StudyMate] [DEDUPED] stale 요청 이벤트 무시', { agentId, requestId });
        return;
      }
      // 이 턴의 모든 AI 메시지에 사용된 모드를 메타데이터로 저장(이미 있으면 유지).
      const aiMsgs = (rawAiMsgs || []).map((m) =>
        m && m.mode == null && m.learningMode == null ? { ...m, mode: activeLearningMode } : m
      );
      const merge = (list) => {
        const kept = (list || []).filter((m) => !(m.sender === 'AI' && m.parentId === userMsg.id));
        return [...kept, ...aiMsgs];
      };
      if (import.meta.env.DEV) console.debug('[StudyMate] setTurnAiMessages', { requestId, count: aiMsgs.length });
      setRoomHistories((prev) => ({ ...prev, [agentId]: merge(prev[agentId]) }));
      if (selectedAgentIdRef.current === agentId) setChatHistory((prev) => merge(prev));
    };

    // 누적 processSteps(전체 map)로부터 단계별 말풍선(1차/2차/3차)을 만든다.
    // 단계가 도착할 때마다 1차→2차→3차 순으로 메인 대화에 누적 표시된다(상세과정 클릭 불필요).
    const buildStreamAiMsgs = (ps) => buildStageBubbles(ps, userMsg.id, new Date().toISOString(), { showInternal: isInternalVisibleMode(activeLearningMode) });

    try {
      // ── 단계/섹션별 SSE 선출력 우선 시도 (default/debate/socratic 모두 스트리밍, 실패 시 블로킹 폴백) ──
      const STREAMING_ENABLED = (import.meta.env.VITE_STUDYMATE_SSE ?? 'true') !== 'false';
      if (STREAMING_ENABLED) {
        const ts = new Date().toISOString();
        // 일반 단계 누적
        const fullPS = { initialAnswers: [], validatedAnswers: [], peerFeedback: [], personalityValidationSummary: [] };
        // Intent Router: terminal/파이프라인으로 종료되면 기존 답변 렌더를 스킵하기 위한 플래그
        let routedTerminal = false;
        // 토론 단계 누적 (stageType+side 기준 upsert, 도착 순서 유지) + 사용된 설정
        const debateStageMap = new Map();
        let debateConfigAcc = null;
        const debateStagesArr = () => Array.from(debateStageMap.values());
        // 소크라테스 단계 누적 (stageType+agentIndex 기준 upsert) + 사용된 설정
        const socraticStepMap = new Map();
        let socraticConfigAcc = null;
        const socraticStepsArr = () => Array.from(socraticStepMap.values());
        // 상황극 단계 누적 (requestId+stageType+agentIndex+contentHash 기준 dedupe/upsert) + 사용된 설정
        const simulationStageMap = new Map();
        let simulationConfigAcc = null;
        const simulationStagesArr = () => Array.from(simulationStageMap.values());
        const contentHash = (text) => {
          let h = 0;
          const str = String(text || '');
          for (let i = 0; i < str.length; i += 1) h = ((h << 5) - h + str.charCodeAt(i)) | 0;
          return String(h);
        };
        const agentAnswerMap = new Map();
        const agentMsgsArr = () => sortByAgentOrder(Array.from(agentAnswerMap.values()));
        const upsertAgentMessage = (d, patch = {}) => {
          // 목표 B.5: all_complete 이후 같은 turn의 추가 이벤트는 렌더링하지 않는다.
          if (streamCompleted) return;
          const idx = d?.agentIndex ?? patch.agentIndex ?? 0;
          const aid = d?.agentId ?? patch.agentId ?? idx;
          const hash = contentHash(d?.content ?? d?.answer ?? patch.content ?? '');
          const key = `${d?.requestId || requestId}::basic::${d?.stageType || 'FIRST_DRAFT'}::${idx}::${aid}::${hash}`;
          const stableKey = `${d?.requestId || requestId}::basic::${d?.stageType || 'FIRST_DRAFT'}::${idx}::${aid}`;
          const prevKey = Array.from(agentAnswerMap.keys()).find((k) => k.startsWith(stableKey));
          if (prevKey && prevKey !== key) agentAnswerMap.delete(prevKey);
          // 진행 중(isPending) 플레이스홀더는 방어 대상에서 제외하고, 실제 답변만 빈/진단 응답을 차단한다.
          const rawContent = d?.content ?? d?.answer ?? patch.content ?? '';
          const coerced = (patch.isPending || patch.isError)
            ? { ok: !patch.isError, text: rawContent }
            : coerceAgentText(rawContent, { requestId: d?.requestId || requestId, roomId: agentId, agentId: aid, agentIndex: idx, stageType: d?.stageType || 'FIRST_DRAFT' });
          agentAnswerMap.set(key, {
            id: key,
            content: coerced.text,
            sender: 'AI',
            senderName: d?.agentName || patch.agentName || selectedAgent?.name || 'AI',
            agentId: aid,
            agentIndex: idx,
            role: d?.role || patch.role,
            stageType: d?.stageType || 'FIRST_DRAFT',
            createdAt: d?.createdAt || patch.createdAt || ts,
            parentId: userMsg.id,
            isPending: !!patch.isPending,
            isError: !!patch.isError || !coerced.ok,
            statusText: patch.statusText || '',
            validation: extractValidation(d),
          });
          streamRendered = true;
          setTurnAiMessages(agentMsgsArr());
        };
        let streamRendered = false;
        let streamCompleted = false;

        // all_complete 라우팅: socratic → 답변 카드 / debate → DebateRenderer / processSteps → 단계 / answers → 카드 / 없음 → 안내
        const renderAllComplete = (d) => {
          const respMode = String((d && (d.mode || d.learningMode)) || '').toLowerCase();
          // 1) 상황극 — 구조화 simulationStages 우선, 없으면 누적 단계/answer fallback
          if (respMode === 'simulation' || isSimulationModeValue(activeLearningMode)) {
            const finalStages = (Array.isArray(d?.simulationStages) && d.simulationStages.length)
              ? d.simulationStages
              : (simulationStageMap.size ? simulationStagesArr() : (normalizeSimulationStages(d) || []));
            if (finalStages.length > 0) {
              setTurnAiMessages([buildSimulationTurnMessage(
                buildSimulationPayload({ ...d, simulationStages: finalStages, simulationConfig: d?.simulationConfig || simulationConfigAcc }) || { simulationStages: finalStages, simulationConfig: d?.simulationConfig || simulationConfigAcc },
                userMsg.id, ts,
              )]);
              return;
            }
          }
          // 2) 소크라테스 — 구조화 socraticSteps 우선, 없으면 누적 단계/answer fallback
          if (respMode === 'socratic' || isSocraticModeValue(activeLearningMode)) {
            const finalSteps = (Array.isArray(d?.socraticSteps) && d.socraticSteps.length)
              ? d.socraticSteps
              : (socraticStepMap.size ? socraticStepsArr() : (normalizeSocraticSteps(d) || []));
            if (finalSteps.length > 0) {
              setTurnAiMessages([buildSocraticTurnMessage(
                { socraticSteps: finalSteps, socraticConfig: d?.socraticConfig || socraticConfigAcc },
                userMsg.id, ts,
              )]);
              return;
            }
          }
          // 3) 토론 구조 — 구조화 debateStages 우선, 없으면 누적된 단계/레거시 변환 사용
          const finalStages = (Array.isArray(d?.debateStages) && d.debateStages.length)
            ? d.debateStages
            : (debateStageMap.size ? debateStagesArr() : (normalizeDebateStages(d) || []));
          if (finalStages.length > 0) {
            setTurnAiMessages([buildDebateTurnMessage(
              { debateStages: finalStages, debateConfig: d?.debateConfig || debateConfigAcc },
              userMsg.id, ts,
            )]);
            return;
          }
          // 4) 기본 agent_answer가 이미 표시됐으면 all_complete에서는 재append하지 않는다.
          if (agentAnswerMap.size > 0) {
            setTurnAiMessages(agentMsgsArr());
            return;
          }
          // 5) processSteps / stages → 1차/2차/3차 단계 말풍선
          const ps = (d && d.processSteps) || fullPS;
          const bubbles = buildStageBubbles(ps, userMsg.id, ts, { showInternal: isInternalVisibleMode(respMode || activeLearningMode) });
          if (bubbles.length) { setTurnAiMessages(bubbles); return; }
          // 6) 일반 answers/replies 카드
          const answers = (d && (d.answers || d.replies)) || [];
          if (Array.isArray(answers) && answers.length) {
            setTurnAiMessages(sortByAgentOrder(answers).map((a, i) => {
              const c = coerceAgentText(a.answer || a.content || '', { requestId: d?.requestId || requestId, roomId: agentId, agentId: a.agentId, stage: 'all_complete', idx: i });
              return {
                id: `${userMsg.id}::ans::${i}`,
                content: c.text,
                sender: 'AI',
                senderName: a.agentName || a.agent_name || selectedAgent?.name || 'AI',
                agentId: a.agentId,
                isError: !c.ok,
                validation: extractValidation(a),
                createdAt: ts,
                parentId: userMsg.id,
              };
            }));
            return;
          }
          // 7) 아무것도 없으면 안내 (답변을 버리지 않는다)
          if (!streamRendered) {
            setTurnAiMessages([{
              id: `${userMsg.id}::empty`, content: 'AI 응답을 받지 못했습니다. 잠시 후 다시 시도해주세요.',
              sender: 'AI', senderName: selectedAgent?.name || 'StudyMate', isError: true,
              createdAt: ts, parentId: userMsg.id,
            }]);
          }
        };

        // ── 무한 loading 방지 watchdog: 일정 시간 아무 이벤트도 없으면 abort 후 안내 ──
        // 이벤트가 올 때마다 rearm한다. (서버 ':hb' 주석은 이벤트로 디스패치되지 않으므로 진짜 hang만 잡힘)
        const streamAbort = new AbortController();
        let watchdogTimedOut = false;
        const WATCHDOG_MS = 330000; // 가장 긴 모드(토론/소크라테스 백엔드 타임아웃)보다 여유 있게
        let watchdogTimer = null;
        const armWatchdog = () => {
          if (watchdogTimer) clearTimeout(watchdogTimer);
          watchdogTimer = setTimeout(() => {
            watchdogTimedOut = true;
            try { streamAbort.abort(); } catch { /* noop */ }
          }, WATCHDOG_MS);
        };
        armWatchdog();

        try {
          await agentService.streamMessage(userId, agentId, {
            message: inputMsg,
            // 사용자가 고른 학습모드(라이브 토글)를 우선 전송한다(검증/협업/토론/소크라테스/상황극 분기).
            learningMode: activeLearningMode,
            // basic은 백엔드가 single/multi를 파생하도록 mode를 생략하고, 그 외는 mode=learningMode로 명시 전송한다.
            mode: activeLearningMode === 'basic' ? undefined : activeLearningMode,
            rounds: 1,
            ...turnExtras,
          }, {
            // 성능 측정: 첫 SSE 이벤트(heartbeat 제외) 도착 지연을 한 지점에서 기록한다.
            onAnyEvent: (event) => {
              if (!perfFirstEvent && event !== 'heartbeat') {
                perfFirstEvent = Date.now();
                if (import.meta.env.DEV) console.debug('[StudyMate][perf] first SSE event', { event, ttfbMs: perfFirstEvent - perfT0 });
              }
            },
            onTurnStart: () => { armWatchdog(); },
            onHeartbeat: (d) => {
              if (streamCompleted) return; // 목표 B.5
              if (!d || d.agentIndex == null) return;
              const stablePrefix = `${d.requestId || requestId}::basic::FIRST_DRAFT::${d.agentIndex}::`;
              const found = Array.from(agentAnswerMap.keys()).find((k) => k.startsWith(stablePrefix));
              if (found) {
                const prev = agentAnswerMap.get(found);
                agentAnswerMap.set(found, { ...prev, isPending: true, statusText: d.message || '답변 생성 중입니다.' });
                setTurnAiMessages(agentMsgsArr());
              }
            },
            onProgress: (d) => {
              if (d) console.debug('[StudyMate] stream progress', d);
            },
            onAgentStart: (d) => {
              if (!d) return;
              upsertAgentMessage(d, { isPending: true, content: d.message || `에이전트 ${d.agentIndex || ''} 답변 생성 중...` });
            },
            onAgentAnswer: (d) => {
              armWatchdog();
              if (!d) return;
              upsertAgentMessage(d, { isPending: false, content: d.content || d.answer || '' });
            },
            onAgentError: (d) => {
              if (!d) return;
              upsertAgentMessage(d, { isPending: false, isError: true, content: d.message || '이 에이전트의 응답 생성에 실패했습니다.' });
            },
            // default legacy 모드: 1차/2차/3차 단계 완료 시 즉시 반영. 저장 전에 에이전트 순서로 정렬한다.
            onStageComplete: (d) => {
              armWatchdog();
              if (streamCompleted) return; // all_complete 이후 무시(목표 B.5)
              if (!d) return;
              // 백엔드가 visible=false로 표시한 내부 단계(2차 검증/3차 피드백)는 누적은 하되,
              //  buildStreamAiMsgs(showInternal)에서 기본 채팅이면 렌더하지 않는다.
              if (d.stage === 1) fullPS.initialAnswers = sortByAgentOrder(d.answers || []);
              else if (d.stage === 2) fullPS.validatedAnswers = sortByAgentOrder(d.answers || []);
              else if (d.stage === 3) {
                fullPS.peerFeedback = sortByAgentOrder(d.feedbacks || []);
                fullPS.personalityValidationSummary = d.personalityValidationSummary || [];
              } else {
                // unknown stage fallback: 알 수 없는 stage 값이어도 UI가 죽지 않게 처리한다.
                // 답변이 실려 있으면 유실하지 않도록 1차(노출) 영역에 누적한다.
                console.warn('[StudyMate] unknown stage', { stage: d.stage, stageType: d.stageType, requestId: d.requestId || requestId, roomId: agentId });
                if (Array.isArray(d.answers) && d.answers.length) fullPS.initialAnswers = sortByAgentOrder(d.answers);
                else if (Array.isArray(d.feedbacks) && d.feedbacks.length) fullPS.peerFeedback = sortByAgentOrder(d.feedbacks);
              }
              streamRendered = true;
              setTurnAiMessages(buildStreamAiMsgs(fullPS));
            },
            // 토론 모드: 단계(debate_section) 도착 즉시 stageType+side로 upsert 후 갱신.
            onDebateSection: (d) => {
              if (streamCompleted) return; // 목표 B.5
              captureConvState(d);
              if (!d || !d.stageType) return;
              const key = `${d.stageType}::${d.side}`;
              debateStageMap.set(key, {
                stageType: d.stageType,
                stageTitle: d.stageTitle || d.stageType,
                side: d.side,
                role: d.role,
                agentIndex: d.agentIndex,
                agentId: d.agentId,
                agentName: d.agentName,
                content: d.content ?? '',
              });
              if (d.debateConfig) debateConfigAcc = d.debateConfig;
              streamRendered = true;
              setTurnAiMessages([buildDebateTurnMessage(
                { debateStages: debateStagesArr(), debateConfig: debateConfigAcc },
                userMsg.id, ts,
              )]);
            },
            // 소크라테스: 단계(socratic_step) 도착 즉시 stageType+agentIndex로 upsert 후 갱신.
            onSocraticStep: (d) => {
              if (streamCompleted) return; // 목표 B.5
              if (!d || !d.stageType) return;
              const key = `${d.stageType}::${d.agentIndex ?? 0}`;
              socraticStepMap.set(key, {
                stageType: d.stageType,
                stageTitle: d.stageTitle || d.stageType,
                role: d.role,
                agentIndex: d.agentIndex,
                agentName: d.agentName,
                question: d.question,
                hint: d.hint,
                feedback: d.feedback,
                expectedConcept: d.expectedConcept,
                misconceptionDetected: d.misconceptionDetected,
                misconception: d.misconception,
                directAnswerSuppressed: d.directAnswerSuppressed,
                content: d.content ?? d.question ?? d.hint ?? d.feedback ?? '',
              });
              if (d.socraticConfig) socraticConfigAcc = d.socraticConfig;
              streamRendered = true;
              setTurnAiMessages([buildSocraticTurnMessage(
                { socraticSteps: socraticStepsArr(), socraticConfig: socraticConfigAcc },
                userMsg.id, ts,
              )]);
            },
            // 상황극: 단계(simulation_stage) 도착 즉시 requestId+stageType+agentIndex+contentHash로 upsert 후 갱신.
            onSimulationStage: (d) => {
              if (streamCompleted) return; // 목표 B.5
              captureConvState(d);
              if (!d || !d.stageType) return;
              const key = `${requestId}::${d.stageType}::${d.agentIndex ?? 0}::${contentHash(d.content)}`;
              simulationStageMap.set(key, {
                stageType: d.stageType,
                stageTitle: d.stageTitle || SIMULATION_STAGE_META[d.stageType]?.title || d.stageType,
                role: d.role,
                agentIndex: d.agentIndex,
                agentName: d.agentName,
                content: d.content ?? '',
                userRole: d.userRole,
                choices: Array.isArray(d.choices) ? d.choices : [],
                selectedChoiceId: d.selectedChoiceId,
                consequence: d.consequence,
                conceptMapping: Array.isArray(d.conceptMapping) ? d.conceptMapping : [],
                misconceptionTrap: d.misconceptionTrap,
                reflectionQuestion: d.reflectionQuestion,
                nextScenarioPrompt: d.nextScenarioPrompt,
              });
              if (d.simulationConfig) simulationConfigAcc = d.simulationConfig;
              streamRendered = true;
              setTurnAiMessages([buildSimulationTurnMessage(
                { simulationStages: simulationStagesArr(), simulationConfig: simulationConfigAcc || DEFAULT_SIMULATION_CONFIG },
                userMsg.id, ts,
              )]);
            },
            // (하위 호환) 단일 socratic_answer 이벤트 — SUMMARY 단일 단계로 표시
            onSocraticAnswer: (d) => {
              if (streamCompleted) return; // 목표 B.5
              if (!d) return;
              const answer = d.answer ?? (Array.isArray(d.answers) && d.answers[0] && d.answers[0].answer) ?? '';
              streamRendered = true;
              setTurnAiMessages([buildSocraticTurnMessage({
                socraticSteps: [{ stageType: 'SUMMARY', stageTitle: '정리 및 다음 학습 방향', role: '정리자', agentIndex: 3, content: answer, directAnswerSuppressed: false }],
                socraticConfig: socraticConfigAcc,
              }, userMsg.id, ts)]);
            },
            // ── Intent Router 라우팅 이벤트 ──
            // terminal(DIRECT_REPLY/BLOCK/CLARIFY): 라우터 메시지 한 건만 표시하고 기존 답변 렌더는 스킵.
            onRouteMessage: (d) => {
              if (!d) return;
              routedTerminal = true;
              streamRendered = true;
              setTurnAiMessages([{
                id: `${userMsg.id}::route`,
                content: d.message || '',
                sender: 'AI',
                senderName: selectedAgent?.name || 'StudyMate',
                routeAction: d.routeAction || null,
                createdAt: new Date().toISOString(),
                parentId: userMsg.id,
              }]);
            },
            // QUIZ/SUMMARY/ROADMAP 파이프라인 결과: 안내 메시지 + 페이로드 표시.
            onRoutePipeline: (d) => {
              if (!d) return;
              routedTerminal = true;
              streamRendered = true;
              setTurnAiMessages([{
                id: `${userMsg.id}::route-pipeline`,
                content: d.message || '요청을 처리했습니다.',
                sender: 'AI',
                senderName: selectedAgent?.name || 'StudyMate',
                routeAction: d.routeAction || null,
                pipeline: d.pipeline || null,
                createdAt: new Date().toISOString(),
                parentId: userMsg.id,
              }]);
            },
            // WARN: 경고를 별도 버블(다른 parentId)로 올려 이후 학습 답변 렌더에 덮이지 않게 한다(중복 append 아님).
            onRouteNotice: (d) => {
              if (!d || !d.message) return;
              const notice = {
                id: `${userMsg.id}::warn-notice`,
                content: d.message,
                sender: 'AI',
                senderName: selectedAgent?.name || 'StudyMate',
                routeAction: 'WARN',
                isNotice: true,
                createdAt: new Date().toISOString(),
                parentId: `${userMsg.id}::warn`,
              };
              const addNotice = (list) => ((list || []).some((m) => m.id === notice.id) ? list : [...(list || []), notice]);
              setRoomHistories((prev) => ({ ...prev, [agentId]: addNotice(prev[agentId]) }));
              if (selectedAgentIdRef.current === agentId) setChatHistory((prev) => addNotice(prev));
            },
            onAllComplete: (d) => {
              if (watchdogTimer) clearTimeout(watchdogTimer);
              streamCompleted = true;
              captureConvState(d);
              lastTurnAtRef.current[agentId] = Date.now();
              if (import.meta.env.DEV) console.debug('[StudyMate][perf] all_complete', { totalMs: Date.now() - perfT0, ttfbMs: perfFirstEvent ? perfFirstEvent - perfT0 : null });
              if (routedTerminal) return; // 라우팅으로 종료 — 기존 답변 렌더 스킵(중복 방지)
              renderAllComplete(d);
            },
            // 목표 D: FastAPI의 error 이벤트가 와도 전체 대화를 무조건 실패로 덮지 않는다.
            //  1) agentId/agentIndex가 있으면 해당 교수만 error 상태로 표시(전체 실패 아님).
            //  2) 이미 일부 단계/답변이 렌더됐으면(streamRendered) 전체를 실패로 바꾸지 않는다(개발자 로그만).
            //  3) 아무것도 렌더되지 않았고 대상도 특정되지 않은 진짜 치명적 오류일 때만 폴백으로 던진다.
            //  → 사용자에게 내부 stacktrace는 노출하지 않고 code/reason은 콘솔에만 남긴다.
            onError: (d) => {
              if (streamCompleted) return; // all_complete 이후 늦게 온 error는 무시
              if (import.meta.env.DEV) {
                console.warn('[StudyMate] SSE error event', {
                  code: d?.code ?? d?.errorCode, reason: d?.reason ?? d?.message,
                  agentId: d?.agentId, agentIndex: d?.agentIndex,
                });
              }
              if (d && (d.agentId != null || d.agentIndex != null)) {
                upsertAgentMessage(d, {
                  isPending: false, isError: true,
                  content: d.message || '이 교수의 응답 생성에 실패했습니다.',
                });
                return;
              }
              if (streamRendered) return; // 일부 답변은 이미 표시됨 → 유지
              throw new Error('stream error event');
            },
          }, { signal: streamAbort.signal });
          if (watchdogTimer) clearTimeout(watchdogTimer);
          if (!streamCompleted && !streamRendered) {
            throw new Error('empty stream');
          }
          pendingDetailParentId.current = null;
          return; // 성공 — 바깥 finally에서 typing 해제
        } catch (streamErr) {
          if (watchdogTimer) clearTimeout(watchdogTimer);
          const streamErrMessage = String(streamErr?.message || streamErr || '');
          // watchdog 타임아웃으로 끊은 경우: 무한 loading 대신 안내 메시지로 종료한다.
          if (watchdogTimedOut && !streamRendered) {
            setTurnAiMessages([{
              id: `${userMsg.id}::timeout`,
              content: '응답 생성이 지연되었습니다. 잠시 후 다시 시도해 주세요.',
              sender: 'AI',
              senderName: selectedAgent?.name || 'StudyMate',
              isError: true,
              createdAt: new Date().toISOString(),
              parentId: userMsg.id,
            }]);
            pendingDetailParentId.current = null;
            return;
          }
          if (
            streamErr?.name === 'AbortError' ||
            streamErrMessage.includes('network error') ||
            streamErrMessage.includes('terminated') ||
            streamErrMessage.includes('incomplete') ||
            streamErrMessage.includes('outstanding read data') ||
            streamErrMessage.includes('Load failed') ||
            streamErrMessage.includes('Failed to fetch')
          ) {
            console.warn('[StudyMate] SSE 연결 종료 감지 - 서버 응답 수신 후 종료로 간주', streamErr);
            return;
          }

          console.warn('[StudyMate] SSE 스트리밍 실패', streamErr);
          if (streamRendered) {
            // 일부 단계가 이미 렌더됨 → 블로킹 재실행 시 중복되므로 폴백하지 않는다.
            pendingDetailParentId.current = null;
            return;
          }
          // 순차 UX 보장: SSE 실패 시 일반 REST sendMessage로 폴백하지 않는다.
          // REST 폴백은 최종 JSON을 한 번에 렌더링하여 Agent1→Agent2→Agent3 순차 표시 UX를 깨뜨린다.
          const noticeMsg = {
            id: `${userMsg.id}::stream-error`,
            content: 'AI 스트리밍 연결이 끊겼습니다. 순차 답변을 위해 다시 시도해주세요.',
            sender: 'AI',
            senderName: selectedAgent?.name || 'StudyMate',
            isError: true,
            createdAt: new Date().toISOString(),
            parentId: userMsg.id,
          };

          setTurnAiMessages([noticeMsg]);
          pendingDetailParentId.current = null;
          return;
        }
      }

      console.debug('[StudyMate] chat request', {
        userId,
        agentId,
        message: inputMsg,
        selectedAgent
      });
      const res = await agentService.sendMessage(userId, agentId, {
        message: inputMsg,
        // 사용자가 고른 학습모드(라이브 토글) 우선, 없으면 방 설정/기본 채팅
        learningMode: activeLearningMode,
        mode: activeLearningMode === 'basic' ? undefined : activeLearningMode,
        rounds: 1, // 프론트단에서 타임아웃 방지를 위해 강제로 1라운드(병렬 단답)만 요청
        ...turnExtras,
      });
      console.debug('[StudyMate] chat response', res);
      captureConvState(res);

      if (res.success === false || res.errorMessage) {
        // timeout 등 서버측 실패: alert로 흐름을 막지 않고 UI 내부 메시지로 부드럽게 안내한다.
        const isSoftTimeout = res.errorCode === 'AI_TIMEOUT';
        const noticeText = isSoftTimeout
          ? 'AI 답변 생성이 예상보다 오래 걸리고 있습니다. 소크라테스/토론 모드는 더 깊은 검토가 필요해 시간이 더 걸릴 수 있어요. 잠시 후 다시 시도하면 보통 정상 생성됩니다.'
          : (res.errorMessage || 'AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
        const noticeMsg = {
          id: Date.now() + 1,
          content: noticeText,
          sender: 'AI',
          senderName: selectedAgent?.name || 'StudyMate',
          isError: true,
          createdAt: new Date().toISOString(),
          parentId: userMsg.id,
        };
        setRoomHistories((prev) => {
          const currentList = prev[agentId] || [];
          const hasUserMsg = currentList.some((m) => m.id === userMsg.id);
          const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
          return { ...prev, [agentId]: [...baseList, noticeMsg] };
        });
        if (selectedAgentIdRef.current === agentId) {
          setChatHistory((prev) => {
            const hasUserMsg = prev.some((m) => m.id === userMsg.id);
            const baseList = hasUserMsg ? prev : [...prev, userMsg];
            return [...baseList, noticeMsg];
          });
        }
        pendingDetailParentId.current = null;
        return; // alert 없이 종료 (finally에서 typing 상태 해제)
      }

      let newMsgs = [];
      const resSimulationPayload = buildSimulationPayload(res);
      const resDebateStages = normalizeDebateStages(res);
      const resSocraticSteps = normalizeSocraticSteps(res);
      if (resSimulationPayload && resSimulationPayload.simulationStages.length > 0) {
        newMsgs = [buildSimulationTurnMessage(resSimulationPayload, userMsg.id, new Date().toISOString())];
      } else if (resDebateStages && resDebateStages.length > 0) {
        newMsgs = [{
          id: Date.now() + 1,
          content: '토론',
          sender: 'AI',
          senderName: '토론',
          createdAt: new Date().toISOString(),
          parentId: userMsg.id,
          debateStages: resDebateStages,
          debateConfig: res.debateConfig || debateConfigOf(res),
        }];
      } else if (resSocraticSteps && resSocraticSteps.length > 0) {
        newMsgs = [{
          id: Date.now() + 1,
          content: '소크라테스 문답',
          sender: 'AI',
          senderName: '소크라테스',
          createdAt: new Date().toISOString(),
          parentId: userMsg.id,
          isSocratic: true,
          socraticSteps: resSocraticSteps,
          socraticConfig: res.socraticConfig || socraticConfigOf(res),
        }];
      } else {
        const blockingStages = buildStageBubbles(res.processSteps, userMsg.id, new Date().toISOString(), { showInternal: isInternalVisibleMode(res.learningMode || res.mode || activeLearningMode) });
        if (blockingStages.length > 0) {
          newMsgs = blockingStages;
        } else if (res.replies && res.replies.length > 0) {
        newMsgs = res.replies.map((reply, index) => {
          const senderName = reply.agentName || reply.agent_name;
          return {
            id: Date.now() + 1 + index,
            content: reply.answer || reply.content,
            sender: 'AI',
            senderName,
            agentId: reply.agentId,
            createdAt: new Date().toISOString(),
            parentId: userMsg.id, // AI 응답은 방금 작성한 유저 질문의 자식이 됨
            processSteps: res.processSteps,
          };
        });
        } else {
          newMsgs = [{
            id: Date.now() + 1,
            content: res.answer,
            sender: 'AI',
            senderName: selectedAgent.name,
            createdAt: new Date().toISOString(),
            parentId: userMsg.id,
            processSteps: res.processSteps,
          }];
        }
      }
      // 태깅 초기화
      pendingDetailParentId.current = null;

      // 5. 해당 방의 캐시 갱신 (사용자가 다른 방에 있더라도 백그라운드 캐시에 완벽히 반영)
      setRoomHistories((prev) => {
        const currentList = prev[agentId] || [];
        const hasUserMsg = currentList.some(m => m.id === userMsg.id);
        const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
        return {
          ...prev,
          [agentId]: [...baseList, ...newMsgs]
        };
      });

      // 6. 현재 여전히 이 방을 보고 있는 경우에만 실시간 UI 업데이트 실행
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory((prev) => {
          const hasUserMsg = prev.some(m => m.id === userMsg.id);
          const baseList = hasUserMsg ? prev : [...prev, userMsg];
          return [...baseList, ...newMsgs];
        });
      }
    } catch (err) {
      console.error('메시지 전송 실패:', err);
      // alert로 흐름을 막지 않고, 네트워크/서버 오류를 채팅 내부 메시지로 표시한다.
      const isNetwork = err?.code === 'ERR_NETWORK' || /Network|timeout|aborted/i.test(err?.message || '');
      const noticeText = isNetwork
        ? '서버 연결이 불안정합니다. 잠시 후 다시 시도해주세요.'
        : (err.message || 'AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
      const noticeMsg = {
        id: Date.now() + 1,
        content: noticeText,
        sender: 'AI',
        senderName: selectedAgent?.name || 'StudyMate',
        isError: true,
        createdAt: new Date().toISOString(),
        parentId: userMsg.id,
      };
      setRoomHistories((prev) => {
        const currentList = prev[agentId] || [];
        const hasUserMsg = currentList.some((m) => m.id === userMsg.id);
        const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
        return { ...prev, [agentId]: [...baseList, noticeMsg] };
      });
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory((prev) => {
          const hasUserMsg = prev.some((m) => m.id === userMsg.id);
          const baseList = hasUserMsg ? prev : [...prev, userMsg];
          return [...baseList, noticeMsg];
        });
      }
    } finally {
      // 8. 해당 방의 타이핑/로딩 상태만 해제 + 전송 가드 해제(재진입 허용)
      setTypingRooms((prev) => ({ ...prev, [agentId]: false }));
      sendingRoomsRef.current.delete(agentId);
      lastTurnAtRef.current[agentId] = Date.now();
      // 9. 스트림 종료 후 명시적 보정 — 백엔드 비동기 영속화(persistStreamedAnswers) 커밋을 잠깐 기다린 뒤
      //    서버 저장본과 화면을 맞춘다. reconcileHistory가 '더 긴 쪽'을 채택하므로 라이브 답변을 깎지 않는다.
      //    (라우팅 종료/중복 전송 차단 등으로 활성 요청이 아니면 자연히 no-op)
      if (activeRequestRef.current[agentId] === requestId) {
        setTimeout(() => { reconcileRoomFromServer(agentId, 'post-stream'); }, 1500);
      }
    }
  };

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const formatTime = (isoString) => {
    if (!isoString) return '';
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const getAvatarColor = (index) => {
    const colors = [
      { bg: '#E8F5E9', text: '#2E7D32' },
      { bg: '#E3F2FD', text: '#1565C0' },
      { bg: '#FFF3E0', text: '#E65100' }
    ];
    return colors[index % colors.length];
  };

  // 로그아웃 상태일 때도 UI는 렌더링되도록 함

  const handleBookmark = (node) => {
    setBookmarkedIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(node.id)) {
        newSet.delete(node.id);
        setToastMsg('❌ 메모가 취소되었습니다.');
      } else {
        newSet.add(node.id);
        setToastMsg('📌 메모에 저장되었습니다.');
      }
      setTimeout(() => setToastMsg(''), 2500);
      return newSet;
    });
  };

  // 답변 후속 액션 핸들러 (더 자세히/반박/비교/예시).
  // 채팅 답변 카드와 (deprecated) 마인드맵 노드가 동일 로직을 재사용한다.
  // disc: 채팅 메시지 또는 노드 객체. UI 문구상으로는 "교수님들이 함께 반응"하는 흐름이다.
  const handleNodeAction = (disc, actionType = 'detail') => {
    pendingDetailParentId.current = disc.id;

    // ── 상황극 노드: stageType에 맞는 전용 액션 프롬프트를 준비한다 ──
    if (disc.nodeType === 'simulation') {
      const promptText = buildSimulationActionPrompt(disc, actionType);
      setMessage(promptText);
      setLearningMode('simulation');
      setShowMentionPopup(false);
      const activeId = getAgentId(selectedAgent);
      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
      const inputEl = document.querySelector('.chat-input-premium input');
      if (inputEl) inputEl.focus();
      setToastMsg('상황극 액션이 입력창에 준비되었습니다. 전송하면 이 노드에 이어서 진행됩니다.');
      setTimeout(() => setToastMsg(''), 2800);
      return;
    }

    // ── 소크라테스 노드: stageType에 맞는 전용 액션 프롬프트를 준비한다 ──
    if (disc.nodeType === 'socratic') {
      const promptText = buildSocraticActionPrompt(disc, actionType);
      setMessage(promptText);
      setLearningMode('socratic'); // 소크라테스 모드 유지
      setShowMentionPopup(false);
      const activeId = getAgentId(selectedAgent);
      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
      const inputEl = document.querySelector('.chat-input-premium input');
      if (inputEl) inputEl.focus();
      setToastMsg('🧭 소크라테스 액션이 입력창에 준비되었습니다. 전송하면 이 노드에 이어서 진행됩니다.');
      setTimeout(() => setToastMsg(''), 2800);
      return;
    }

    // ── 토론 노드: stageType/side에 맞는 전용 액션 프롬프트를 준비한다 ──
    const isDebateNode = disc.nodeType === 'debate' || !!disc.stageType;
    if (isDebateNode) {
      const promptText = buildDebateActionPrompt(disc, actionType);
      setMessage(promptText);
      // 토론 모드 유지(이어지는 응답도 토론 구조로 생성되게)
      setLearningMode('debate');
      setShowMentionPopup(false);
      const activeId = getAgentId(selectedAgent);
      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
      const inputEl = document.querySelector('.chat-input-premium input');
      if (inputEl) inputEl.focus();
      setToastMsg('🗣️ 토론 액션이 입력창에 준비되었습니다. 전송하면 이 노드에 이어서 진행됩니다.');
      setTimeout(() => setToastMsg(''), 2800);
      return;
    }

    // 사용자의 질문 노드에서 파생될 경우와 AI 노드에서 파생될 경우 문구 분리
    const isUserNode = disc.sender === 'USER';
    const senderName = disc.senderName || disc.sender_name || 'AI';

    // 내용을 25자 정도로 요약해서 프롬프트에 직접 포함하여 문맥 상실 방지
    const contentExcerpt = disc.content
        ? (disc.content.length > 25 ? disc.content.substring(0, 25).replace(/\n/g, ' ') + '...' : disc.content.replace(/\n/g, ' '))
        : '';

    let promptText = '';
    if (isUserNode) {
      promptText = `@모두 여기에 덧붙여서 하나 더 궁금한 게 있는데, `;
    } else {
      if (actionType === 'criticize') {
        promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 대해 각자의 관점에서 단점이나 문제점을 비판하고 반박해 줄래?`;
      } else if (actionType === 'compare') {
        promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용과 다른 개념을 대조하거나 각자의 의견과 어떻게 다른지 비교 분석해 줄래?`;
      } else if (actionType === 'support') {
        promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 전적으로 동의하며, 실무적인 추가 예시를 들어 보충 설명해 줄래?`;
      } else {
        promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 대해 각자의 특기나 관점에서 좀 더 자세히 설명해 줄래?`;
      }
    }

    // AI 답변에 대한 후속 액션(더 자세히/반박/비교/예시)은 자동으로 "교수님들과 대화" 탭으로
    // 전환하고, 트리 최상단 라벨을 액션에 맞게 갱신한다. 전송 시 mindmapMessages가 갱신되며
    // 결과가 이 트리에 이어진다. (사용자의 추가 질문 노드 'question'은 탭을 전환하지 않는다.)
    if (!isUserNode) {
      // 채팅 하단 빠른 액션도 동일한 professor action 시스템과 연결한다.
      // (말풍선 문구·트리 루트 제목·강조색이 함께 바뀐다. 대상은 기본값 all.)
      const profAction = NODE_ACTION_TO_PROFESSOR_ACTION[actionType] || 'detail';
      setProfessorActionMode(profAction);
      setProfessorSelectedAction(profAction);
      setProfessorSelectedTarget('all');
      setProfessorTreeTitle(PROFESSOR_ROOT_TITLE_BY_ACTION[profAction] || '전체 의견');
      setViewTab(PROFESSOR_TAB_VALUE);
    }

    setMessage(promptText);
    setShowMentionPopup(true);
    setMentionFilter(''); // 전체 목록 보여주기

    const activeId = getAgentId(selectedAgent);
    if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));

    const inputEl = document.querySelector('.chat-input-premium input');
    if (inputEl) inputEl.focus();

    setToastMsg('💡 교수님들과 대화 탭에서 이어집니다. 하단 입력창에서 전송해 주세요.');
    setTimeout(() => setToastMsg(''), 2500);
  };

  // ── 교수 hotspot 2단계 메뉴 (액션 선택 → 대상 선택) ─────────────────────────
  // 현재 학습 모드(normalizeLearningMode) 기준 액션 목록을 보여준다.
  const professorActions = PROFESSOR_ACTIONS_BY_MODE[normalizeLearningMode(learningMode)]
    || PROFESSOR_ACTIONS_BY_MODE.basic;
  const professorTargets = getProfessorTargets(selectedAgent?.agents || []);

  // 1단계: 교수 캐릭터 클릭 → 액션 메뉴 열기.
  const openProfessorActionMenu = (professorKey) => {
    setProfessorMenuState({
      open: true, step: 'action', professorKey, actionKey: null, anchor: professorKey,
    });
  };

  // 1단계 선택: 액션 클릭 → 대상 선택 단계로. (말풍선 문구는 즉시 미리보기)
  const selectProfessorAction = (actionKey) => {
    setProfessorMenuState((prev) => ({ ...prev, step: 'target', actionKey }));
    setProfessorActionMode(actionKey);
  };

  const closeProfessorMenu = () => {
    setProfessorMenuState({ open: false, step: 'action', professorKey: null, actionKey: null, anchor: null });
  };

  // 2단계 선택: 대상 클릭 → 교수님들과 대화 탭으로 전환 + 트리 갱신 + 후속질문 준비.
  //   기존 후속질문 로직(handleNodeAction)을 재사용해 promptText만 만들고 전송은 사용자에게 맡긴다.
  //   API payload schema/메시지 배열 구조는 변경하지 않는다.
  const handleProfessorActionTarget = ({ professorKey, actionKey, targetKey }) => {
    const action = actionKey || 'detail';
    setProfessorSelectedAction(action);
    setProfessorSelectedTarget(targetKey);
    setProfessorActionMode(action);
    setProfessorTreeTitle(PROFESSOR_ROOT_TITLE_BY_ACTION[action] || '전체 의견');
    setViewTab(PROFESSOR_TAB_VALUE);

    // 기준 내용: 가장 최근 AI 답변(없으면 빈 문자열).
    const lastAi = [...chatHistory].reverse().find((m) => m.sender !== 'USER' && m.content);
    const promptText = buildProfessorActionPrompt({
      actionKey: action,
      targetKey,
      baseText: lastAi?.content || '',
    });

    // 다음 응답이 트리에 이어지도록 부모 노드를 추적(기존 후속질문 흐름과 동일).
    if (lastAi?.id) pendingDetailParentId.current = lastAi.id;

    setMessage(promptText);
    setShowMentionPopup(false);
    const activeId = getAgentId(selectedAgent);
    if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
    const inputEl = document.querySelector('.chat-input-premium input');
    if (inputEl) inputEl.focus();

    setToastMsg('💡 교수님들과 대화 탭에서 이어집니다. 하단 입력창에서 전송해 주세요.');
    setTimeout(() => setToastMsg(''), 2500);
  };

  // floating menu 닫기: ESC / 바깥 클릭 / 탭 변경 / unmount cleanup.
  useEffect(() => {
    if (!professorMenuState.open) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') closeProfessorMenu(); };
    const onDown = (e) => {
      // 메뉴 내부 또는 hotspot 클릭은 무시(자체 핸들러가 처리).
      if (e.target.closest?.('.professor-floating-menu') || e.target.closest?.('.professor-hotspot')) return;
      closeProfessorMenu();
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('mousedown', onDown);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('mousedown', onDown);
    };
  }, [professorMenuState.open]);

  // 탭이 바뀌면 열린 메뉴를 닫는다.
  useEffect(() => { if (!isProfessorTab) closeProfessorMenu(); }, [isProfessorTab]);

  const handleScrollToNode = (id) => {
    const element = document.getElementById(`node-${id}`);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // 반짝이는 효과 주기
      element.style.transition = 'box-shadow 0.3s ease-in-out';
      element.style.boxShadow = '0 0 0 4px rgba(16, 185, 129, 0.4)';
      setTimeout(() => {
        element.style.boxShadow = '';
      }, 1500);
    }
  };

  return (
    <div className="container-workspace">
      {/* ── 토스트 알림 ── */}
      {toastMsg && (
        <div style={{
          position: 'fixed', bottom: 28, left: '50%', transform: 'translateX(-50%)',
          background: '#111827', color: '#fff', padding: '10px 20px', borderRadius: 12,
          fontSize: 13, fontWeight: 600, zIndex: 9999, whiteSpace: 'nowrap',
          boxShadow: '0 8px 24px rgba(0,0,0,0.2)', animation: 'fadeInUp 0.25s ease',
        }}>
          {toastMsg}
        </div>
      )}
      <div className="layout-3-panel">
        {/* ════ 1. 좌측: 트윈 컨트롤 패널 ════ */}
        {isLeftOpen && (
          <div className="pane-left animate-fade-in">
            <div className="dt-left-panel">

            {/* 헤더 */}
            <div className="dt-left-header">
              <div className="dt-left-title">
                <div className="dt-left-title-icon">
                  <Sparkles size={14} color="white" />
                </div>
                AI 학습메이트
              </div>
            </div>

            {/* 트윈 동기화 상태 배너 */}
            <div className="dt-sync-banner">
              <div className="dt-sync-dot" />
              <div>
                <span className="dt-sync-text">트윈 세션 활성화</span>
                <span style={{ marginLeft: 4 }}>·</span>
                <span style={{ marginLeft: 4 }}>{agents.length}개 그룹</span>
              </div>
            </div>

            {/* 에이전트 카드 스크롤 영역 */}
            <div className="dt-agent-scroll">
              {agents.length === 0 ? (
                <div className="dt-empty-state">
                  <div className="dt-empty-icon">
                    <Bot size={28} color="#60C95A" />
                  </div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#374151', marginBottom: 6 }}>에이전트가 없습니다</div>
                  <div style={{ fontSize: 12, color: '#9ca3af', lineHeight: 1.5 }}>학습 목적에 맞는<br/>
                    AI 에이전트를 만들어보세요.
                  </div>
                </div>
              ) : (
                agents.map((agent, index) => {
                  const agentId = getAgentId(agent);
                  const isActive = getAgentId(selectedAgent) === agentId;
                  const avatarColor = getAvatarColor(index);
                  const knowledgeLevel = knowledgeLevelLabel(getAgentKnowledgeLevel(agent));
                  const personality = getAgentPersonality(agent);
                  const isTyping = typingRooms[agentId];

                  return (
                    <div
                      key={agentId}
                      className={`dt-agent-card ${isActive ? 'active' : ''}`}
                      onClick={() => selectAgent(agent)}
                    >
                      <div className="dt-agent-card-row">
                        <div className="dt-avatar-wrap">
                          <div className="dt-avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }} title="StudyBridge AI">
                            <Bot size={18} />
                          </div>
                          <div className={`dt-status-dot ${isTyping ? 'busy' : isActive ? 'online' : 'idle'}`} />
                        </div>
                        <div className="dt-agent-info">
                          <div className="dt-agent-name">{getDisplayRoomTitle(agent)}</div>
                          <div className="dt-agent-tags">
                            {agent.agents && agent.agents.length > 0 ? (
                              agent.agents.map((ag, idx) => {
                                const tagColor = getAgentColor(agentColorKey(ag));
                                return (
                                  <span key={idx} className="dt-tag" style={{ color: tagColor.text, backgroundColor: tagColor.bg, borderColor: tagColor.border }}>#{ag.name}</span>
                                );
                              })
                            ) : (
                              <>
                                <span className="dt-tag">#{personality}</span>
                                <span className="dt-tag">#{knowledgeLevel}</span>
                              </>
                            )}
                          </div>
                          <div className="dt-agent-desc">
                            {String(agent.persona || agent.goal || '').substring(0, 38) || '학습 메이트'}
                          </div>
                        </div>
                        <button
                          className="dt-delete-btn"
                          onClick={(e) => handleDeleteAgent(e, agentId)}
                          aria-label="에이전트 삭제"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                      {isActive && <div className="dt-neural-bar" />}
                    </div>
                  );
                })
              )}
            </div>

            {/* 하단 고정 생성 버튼 */}
            <div className="dt-create-btn-wrap">
              <button
                className="dt-create-btn"
                onClick={handleOpenModal}
                disabled={agents.length >= roomLimit}
              >
                <Plus size={15} /> 새 AI 그룹 생성 ({agents.length}/{roomLimit})
              </button>
            </div>

          </div>
        </div>
        )}

        {/* 좌측 패널 토글 버튼 */}
        <button 
          onClick={() => setIsLeftOpen(!isLeftOpen)}
          style={{
            position: 'absolute', left: isLeftOpen ? '300px' : '0', top: '50%', transform: 'translateY(-50%)', zIndex: 50,
            background: 'white', border: '1px solid #e5e7eb', borderLeft: 'none', borderRadius: '0 12px 12px 0', padding: '10px 4px', cursor: 'pointer',
            boxShadow: '4px 0 12px rgba(0,0,0,0.05)', transition: 'left 0.3s ease', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          {isLeftOpen ? <ChevronLeft size={16} color="#9ca3af" /> : <ChevronRight size={16} color="#9ca3af" />}
        </button>

        {/* ════ 2. 중앙: 메인 학습 캔버스 ════ */}
        <div className="pane-center animate-fade-in">
          {!selectedAgent ? (
            <div className="empty-state" style={{ 
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', 
              height: '100%', background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)', position: 'relative' 
            }}>
              <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: '300px', height: '300px', background: 'radial-gradient(circle, rgba(96,201,90,0.05) 0%, transparent 70%)', borderRadius: '50%', animation: 'pulseDot 4s infinite alternate' }}></div>
              <div style={{ background: 'white', padding: '24px', borderRadius: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.04)', marginBottom: '24px', position: 'relative', zIndex: 1 }}>
                <Sparkles size={48} color="#60C95A" />
              </div>
              <h2 style={{ 
                margin: '0 0 12px 0', fontSize: '28px', fontWeight: '900', letterSpacing: '-0.5px',
                background: 'linear-gradient(135deg, #111827 0%, #374151 100%)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', position: 'relative', zIndex: 1 
              }}>스터디 브릿지</h2>
              <p style={{ margin: 0, color: '#6b7280', fontSize: '15px', fontWeight: '500', textAlign: 'center', lineHeight: '1.6', position: 'relative', zIndex: 1 }}>
                왼쪽 패널에서 에이전트를 선택하여 지식 동기화를 시작하거나<br/>
                새로운 AI 학습메이트를 생성하세요.
              </p>
            </div>
          ) : (
            <div className="chat-container">
              {/* ── 스터디 브릿지 세션 헤더 ── */}
              <div className="dt-session-header">
                {/* 상단: 아이덴티티 + 상세보기 (전체화면 시 숨김) */}
                { (isLeftOpen || isRightOpen) && (
                  <>
                    <div className="dt-session-top">
                      <div className="dt-session-identity">
                        <div className="dt-session-avatar" title="StudyBridge AI">
                          <Bot size={18} />
                        </div>
                        <div>
                          <div className="dt-session-title">
                            {getDisplayRoomTitle(selectedAgent)}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => setShowDetailsModal(true)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '5px',
                          fontSize: '11px', padding: '5px 10px', borderRadius: '8px',
                          background: 'rgba(96,201,90,0.08)', border: '1px solid rgba(96,201,90,0.2)',
                          color: '#16a34a', fontWeight: '700', cursor: 'pointer'
                        }}
                      >
                        에이전트 상세
                      </button>
                    </div>

                    {/* 에이전트 칩 */}
                    {selectedAgent.agents && selectedAgent.agents.length > 0 && (
                      <div className="dt-agent-chips">
                        {selectedAgent.agents.map((ag, idx) => {
                          const c = getAgentColor(agentColorKey(ag));
                          return (
                            <div key={ag.id || idx} className="dt-agent-chip">
                              <div className="dt-chip-dot" style={{ backgroundColor: c.border }} />
                              <span>{ag.name}</span>
                              <span style={{ color: '#9ca3af', fontSize: 10 }}>({ag.role})</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}

                {/* 상단 가로 탭바: 채팅 ↔ 교수님들과 대화 (기존 '마인드맵 크게 보기' 위치/폭 재사용) */}
                <div className="study-view-tabs">
                  <button
                    type="button"
                    className={`view-tab-btn ${viewTab === 'chat' ? 'active chat' : ''}`}
                    onClick={() => setViewTab('chat')}
                  >
                    <MessageCircle size={16} />
                    <span>채팅</span>
                  </button>
                  <button
                    type="button"
                    className={`view-tab-btn ${isProfessorTab ? 'active professor' : ''}`}
                    onClick={() => setViewTab(PROFESSOR_TAB_VALUE)}
                  >
                    <UsersRound size={16} />
                    <span>교수님들과 대화</span>
                  </button>
                </div>
              </div>

              {/* ── 채팅 뷰 ── */}
              {viewTab === 'chat' && (
                <div className="chat-history">
                  {chatHistory.length === 0 ? (
                    <div className="empty-state" style={{ marginTop: '40px' }}>
                      <MessageSquare size={36} color="#E5E7EB" style={{ marginBottom: 12 }} />
                      <p style={{ margin: 0, color: '#9ca3af', fontSize: 14 }}>질문을 입력해보세요.</p>
                    </div>
                  ) : (
                    chatHistory.map((msg, idx) => {
                      const isUser = msg.sender === 'USER';
                      const simulationPayload = !isUser ? buildSimulationPayload(msg) : null;
                      const simulationStages = simulationPayload?.simulationStages || null;
                      const hasSimulationPayload = simulationStages && simulationStages.length > 0;
                      const debateStages = (!isUser && !hasSimulationPayload) ? normalizeDebateStages(msg) : null;
                      const debatePayload = debateStages && debateStages.length > 0;
                      const socraticSteps = (!isUser && !hasSimulationPayload && !debatePayload) ? normalizeSocraticSteps(msg) : null;
                      const socraticPayload = socraticSteps && socraticSteps.length > 0;
                      const senderName = isUser ? '나' : (msg.senderName || msg.sender_name || selectedAgent.name);

                      let agentTheme = { bg: '#F3F4F6', icon: '🤖', tagBg: '#E5E7EB', accent: '#4B5563' };
                      let agentPersonality = '';
                      let agentRole = '';
                      let agentKnowledge = '';
                      let speakingAgent = null;

                      if (!isUser && selectedAgent && selectedAgent.agents) {
                        speakingAgent = selectedAgent.agents.find(
                          (ag) => ag.name === senderName || ag.name === msg.senderName || ag.name === msg.sender_name
                        ) || null;
                        if (speakingAgent) {
                          agentPersonality = getAgentPersonality(speakingAgent);
                          agentTheme = getAgentStyleTheme(agentPersonality);
                          agentRole = speakingAgent.role;
                          agentKnowledge = getAgentKnowledgeLevel(speakingAgent);
                        }
                      }

                      // 발화 에이전트 고유 색 (말풍선 보더/이름/아바타 공통). 매칭 실패 시 senderName으로 폴백.
                      const agentColor = getAgentColor(speakingAgent ? agentColorKey(speakingAgent) : senderName);
                      // 이 답변에 사용된 모드: 렌더되는 페이로드 종류에서 결정적으로 도출(+저장된 mode 폴백).
                      const msgMode = hasSimulationPayload ? 'simulation'
                        : debatePayload ? 'debate'
                        : socraticPayload ? 'socratic'
                        : (msg.mode || msg.learningMode || 'basic');

                      // 방어적 필터: 기본 채팅(평가/피드백 모드가 아닐 때)에서 내부 evaluator 문구가
                      //  섞여 들어오면 사용자에게 노출하지 않는다. (라우팅/경고 버블은 예외)
                      const isStructured = hasSimulationPayload || debatePayload || socraticPayload;
                      if (!isUser && !isStructured && !msg.routeAction && !msg.isNotice
                          && !isInternalVisibleMode(msgMode) && looksInternalLeak(msg.content)) {
                        return null;
                      }
                      // 라우팅/인사/욕설 등 direct reply는 마크다운 제거 평문, 그 외 AI 답변은 RichText 렌더.
                      const isPlainReply = !!msg.routeAction || !!msg.isNotice;

                      return (
                        <div key={msg.id ?? `${msg.parentId}-${msg.badgeKey}-${idx}`} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                          {/* 메시지 헤더: 에이전트 이름(+아이콘)만 노출. 모드/단계/모델/역할/성격/수준/글자수 배지는
                              발표 화면 단순화를 위해 렌더링하지 않는다(내부 데이터는 유지). */}
                          <div
                            className="chat-bubble-sender"
                            style={{ display: 'flex', alignItems: 'center', gap: '6px', color: isUser ? undefined : agentColor.text }}
                          >
                            {!isUser && (
                              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', backgroundColor: agentColor.bg, color: agentColor.text, fontSize: '11px' }}>
                                {agentTheme.icon}
                              </span>
                            )}
                            <span style={{ fontWeight: '700' }}>{senderName}</span>
                          </div>
                          {hasSimulationPayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', borderLeft: `4px solid ${agentColor.border}`, maxWidth: '100%' }}>
                              <SimulationRenderer
                                stages={simulationStages}
                                onChoice={(choice) => {
                                  const label = choice.label || choice.choiceId || 'A';
                                  const choiceId = choice.choiceId || choice.label || label;
                                  const promptText = `${label} 선택`;
                                  pendingDetailParentId.current = `${msg.id}::simulation::CHOICE::${label}`;
                                  const activeId = getAgentId(selectedAgent);
                                  // 고른 선택지를 방 상태에 기록 → 다음 전송 payload에 selectedChoice로 echo되어
                                  //  ai07가 같은 선택지 목록을 반복하지 않고 선택 결과/반응 단계로 진행한다.
                                  if (activeId) {
                                    const prevState = convStateRef.current[activeId] || {};
                                    convStateRef.current[activeId] = { ...prevState, selectedChoice: choiceId };
                                    setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
                                  }
                                  setMessage(promptText);
                                  setLearningMode('simulation');
                                  setShowMentionPopup(false);
                                  const inputEl = document.querySelector('.chat-input-premium input');
                                  if (inputEl) inputEl.focus();
                                }}
                              />
                            </div>
                          ) : debatePayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', borderLeft: `4px solid ${agentColor.border}`, maxWidth: '100%' }}>
                              <DebateRenderer stages={debateStages} />
                            </div>
                          ) : socraticPayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', borderLeft: `4px solid ${agentColor.border}`, maxWidth: '100%' }}>
                              <SocraticRenderer steps={socraticSteps} />
                            </div>
                          ) : (
                            <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`} style={{ whiteSpace: 'pre-wrap', backgroundColor: isUser ? undefined : agentTheme.bg, border: 'none', borderLeft: isUser ? undefined : `4px solid ${agentColor.border}` }}>
                              {isUser || isPlainReply ? (isPlainReply ? stripMarkdown(msg.content) : msg.content) : <RichText text={msg.content} />}
                            </div>
                          )}
                          {/* AI 환각 검증 결과(있을 때만): 답변 본문과 분리해 표시. high 위험은 경고 배지로 강조. (문제5) */}
                          {!isUser && !hasSimulationPayload && !debatePayload && !socraticPayload && msg.validation && (
                            <ValidationResult data={msg.validation} />
                          )}
                          {/* 검증 답변 말풍선엔 사용한 웹 근거 출처 칩을 단다 */}
                          {!hasSimulationPayload && !debatePayload && !isUser && Array.isArray(msg.sources) && msg.sources.length > 0 && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                              <span style={{ fontSize: '10px', color: '#9ca3af', alignSelf: 'center' }}>근거:</span>
                              {msg.sources.slice(0, 6).map((s, si) => (
                                s.url ? (
                                  <a key={si} href={s.url} target="_blank" rel="noopener noreferrer"
                                    style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.05)', color: 'var(--color-text-muted)', textDecoration: 'none' }}>
                                    {s.source}{s.title ? ` · ${String(s.title).slice(0, 24)}` : ''}
                                  </a>
                                ) : (
                                  <span key={si} style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.05)', color: 'var(--color-text-muted)' }}>
                                    {s.source}{s.title ? ` · ${String(s.title).slice(0, 24)}` : ''}
                                  </span>
                                )
                              ))}
                            </div>
                          )}
                          {/* 피드백 말풍선엔 성격 검증 점수 배지 */}
                          {!hasSimulationPayload && !debatePayload && !isUser && msg.pv && typeof msg.pv.score === 'number' && (
                            <div style={{ marginTop: '4px', fontSize: '10px', color: msg.pv.passed ? '#16a34a' : '#dc2626' }}>
                              성격 검증 {msg.pv.score.toFixed(2)} {msg.pv.passed ? '통과' : '보완 필요'}
                            </div>
                          )}
                          {/* 답변 하단 액션: 메모하기만 유지(저장된 메모 패널과 연동).
                              더 자세히/반박/비교/예시 등 후속 비교 액션은 발표 화면 단순화를 위해 제거.
                              (handleNodeAction은 '교수님들과 대화' 탭에서 계속 사용되므로 유지) */}
                          {!isUser && !hasSimulationPayload && !debatePayload && !socraticPayload && (
                            <div className="chat-answer-actions">
                              <button
                                type="button"
                                className={`answer-act is-memo ${bookmarkedIds.has(msg.id) ? 'on' : ''}`}
                                onClick={() => handleBookmark(msg)}
                              >
                                <Bookmark size={12} fill={bookmarkedIds.has(msg.id) ? '#16a34a' : 'none'} />
                                {bookmarkedIds.has(msg.id) ? '메모됨' : '메모하기'}
                              </button>
                            </div>
                          )}
                          {/* 단계 펼침/접힘 UI는 노출하지 않는다. processSteps는 결과 말풍선(1차/2차/3차)으로만 표시한다. */}
                          <div className="chat-bubble-time">{formatTime(msg.createdAt)}</div>
                        </div>
                      );
                    })
                  )}
                  {typingRooms[getAgentId(selectedAgent)] && (
                    <div className="chat-bubble-container ai">
                      <div className="chat-bubble-sender"><StagedTypingLabel /></div>
                      <div className="chat-bubble ai" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span className="dot" /><span className="dot" /><span className="dot" />
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
              )}

              {/* ── 교수님들과 대화 뷰 (기존 트리 구조 재사용) ── */}
              {isProfessorTab && (
                <div className="professor-discussion-view">
                  {/* 교실 배너(전체 표시) + 교수 hotspot + 교수별 말풍선 + 2단계 floating menu */}
                  <section className="professor-classroom-banner">
                    <img
                      src="/studymate-professor-classroom.png"
                      alt="교수님들과 함께 학습하는 픽셀 교실"
                      className="professor-classroom-banner-image"
                      draggable={false}
                    />

                    {/* 교수별 추천/유도 말풍선(actionMode 변경 시 pop 애니메이션).
                        목표 E.2: 질문을 전송(스트리밍 중)했거나 이미 대화가 시작됐으면 추천/유도 말풍선을 숨긴다.
                        새 방(대화 없음)에서만 안내 말풍선을 노출한다. */}
                    {!typingRooms[getAgentId(selectedAgent)] && mindmapMessages.length === 0 &&
                      (PROFESSOR_BUBBLES[professorActionMode] || PROFESSOR_BUBBLES.default).map((text, i) => (
                      <div
                        key={`${professorActionMode}-${i}`}
                        className={`professor-bubble is-active professor-bubble-${['left', 'center', 'right'][i]}`}
                      >
                        {text}
                      </div>
                    ))}

                    {/* 클릭 가능한 투명 hotspot 3개(통짜 PNG 위 overlay) */}
                    <button
                      type="button"
                      className={`professor-hotspot professor-hotspot-left ${professorMenuState.anchor === 'agent1' ? 'is-speaking' : ''}`}
                      aria-label="왼쪽 교수 선택"
                      onClick={() => openProfessorActionMenu('agent1')}
                    />
                    <button
                      type="button"
                      className={`professor-hotspot professor-hotspot-center ${professorMenuState.anchor === 'agent2' ? 'is-speaking' : ''}`}
                      aria-label="가운데 교수 선택"
                      onClick={() => openProfessorActionMenu('agent2')}
                    />
                    <button
                      type="button"
                      className={`professor-hotspot professor-hotspot-right ${professorMenuState.anchor === 'agent3' ? 'is-speaking' : ''}`}
                      aria-label="오른쪽 교수 선택"
                      onClick={() => openProfessorActionMenu('agent3')}
                    />

                    {/* 2단계 floating menu: 1) 모드별 액션 → 2) 대상 선택 */}
                    {professorMenuState.open && (
                      <div className={`professor-floating-menu ${PROFESSOR_HOTSPOT_POS[professorMenuState.anchor] || 'center'}`}>
                        <div className="professor-floating-menu-title">
                          {professorMenuState.step === 'action' ? '교수님께 요청할 액션' : '누구에게 들을까요?'}
                        </div>

                        {professorMenuState.step === 'action' ? (
                          <div className="professor-floating-menu-grid">
                            {professorActions.map((act) => (
                              <button
                                key={act.key}
                                type="button"
                                className={`professor-floating-menu-btn ${act.tone}`}
                                onClick={() => selectProfessorAction(act.key)}
                              >
                                <span aria-hidden="true">{act.icon}</span> {act.label}
                              </button>
                            ))}
                          </div>
                        ) : (
                          <div className="professor-floating-menu-grid">
                            {professorTargets.map((tgt) => (
                              <button
                                key={tgt.key}
                                type="button"
                                className="professor-floating-menu-btn"
                                onClick={() => {
                                  handleProfessorActionTarget({
                                    professorKey: professorMenuState.professorKey,
                                    actionKey: professorMenuState.actionKey,
                                    targetKey: tgt.key,
                                  });
                                  closeProfessorMenu();
                                }}
                              >
                                {tgt.label}
                              </button>
                            ))}
                          </div>
                        )}

                        <button type="button" className="professor-floating-menu-close" onClick={closeProfessorMenu}>
                          닫기
                        </button>
                      </div>
                    )}
                  </section>

                  {/* 트리: 최상단 전체 의견 + 교수/에이전트별 의견 카드 */}
                  <section className="professor-tree-section">
                    <div className="professor-tree-header">
                      <h3>{professorTreeTitle}</h3>
                      <p>아래에는 교수/에이전트별 관점이 정리됩니다.</p>
                    </div>
                    <div className="professor-tree-body">
                      <AgentDiscussionThread
                        messages={mindmapMessages}
                        typingAgents={
                          typingRooms[getAgentId(selectedAgent)]
                            ? (selectedAgent.agents || [{ id: 'ai', name: selectedAgent.name || 'AI' }]).map((ag, i) => ({
                                id: ag.id || i,
                                name: ag.name,
                                color: ['#2563eb','#EA580C','#7C3AED'][i % 3],
                              }))
                            : []
                        }
                        agents={selectedAgent.agents || []}
                        bookmarkedIds={bookmarkedIds}
                        onBookmark={handleBookmark}
                        onRequestDetail={handleNodeAction}
                        focusAgentName={
                          professorSelectedTarget === 'all'
                            ? null
                            : (selectedAgent.agents || [])[{ agent1: 0, agent2: 1, agent3: 2 }[professorSelectedTarget]]?.name || null
                        }
                      />
                    </div>
                  </section>
                </div>
              )}

              {/* ── 공통 입력창 ── */}
              <div style={{ position: 'relative', padding: '12px 20px 16px', backgroundColor: 'white', borderTop: '1px solid #f3f4f6', borderBottomLeftRadius: 16, borderBottomRightRadius: 16 }}>
                
                {/* 멘션 팝업 */}
                <AnimatePresence>
                  {showMentionPopup && selectedAgent && (
                    <motion.div 
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      transition={{ duration: 0.15 }}
                      style={{
                        position: 'absolute', bottom: '100%', left: '20px', marginBottom: '8px',
                        background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '12px',
                        boxShadow: '0 10px 25px rgba(0,0,0,0.1)', minWidth: '200px', overflow: 'hidden', zIndex: 100
                      }}
                    >
                      <ul style={{ listStyle: 'none', margin: 0, padding: '4px' }}>
                        {[{ name: '모두', color: '#60C95A' }, ...(selectedAgent.agents || [])]
                          .filter(ag => !mentionFilter || ag.name.toLowerCase().includes(mentionFilter.toLowerCase()))
                          .map((ag, idx) => (
                            <li 
                              key={idx}
                              style={{ 
                                padding: '10px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', 
                                fontSize: '13px', fontWeight: '600', color: '#374151', borderRadius: '8px', transition: 'background 0.2s'
                              }}
                              onMouseEnter={(e) => e.currentTarget.style.background = '#f3f4f6'}
                              onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                              onClick={() => {
                                const val = message;
                                const lastAtPos = val.lastIndexOf('@');
                                if (lastAtPos !== -1) {
                                  const beforeAt = val.slice(0, lastAtPos);
                                  const afterAtText = val.slice(lastAtPos);
                                  const spaceIndex = afterAtText.indexOf(' ');
                                  
                                  const afterMention = spaceIndex !== -1 ? afterAtText.slice(spaceIndex) : ' ';
                                  const newMsg = beforeAt + '@' + ag.name + afterMention;
                                  
                                  setMessage(newMsg);
                                  const activeId = getAgentId(selectedAgent);
                                  if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: newMsg }));
                                }
                                setShowMentionPopup(false);
                                const inputEl = document.querySelector('.chat-input-premium input');
                                if (inputEl) inputEl.focus();
                              }}
                            >
                              <div style={{ width: 24, height: 24, borderRadius: '50%', background: ag.color || '#e5e7eb', color: ag.color ? '#fff' : '#6b7280', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                                {ag.name === '모두' ? 'M' : <Bot size={13} />}
                              </div>
                              {ag.name}
                            </li>
                          ))
                        }
                      </ul>
                    </motion.div>
                  )}
                </AnimatePresence>

                {/* 라이브 모드 토글은 입력창 우측의 컴팩트 드롭다운으로 축소됨(아래 form 내부). */}
                <form onSubmit={sendMessage} className="chat-input-premium">
                  <input
                    type="text"
                    value={message}
                    onChange={(e) => {
                      const val = e.target.value;
                      setMessage(val);
                      
                      // 멘션 팝업 파싱 로직
                      const lastAtPos = val.lastIndexOf('@');
                      if (lastAtPos !== -1) {
                        const afterAt = val.slice(lastAtPos + 1);
                        if (!afterAt.includes(' ')) {
                          setShowMentionPopup(true);
                          setMentionFilter(afterAt);
                        } else {
                          setShowMentionPopup(false);
                        }
                      } else {
                        setShowMentionPopup(false);
                      }

                      const activeId = getAgentId(selectedAgent);
                      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: val }));
                    }}
                    onKeyDown={(e) => {
                      // 한글 등 IME 조합 중 Enter는 글자 확정용이다. 이때 폼이 submit되면
                      // 조합 중 텍스트가 조기/중복 전송되어 입력이 유실되는 것처럼 보인다(BUG-03).
                      // 조합 중 Enter는 전송을 막고 글자 확정만 하도록 한다.
                      if (e.key === 'Enter' && (e.nativeEvent?.isComposing || e.keyCode === 229)) {
                        e.preventDefault();
                      }
                    }}
                    placeholder={'교수님들과 학습할 질문을 입력하세요... (@를 입력해 에이전트 호출)'}
                    disabled={typingRooms[getAgentId(selectedAgent)]}
                  />
                  {/* 입력창 모드 선택 드롭다운 제거: 방 설정에서 정한 learningMode를 그대로 따른다.
                      (전송 payload의 mode/learningMode는 sendMessage에서 기존 방 모드로 계속 전송됨) */}
                  <button type="submit" disabled={typingRooms[getAgentId(selectedAgent)] || !message.trim()}>
                    <Send size={17} />
                  </button>
                </form>
              </div>
            </div>
          )}
        </div>

        {/* 우측 패널 토글 버튼 */}
        <button 
          onClick={() => setIsRightOpen(!isRightOpen)}
          style={{
            position: 'absolute', right: isRightOpen ? '320px' : '0', top: '50%', transform: 'translateY(-50%)', zIndex: 50,
            background: 'white', border: '1px solid #e5e7eb', borderRight: 'none', borderRadius: '12px 0 0 12px', padding: '10px 4px', cursor: 'pointer',
            boxShadow: '-4px 0 12px rgba(0,0,0,0.05)', transition: 'right 0.3s ease', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          {isRightOpen ? <ChevronRight size={16} color="#9ca3af" /> : <ChevronLeft size={16} color="#9ca3af" />}
        </button>

        {/* ════ 3. 우측: 저장된 메모 + 도움말 패널 (교실 배너는 교수님들과 대화 탭으로 이동) ════ */}
        {isRightOpen && (
          <div className="pane-right animate-fade-in" style={{ width: '320px', flexShrink: 0 }}>
            {!selectedAgent ? (
              <div className="dt-right-empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af', textAlign: 'center', padding: '20px' }}>
                <Bookmark size={36} color="#e5e7eb" style={{ marginBottom: '12px' }} />
                <div style={{ fontSize: '14px', fontWeight: '600', color: '#6b7280' }}>세션을 선택하면<br/>교수님들과 학습할 수 있어요</div>
              </div>
            ) : (
              <ProfessorLearningPanel
                memos={Array.from(bookmarkedIds)
                  .map((id) => chatHistory.find((m) => m.id === id))
                  .filter(Boolean)}
                onScrollToMemo={handleScrollToNode}
              />
            )}
          </div>
        )}
      </div>

      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ width: '95%', maxWidth: '600px', maxHeight: '90vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={20} color="var(--color-primary)" /> 새 AI 그룹 스터디 생성
              </h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)} aria-label="닫기"><X size={20} /></button>
            </div>

            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, overflow: 'hidden' }}>
              {/* 단계 표시 — 기본 설정 · AI 학습메이트 #1/#2/#3 (이미 만들어진 단계는 클릭으로 바로 이동) */}
              <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '6px', padding: '4px 0 10px', flexWrap: 'wrap' }}>
                {['기본 설정', 'AI 학습메이트 #1', 'AI 학습메이트 #2', 'AI 학습메이트 #3'].map((label, i) => {
                  const on = modalStep === i;
                  const reachable = i === 0 || i <= createdAgents.length;
                  return (
                    <button
                      type="button"
                      key={label}
                      onClick={() => reachable && setModalStep(i)}
                      disabled={!reachable}
                      style={{
                        padding: '4px 10px', borderRadius: '999px', fontSize: '11px',
                        fontWeight: on ? 800 : 600,
                        border: `1px solid ${on ? 'var(--color-primary)' : 'var(--color-border)'}`,
                        background: on ? 'var(--color-primary-soft, rgba(99,102,241,0.10))' : 'transparent',
                        color: on ? 'var(--color-primary)' : (reachable ? 'var(--color-text-muted)' : 'var(--color-border)'),
                        cursor: reachable ? 'pointer' : 'not-allowed', whiteSpace: 'nowrap',
                      }}
                    >{label}</button>
                  );
                })}
              </div>

              {/* 좌(‹) · 본문 · 우(›) — 큰 › 를 누르면 화면 단계 전체가 옆으로 넘어간다 */}
              <div style={{ display: 'flex', alignItems: 'stretch', gap: '6px', flex: 1, minHeight: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                  <button type="button" onClick={goPrevModalStep} disabled={modalStep === 0} aria-label="이전 단계" style={modalStep === 0 ? BIG_NAV_OFF : BIG_NAV}>‹</button>
                </div>

                <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', overflowX: 'hidden', paddingRight: '4px', display: 'flex', flexDirection: 'column', gap: '16px' }}>

                {modalStep === 0 && (<>
                {/* 스터디방 이름 설정 */}
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '6px' }}>
                    그룹 스터디방 이름
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    maxLength="50"
                    value={roomName}
                    onChange={(e) => setRoomName(e.target.value)}
                    placeholder={roomName ? "" : createdAgents.map(a => a.name.trim() || '새 에이전트').join(' & ') + '의 그룹 스터디'}
                  />
                </div>

                {/* 학습 방식 선택 — 질문 하나를 4가지 방식으로 */}
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '2px' }}>
                    학습 방식 선택
                  </label>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '8px' }}>
                    같은 질문도 학습 방식에 따라 완전히 다르게 배울 수 있습니다.
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {[
                      { value: 'basic', title: '기본 설명', desc: '개념을 빠르게 정리하고 예시와 함께 설명합니다.', result: '개념 정리 · 예시 · 핵심 요약' },
                      { value: 'socratic', title: '소크라테스', desc: '정답을 바로 주지 않고 질문과 힌트로 이해를 유도합니다.', result: '단계별 질문 · 힌트 · 오개념 확인' },
                      { value: 'debate', title: '토론', desc: '장점, 단점, 반론을 비교하며 사고를 넓힙니다.', result: '주장 · 근거 · 반박 · 결론' },
                      { value: 'simulation', title: '상황극', desc: '현실 상황 속 역할을 맡아 개념을 체험합니다.', result: '시나리오 · 선택지 · 피드백' },
                    ].map((opt) => {
                      const active = learningMode === opt.value;
                      return (
                        <label
                          key={opt.value}
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '10px',
                            padding: '10px 12px',
                            borderRadius: '10px',
                            border: `${active ? '2px' : '1px'} solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
                            backgroundColor: active ? 'var(--color-primary-soft, rgba(99,102,241,0.08))' : 'transparent',
                            cursor: 'pointer',
                          }}
                        >
                          <input
                            type="radio"
                            name="learningMode"
                            value={opt.value}
                            checked={active}
                            onChange={() => { setLearningMode(opt.value); setSelectedPresetId(null); setPresetCarouselIndex(0); }}
                            style={{ marginTop: '3px' }}
                          />
                          <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                              <div style={{ fontSize: '13px', fontWeight: active ? '800' : '700', color: active ? 'var(--color-primary)' : 'var(--color-text-main)' }}>{opt.title}</div>
                              {active && (
                                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '2px', fontSize: '11px', fontWeight: 700, color: 'var(--color-primary)' }}>
                                  <CheckCircle2 size={13} /> 선택됨
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginTop: '2px' }}>{opt.desc}</div>
                            <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '4px', opacity: 0.85 }}>결과: {opt.result}</div>
                          </div>
                        </label>
                      );
                    })}
                  </div>
                </div>

                {/* ── 추천 방 설정 가로 캐러셀 (소크라테스/토론/상황극 모드에서만) ── */}
                {/* 카드 5개를 세로로 쌓지 않고 ‹ › 로 한 장씩 넘긴다(가로 스크롤바 없음). */}
                {ROOM_PRESETS_BY_MODE[learningMode] && (() => {
                  const presets = ROOM_PRESETS_BY_MODE[learningMode];
                  const pIdx = Math.min(presetCarouselIndex, presets.length - 1);
                  const p = presets[pIdx];
                  const selected = selectedPresetId === p.id;
                  const pAtFirst = pIdx <= 0;
                  const pAtLast = pIdx >= presets.length - 1;
                  const pNav = {
                    width: '32px', height: '32px', borderRadius: '999px', border: '1px solid var(--color-border)',
                    background: '#fff', color: 'var(--color-primary)', fontSize: '18px', fontWeight: 800,
                    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  };
                  const pNavOff = { ...pNav, opacity: 0.35, cursor: 'not-allowed' };
                  return (
                  <div>
                    <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '2px' }}>
                      추천 방 설정
                    </label>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '8px' }}>
                      ‹ › 로 추천 방 설정을 넘겨 보고, 마음에 드는 카드를 누르면 세부 설정과 추천 에이전트가 자동으로 채워집니다.
                    </div>

                    {/* 캐러셀 헤더: ‹ 현재/총개수 + 점 › */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      <button type="button" onClick={goPrevPreset} disabled={pAtFirst} aria-label="이전 추천 방 설정" style={pAtFirst ? pNavOff : pNav}>‹</button>
                      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                        <span style={{ fontSize: '12px', fontWeight: 800, color: 'var(--color-primary)' }}>{pIdx + 1} / {presets.length}</span>
                        <div style={{ display: 'flex', gap: '5px' }}>
                          {presets.map((_, i) => (
                            <button type="button" key={i} onClick={() => setPresetCarouselIndex(i)} aria-label={`추천 방 설정 ${i + 1}`}
                              style={{ width: '8px', height: '8px', padding: 0, borderRadius: '999px', border: 'none', cursor: 'pointer', background: i === pIdx ? 'var(--color-primary)' : 'var(--color-border)' }} />
                          ))}
                        </div>
                      </div>
                      <button type="button" onClick={goNextPreset} disabled={pAtLast} aria-label="다음 추천 방 설정" style={pAtLast ? pNavOff : pNav}>›</button>
                    </div>

                    {/* 현재 추천 방 설정 카드 1장 — 누르면 적용 */}
                    <button
                      type="button"
                      aria-pressed={selected}
                      onClick={() => applyRoomPreset(p)}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '14px',
                        borderRadius: '12px',
                        border: `${selected ? '2px' : '1px'} solid ${selected ? 'var(--color-primary)' : 'var(--color-border)'}`,
                        background: selected ? 'var(--color-primary-soft, rgba(99,102,241,0.08))' : '#fff',
                        cursor: 'pointer',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '6px',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-primary)' }}>{p.label}</span>
                        {selected ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '2px', fontSize: '11px', fontWeight: 700, color: 'var(--color-primary)' }}>
                            <CheckCircle2 size={12} /> 선택됨
                          </span>
                        ) : (
                          <span style={{ fontSize: '10px', fontWeight: 700, color: 'var(--color-text-muted)' }}>· 누르면 적용</span>
                        )}
                      </div>
                      <div style={{ fontSize: '14px', fontWeight: 800, color: selected ? 'var(--color-primary)' : 'var(--color-text-main)' }}>{p.title}</div>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', lineHeight: 1.4 }}>{p.purpose}</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '2px' }}>
                        {roomPresetSummary(p).map((s, i) => (
                          <span key={i} style={{ fontSize: '10px', fontWeight: 600, color: 'var(--color-text-muted)', background: 'rgba(0,0,0,0.04)', borderRadius: '999px', padding: '2px 7px', whiteSpace: 'nowrap' }}>{s}</span>
                        ))}
                      </div>
                      <div style={{ fontSize: '10px', fontWeight: 700, color: 'var(--color-primary)', marginTop: '2px', lineHeight: 1.4 }}>
                        👥 에이전트 {p.agents.length}명 · {p.agents.map((a) => a.name).join(' · ')}
                      </div>
                    </button>
                  </div>
                  );
                })()}

                {/* ── 기본 설명 모드 안내 (기본 모드에서만) ── */}
                {learningMode === 'basic' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(99,102,241,0.04)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>기본 설명 모드</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
                      AI들이 사용자의 질문을 중심으로 개념을 정리하고, 예시와 핵심 요약을 제공합니다.
                    </div>
                  </div>
                )}

                {/* ── 상황극 설정 (상황극 모드에서만) ── */}
                {learningMode === 'simulation' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(29,78,216,0.04)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>상황극 모드</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>AI가 현실적인 상황을 만들고, 사용자가 선택과 피드백을 통해 개념을 체험하도록 진행합니다.</div>

                    <div>
                      <div style={dbLabelStyle}>상황 유형</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'realistic', t: '현실 상황' }, { v: 'roleplay', t: '면접 상황' }, { v: 'lab_scenario', t: '프로젝트 상황' }].map((o) => (
                          <button type="button" key={o.v} onClick={() => setSimulationConfig((c) => ({ ...c, scenarioType: o.v }))} style={dbChipStyle(simulationConfig.scenarioType === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>난이도</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'easy', t: '쉬움' }, { v: 'normal', t: '보통' }, { v: 'hard', t: '어려움' }].map((o) => (
                          <button type="button" key={o.v} onClick={() => setSimulationConfig((c) => ({ ...c, difficulty: o.v }))} style={dbChipStyle(simulationConfig.difficulty === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>선택지 개수</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[2, 3, 4].map((count) => <button type="button" key={count} onClick={() => setSimulationConfig((c) => ({ ...c, choiceCount: count }))} style={dbChipStyle(Number(simulationConfig.choiceCount) === count)}>{count}개</button>)}
                      </div>
                    </div>
                  </div>
                )}

                {/* ── 토론 설정 (토론 모드에서만) ── */}
                {learningMode === 'debate' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(124,58,237,0.04)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>토론 모드</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>AI들이 하나의 논제를 두고 찬성·반대·중립 관점에서 주장, 반박, 판정을 진행합니다.</div>

                    {/* 논제 방식 */}
                    <div>
                      <div style={dbLabelStyle}>논제 방식</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[{ v: 'auto', t: '자동 생성' }, { v: 'manual', t: '직접 입력' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setDebateConfig((c) => ({ ...c, topicMode: o.v }))}
                            style={dbChipStyle(debateConfig.topicMode === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* 직접 입력 논제 (직접 입력 선택 시에만) */}
                    {debateConfig.topicMode === 'manual' && (
                      <div>
                        <div style={dbLabelStyle}>논제 입력</div>
                        <input
                          type="text"
                          value={debateConfig.manualTopic}
                          onChange={(e) => setDebateConfig((c) => ({ ...c, manualTopic: e.target.value }))}
                          placeholder="예: 새로운 개념을 배울 때 이론을 먼저 익히는 것과 사례를 먼저 보는 것 중 무엇이 더 효과적인가?"
                          style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}
                        />
                      </div>
                    )}

                    {/* 토론 깊이 */}
                    <div>
                      <div style={dbLabelStyle}>토론 깊이</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[{ v: 'light', t: '가볍게' }, { v: 'normal', t: '보통' }, { v: 'deep', t: '깊게' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setDebateConfig((c) => ({ ...c, debateDepth: o.v }))}
                            style={dbChipStyle(debateConfig.debateDepth === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* ── 소크라테스 설정 (소크라테스 모드에서만) ── */}
                {learningMode === 'socratic' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(14,165,233,0.05)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>소크라테스 모드</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>AI가 정답을 바로 알려주기보다 질문과 힌트로 사용자의 이해를 유도합니다.</div>

                    {/* 질문 강도 */}
                    <div>
                      <div style={dbLabelStyle}>질문 강도</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'gentle', t: '부드럽게' }, { v: 'normal', t: '보통' }, { v: 'strict', t: '집중적으로' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, questionIntensity: o.v }))}
                            style={dbChipStyle(socraticConfig.questionIntensity === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* 힌트 방식 */}
                    <div>
                      <div style={dbLabelStyle}>힌트 방식</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'step_by_step', t: '단계별 힌트' }, { v: 'example_hint', t: '예시 힌트' }, { v: 'partial_answer_when_stuck', t: '막히면 일부 공개' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, hintPolicy: o.v }))}
                            style={dbChipStyle(socraticConfig.hintPolicy === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* 0단계 안내 — 추천 방 설정을 고른 뒤 오른쪽 큰 › 로 학습메이트 단계로 이동 */}
                <div style={{ marginTop: '4px', padding: '12px', borderRadius: '10px', border: '1px dashed var(--color-border)', background: 'rgba(99,102,241,0.04)', fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
                  AI 학습메이트는 1~3명까지 구성할 수 있습니다. 추천 방 설정을 선택한 뒤 오른쪽 <b style={{ color: 'var(--color-primary)' }}>›</b> 버튼으로 AI 학습메이트 #1 → #2 → #3 설정을 확인하세요.
                </div>
                </>)}

                {/* 1~3단계: AI 학습메이트 #N 설정 (modalStep - 1 번째 에이전트만 표시 — 세로 나열 X) */}
                {modalStep >= 1 && (() => {
                  const idx = Math.min(modalStep - 1, createdAgents.length - 1);
                  const agent = createdAgents[idx] || { ...DEFAULT_AGENT };
                  const total = createdAgents.length;
                  const canAdd = total < MAX_AGENT_COUNT;
                  const canRemove = total > MIN_AGENT_COUNT;
                  const stepBtn = {
                    width: '28px', height: '28px', borderRadius: '8px', border: '1px solid var(--color-border)',
                    background: '#fff', color: 'var(--color-primary)', fontSize: '16px', fontWeight: 800,
                    cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1, flexShrink: 0,
                  };
                  const stepBtnOff = { ...stepBtn, opacity: 0.35, cursor: 'not-allowed' };
                  return (
                  <div
                    style={{
                      border: '1px solid var(--color-border)',
                      borderRadius: '12px',
                      padding: '16px',
                      backgroundColor: 'rgba(249, 250, 251, 0.7)',
                      position: 'relative',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '12px'
                    }}
                  >
                    {/* 단계 제목 + 작은 인원 조절(+/-) — 큰 중단 박스 대신 우측 상단에 작게 둔다 */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                      <h4 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '15px', fontWeight: '800' }}>
                        <Bot size={18} /> AI 학습메이트 #{idx + 1} 설정
                      </h4>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <span style={{ fontSize: '11px', fontWeight: 700, color: 'var(--color-text-muted)' }}>인원</span>
                        <button type="button" onClick={removeAgent} disabled={!canRemove} aria-label="에이전트 줄이기" style={canRemove ? stepBtn : stepBtnOff}>−</button>
                        <span style={{ fontSize: '12px', fontWeight: 800, color: 'var(--color-primary)', minWidth: '30px', textAlign: 'center' }}>{total}명</span>
                        <button type="button" onClick={addAgent} disabled={!canAdd} aria-label="에이전트 늘리기" style={canAdd ? stepBtn : stepBtnOff}>＋</button>
                      </div>
                    </div>
                    <div style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                      {agent.role || '이 AI 학습메이트의 역할과 말투, 학습자 수준, 추가 요청을 설정하세요. 오른쪽 › 로 다음 학습메이트로 이동합니다.'}
                    </div>

                    {/* 학습메이트 유형 — 역할 개념. 선택된 하나만 active 강조 */}
                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>학습메이트 유형</label>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        {MATE_TYPES.map((t) => {
                          const selected = agent.agentPreset === t.key;
                          return (
                            <button
                              type="button"
                              key={t.key}
                              onClick={() => {
                                // 유형 버튼 = 프리셋. 역할/답변 톤/학습자 수준/추가 요청을 한 번에 채운다.
                                // 이름은 유형명을 그대로 복사하지 않고 자연스러운 후보로 자동 작명한다.
                                //  · 사용자가 이름을 직접 수정(nameEdited)한 경우에는 덮어쓰지 않는다.
                                //  · 같은 방의 다른 에이전트 이름과 겹치지 않게 한다.
                                const preset = LEARNING_MATE_TYPE_PRESETS[t.key] || {};
                                const list = [...createdAgents];
                                const cur = list[idx] || {};
                                const otherNames = list.filter((_, i) => i !== idx).map((a) => a && a.name);
                                const keepName = cur.nameEdited && String(cur.name || '').trim();
                                list[idx] = {
                                  ...cur,
                                  agentPreset: t.key,
                                  name: keepName ? cur.name : suggestMateName(t.key, otherNames),
                                  role: preset.role || t.role,
                                  personality: preset.tone || cur.personality,
                                  knowledgeLevel: preset.learnerLevel || cur.knowledgeLevel,
                                  customInstruction: preset.additionalRequest || '',
                                  goal: preset.role || t.role,
                                };
                                setCreatedAgents(list);
                              }}
                              style={{
                                padding: '4px 10px',
                                borderRadius: '999px',
                                border: `1px solid ${selected ? t.color : 'var(--color-border)'}`,
                                backgroundColor: selected ? t.color : 'transparent',
                                fontSize: '11px',
                                fontWeight: selected ? '800' : '600',
                                color: selected ? '#fff' : t.color,
                                cursor: 'pointer'
                              }}
                            >
                              {t.icon} {t.key}
                            </button>
                          );
                        })}
                      </div>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '6px', minHeight: '15px' }}>
                        {(MATE_TYPES.find((t) => t.key === agent.agentPreset) || {}).desc || '현재 AI 학습메이트의 역할과 말투를 선택하세요.'}
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>이름</label>
                      <input
                        type="text"
                        className="input-field"
                        maxLength="30"
                        required
                        value={agent.name}
                        onChange={(e) => {
                          const list = [...createdAgents];
                          // 사용자가 직접 이름을 수정하면 nameEdited 표시 → 유형 재선택 시 자동 작명이 덮어쓰지 않음
                          list[idx] = { ...list[idx], name: e.target.value, nameEdited: true };
                          setCreatedAgents(list);
                        }}
                        placeholder="예: 김영한"
                      />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>답변 톤</label>
                        <select
                          className="input-field"
                          // 레거시 저장값(친근하게 등)도 정규 7종 라벨로 매핑해 옵션이 항상 일치하게 한다.
                          value={canonicalPersonalityLabel(agent.personality)}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            // 답변 톤(personality)만 변경. 역할/유형은 학습메이트 유형에서 별도 관리한다.
                            list[idx] = { ...list[idx], personality: e.target.value };
                            setCreatedAgents(list);
                          }}
                        >
                          {TONE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                        </select>
                        <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '4px' }}>
                          AI가 어떤 말투로 설명할지 정합니다.
                        </div>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>학습자 수준</label>
                        <select
                          className="input-field"
                          value={normalizeKnowledgeLevel(agent.knowledgeLevel)}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[idx].knowledgeLevel = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {KNOWLEDGE_LEVELS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                        <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginTop: '4px' }}>
                          {knowledgeLevelDesc(agent.knowledgeLevel)}
                        </div>
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>추가 요청</label>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-muted)', marginBottom: '6px' }}>
                        답변에 꼭 반영하고 싶은 조건이 있으면 적어주세요.
                      </div>
                      <textarea
                        className="input-field"
                        style={{ height: '50px', paddingTop: '6px', resize: 'none' }}
                        maxLength="1000"
                        value={agent.customInstruction}
                        onChange={(e) => {
                          const list = [...createdAgents];
                          list[idx].customInstruction = e.target.value;
                          setCreatedAgents(list);
                        }}
                        placeholder="예: 코드 예시를 포함해줘 / 마지막에 3줄 요약해줘 / 영어 용어는 한글 뜻도 같이 알려줘"
                      />
                      {/* 추천 요청 칩 — 클릭 시 입력창 뒤에 자연스럽게 추가(중복 방지) */}
                      <div style={{ fontSize: '11px', fontWeight: '600', color: 'var(--color-text-muted)', margin: '8px 0 4px' }}>추천 요청</div>
                      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                        {REQUEST_GUIDE_CHIPS.map((chip) => (
                          <button
                            type="button"
                            key={chip.label}
                            onClick={() => {
                              const list = [...createdAgents];
                              const cur = String(list[idx].customInstruction || '').trim();
                              if (cur.includes(chip.text)) return; // 이미 포함되어 있으면 중복 추가 안 함
                              list[idx].customInstruction = cur ? `${cur} ${chip.text}` : chip.text;
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '3px 9px',
                              borderRadius: '999px',
                              border: '1px solid var(--color-border)',
                              background: 'transparent',
                              fontSize: '11px',
                              fontWeight: '600',
                              color: 'var(--color-text-muted)',
                              cursor: 'pointer'
                            }}
                          >
                            + {chip.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>
                  );
                })()}
                </div>{/* /본문 스크롤 */}

                <div style={{ display: 'flex', alignItems: 'center', flexShrink: 0 }}>
                  <button type="button" onClick={goNextModalStep} disabled={modalStep >= MAX_AGENT_COUNT} aria-label="다음 단계" style={modalStep >= MAX_AGENT_COUNT ? BIG_NAV_OFF : BIG_NAV}>›</button>
                </div>
              </div>{/* /좌·본문·우 */}

              <div style={{ display: 'flex', gap: '10px', marginTop: 'auto', paddingTop: '10px', borderTop: '1px solid var(--color-border)' }}>
                <button
                  type="button"
                  className="btn-outline"
                  style={{ flex: 1 }}
                  onClick={() => setShowModal(false)}
                >
                  취소
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  style={{ flex: 2 }}
                >
                  스터디방 생성하기
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showDetailsModal && selectedAgent && (
        <div className="modal-overlay" onClick={() => setShowDetailsModal(false)}>
          <div
            className="glass-panel modal-content"
            style={{
              width: '95%',
              maxWidth: '650px',
              maxHeight: '85vh',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              backgroundColor: 'rgba(255, 255, 255, 0.98)',
              backdropFilter: 'blur(16px)',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
              border: '1px solid rgba(255, 255, 255, 0.5)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--color-border)' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
                <Bot size={20} color="var(--color-primary)" /> 스터디방 에이전트 상세 정보
              </h3>
              <button
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}
                onClick={() => setShowDetailsModal(false)}
                aria-label="닫기"
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ padding: '0 4px' }}>
                <h4 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: '700', color: 'var(--color-text-main)' }}>
                  스터디 그룹
                </h4>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--color-text-muted)' }}>
                  {getDisplayRoomTitle(selectedAgent)}
                </p>
              </div>

              {/* 방 전체 학습 방식(모드) — 에이전트 카드보다 위, 연한 색 카드로 표시 */}
              {(() => {
                const mode = buildRoomModeInfo(selectedAgent);
                return (
                  <div style={{ padding: '0 4px' }}>
                    <h4 style={{ margin: '0 0 8px 0', fontSize: '15px', fontWeight: '700', color: 'var(--color-text-main)' }}>
                      학습 방식
                    </h4>
                    <div style={{
                      border: `1px solid ${mode.color}33`,
                      borderLeft: `4px solid ${mode.color}`,
                      borderRadius: '12px',
                      padding: '14px 16px',
                      background: `${mode.color}0D`,
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '8px'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <span style={{
                          fontSize: '12px', fontWeight: '800', color: '#fff',
                          background: mode.color, padding: '3px 10px', borderRadius: '999px'
                        }}>
                          {mode.label}
                        </span>
                        {mode.badge && (
                          <span style={{
                            fontSize: '11px', fontWeight: '700', color: mode.color,
                            background: `${mode.color}1A`, padding: '3px 10px', borderRadius: '999px'
                          }}>
                            {mode.badge}
                          </span>
                        )}
                      </div>
                      <p style={{ margin: 0, fontSize: '12.5px', lineHeight: 1.5, color: 'var(--color-text-muted)' }}>
                        {mode.desc}
                      </p>
                      {mode.rows.length > 0 && (
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '2px' }}>
                          {mode.rows.map((r) => (
                            <span key={r.k} style={{
                              fontSize: '11px', fontWeight: '600', color: 'var(--color-text-main)',
                              background: '#FFFFFF', border: '1px solid var(--color-border)',
                              padding: '3px 9px', borderRadius: '8px'
                            }}>
                              <span style={{ color: 'var(--color-text-muted)' }}>{r.k}</span>{' '}{r.v}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })()}

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {(selectedAgent.agents && selectedAgent.agents.length > 0 ? selectedAgent.agents : [selectedAgent]).map((ag, idx) => {
                  const agPersonality = getAgentPersonality(ag);
                  const agTheme = getAgentStyleTheme(agPersonality);
                  const agKnowledge = getAgentKnowledgeLevel(ag);
                  const agColor = getAgentColor(agentColorKey(ag));

                  return (
                    <div
                      key={ag.id || idx}
                      style={{
                        border: '1px solid var(--color-border)',
                        borderLeft: `4px solid ${agColor.border}`,
                        borderRadius: '12px',
                        padding: '16px',
                        backgroundColor: '#FFFFFF',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px',
                        boxShadow: '0 2px 4px rgba(0, 0, 0, 0.02)'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              width: '28px',
                              height: '28px',
                              borderRadius: '50%',
                              backgroundColor: agColor.bg,
                              color: agColor.text,
                              fontSize: '16px'
                            }}
                          >
                            {agTheme.icon}
                          </span>
                          <div>
                            <span style={{ fontWeight: 'bold', fontSize: '15px', color: agColor.text }}>{ag.name}</span>
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '11px', marginLeft: '6px' }}>({ag.role || '학습 메이트'})</span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              backgroundColor: 'rgba(96, 201, 90, 0.08)',
                              color: 'var(--color-primary)',
                              fontWeight: '600'
                            }}
                          >
                            {agKnowledge}
                          </span>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              backgroundColor: agTheme.tagBg,
                              color: agTheme.accent,
                              fontWeight: '600'
                            }}
                          >
                            {agPersonality}
                          </span>
                        </div>
                      </div>

                      {(() => {
                        const basePersona = ag.customInstruction || ag.custom_instruction || ag.persona || '';
                        const cleanedPersona = basePersona.replace('사용자의 학습을 돕는다', '').trim();
                        // 대괄호 태그들만 남고 알맹이가 없는 경우 노출하지 않음
                        const hasRealContent = ag.customInstruction || ag.custom_instruction || (cleanedPersona.replace(/\[지식수준:[^\]]+\]/, '').replace(/\[성격:[^\]]+\]/, '').trim().length > 0);
                        if (!hasRealContent) return null;

                        return (
                          <div style={{ fontSize: '13px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                            <div style={{ fontWeight: '600', marginBottom: '4px', color: 'var(--color-text-muted)' }}>사용자 지침 / 페르소나 설정</div>
                            <div
                              style={{
                                padding: '10px 12px',
                                backgroundColor: '#F9FAFB',
                                borderRadius: '8px',
                                border: '1px solid var(--color-border)',
                                fontStyle: 'normal',
                                whiteSpace: 'pre-wrap',
                                color: 'var(--color-text-main)'
                              }}
                            >
                              {ag.customInstruction || ag.custom_instruction || cleanedPersona}
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  );
                })}
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--color-border)' }}>
              <button
                type="button"
                className="btn-primary"
                style={{ width: '100%', borderRadius: '8px' }}
                onClick={() => setShowDetailsModal(false)}
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}

      <style>
        {`
          @keyframes typing {
            0%, 100% { transform: translateY(0); opacity: 0.5; }
            50% { transform: translateY(-3px); opacity: 1; }
          }
          .dot {
            display: inline-block;
            width: 4px; height: 4px;
            background-color: #6B7280;
            border-radius: 50%;
            margin: 0 2px;
            animation: typing 1s infinite;
          }
          .dot:nth-child(2) { animation-delay: 0.2s; }
          .dot:nth-child(3) { animation-delay: 0.4s; }
        `}
      </style>
    </div>
  );
}
