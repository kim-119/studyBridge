import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { Bot, Plus, Send, Sparkles, Trash2, X, MessageSquare, Network, ChevronLeft, ChevronRight, CheckCircle2, Bookmark } from 'lucide-react';
import AgentDiscussionThread from '../components/studymate/AgentDiscussionThread';
import '../components/studymate/studymate-premium.css';
import { motion, AnimatePresence } from 'framer-motion';

const PERSONALITY_OPTIONS = ['전문적', '친근함', '솔직함', '독특함', '효율적', '냉소적'];
const KNOWLEDGE_LEVEL_OPTIONS = ['입문 수준', '학사 수준', '석사 수준', '박사 수준', '전문가 수준'];

const DEFAULT_AGENT = {
  name: '',
  role: '',
  personality: '전문적',
  knowledgeLevel: '학사 수준',
  customInstruction: '',
  goal: '사용자의 학습을 돕는다'
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

// ── 에이전트 프리셋 (learningMode와 별개의 역할/성격 프리셋) ──────────────────────
// learningMode(basic/socratic/debate)와 섞지 않는다. 프리셋은 말투/전문성/관점을 정한다.
const AGENT_PRESETS = [
  { value: 'expert_professor', label: '전문교수', personality: '전문적', desc: '개념을 정의·원리·예시·한계로 체계적으로 설명' },
  { value: 'friendly_friend', label: '친근한친구', personality: '친근함', desc: '쉬운 비유와 편한 말투로 초보자가 질문하기 쉽게' },
  { value: 'creative_teacher', label: '독창적강사', personality: '독특함', desc: '비유·상상·시각적 예시로 추상 개념을 창의적으로' },
  { value: 'cold_mentor', label: '냉철한멘토', personality: '냉소적', desc: '오개념·부족한 점을 직설적으로 교정' },
  { value: 'misconception_tracker', label: '오개념탐지자', personality: '냉소적', desc: '헷갈린 개념·잘못된 전제·빠진 조건을 추적(소크라테스 핵심)' },
  { value: 'exam_maker', label: '시험출제자', personality: '효율적', desc: '개념을 객관식·단답·서술 문제로 변환' },
  { value: 'code_reviewer', label: '코드리뷰어', personality: '냉소적', desc: '설계 문제·나쁜 습관·유지보수 위험 지적' },
  { value: 'practical_architect', label: '실무아키텍트', personality: '전문적', desc: '프로젝트 구조·API·DB·배포 관점으로 설명' },
  { value: 'interviewer', label: '면접관', personality: '냉소적', desc: '압박·꼬리 질문으로 핵심 개념 검증' },
  { value: 'roadmap_coach', label: '로드맵코치', personality: '친근함', desc: '다음에 무엇을 어떤 순서로 공부할지 설계' },
];
const AGENT_PRESET_LABEL = Object.fromEntries(AGENT_PRESETS.map((p) => [p.value, p.label]));
const presetPersonality = (preset) => (AGENT_PRESETS.find((p) => p.value === preset)?.personality) || '전문적';

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
                {s.choices.map((choice) => (
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
const buildStageBubbles = (ps, parentId, createdAt) => {
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

  // 일반 staged 모드 — 항상 에이전트 1 → 2 → 3 순서로 표시한다.
  sortByAgentOrder(ps.initialAnswers).forEach((row, idx) => {
    out.push(mk('initial', row.agentName, stepContent(row), { idx, provider: row.provider, elapsedMs: row.elapsedMs }));
  });
  sortByAgentOrder(ps.validatedAnswers).forEach((row, idx) => {
    out.push(mk('validated', row.agentName, stepContent(row), {
      idx, provider: row.provider, elapsedMs: row.elapsedMs, sources: row.sources || [],
    }));
  });
  sortByAgentOrder(ps.peerFeedback).forEach((fb, idx) => {
    out.push(mk('feedback', fb.fromAgent, stepContent(fb), {
      idx, stageTo: fb.toAgent, pv: fb.personalityValidation || pvForName(ps.personalityValidationSummary, fb.fromAgent),
    }));
  });
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
      const bubbles = buildStageBubbles(ps, turnKey, msg.createdAt);
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

// 화면에 표시되는 채팅방/그룹 제목은 항상 '스터디 브릿지'로 고정한다.
// 내부 roomId, agentId, DB id 및 저장된 roomName 값은 절대 변경하지 않고 표시명만 고정한다.
const STUDYBRIDGE_ROOM_TITLE = '스터디 브릿지';
const getDisplayRoomTitle = () => STUDYBRIDGE_ROOM_TITLE;

const getAgentKnowledgeLevel = (agent) => {
  return agent?.knowledgeLevel
    || agent?.knowledge_level
    || parsePersonaTag(agent?.persona, '지식수준')
    || '학사 수준';
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
  const personality = PERSONALITY_OPTIONS.includes(agent.personality) ? agent.personality : '전문적';
  const knowledgeLevel = KNOWLEDGE_LEVEL_OPTIONS.includes(agent.knowledgeLevel) ? agent.knowledgeLevel : '학사 수준';
  const customInstruction = String(agent.customInstruction || '').trim();
  const goal = String(agent.goal || '사용자의 학습을 돕는다').trim();
  const personaBody = customInstruction || goal;
  const agentPreset = String(agent.agentPreset || '').trim();
  // agentPreset은 Agent 엔티티 컬럼이 없어 persona [프리셋: X] 태그로 인코딩(마이그레이션 없이 영속/복원).
  const presetTag = agentPreset ? `[프리셋: ${agentPreset}] ` : '';

  return {
    name: String(agent.name || '').trim(),
    role: String(agent.role || '').trim(),
    agentPreset,
    personality,
    personalityStrength: agent.personalityStrength || 'extreme',
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    goal,
    customInstruction,
    custom_instruction: customInstruction,
    persona: `${presetTag}[지식수준: ${knowledgeLevel}] [성격: ${personality}] ${personaBody}`,
  };
};

export default function StudyMate() {
  const { userId } = useAuth();

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  // 마인드맵 뷰가 받는 메시지(토론은 구조화 노드로 확장). chatHistory가 바뀔 때만 재계산한다.
  const mindmapMessages = React.useMemo(() => buildMindmapMessages(chatHistory), [chatHistory]);
  const [viewTab, setViewTab] = useState('chat'); // 'chat' | 'mindmap'
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

  // 멀티 에이전트 동적 추가를 위해 상태를 배열로 정의
  const [createdAgents, setCreatedAgents] = useState([{ ...DEFAULT_AGENT }]);
  const [roomName, setRoomName] = useState('');
  // 학습 진행 모드: basic(기본 채팅) / socratic(소크라테스) / debate(토론) / simulation(상황극)
  const [learningMode, setLearningMode] = useState('basic');
  // 토론 모드 논제/구조 설정 (생성 모달 + 메시지 전송에 사용)
  const [debateConfig, setDebateConfig] = useState(DEFAULT_DEBATE_CONFIG);
  // 소크라테스 문답 설정 (생성 모달 + 메시지 전송에 사용)
  const [socraticConfig, setSocraticConfig] = useState(DEFAULT_SOCRATIC_CONFIG);
  // 상황극 설정 (생성 모달 + 메시지 전송에 사용)
  const [simulationConfig, setSimulationConfig] = useState(DEFAULT_SIMULATION_CONFIG);

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
    setCreatedAgents([{ ...DEFAULT_AGENT }]);
    setRoomName('');
    setLearningMode('basic');
    setDebateConfig(DEFAULT_DEBATE_CONFIG);
    setSocraticConfig(DEFAULT_SOCRATIC_CONFIG);
    setSimulationConfig(DEFAULT_SIMULATION_CONFIG);
    setShowModal(true);
  };

  const handleCreateAgent = async (e) => {
    e.preventDefault();
    if (agents.length >= 3) {
      alert('생성된 학습방은 최대 3개까지 가질 수 있습니다.');
      return;
    }

    for (const agent of createdAgents) {
      if (!agent.name.trim() || !agent.role.trim()) {
        alert('모든 에이전트의 이름과 역할을 입력해야 합니다.');
        return;
      }
      if (agent.customInstruction && agent.customInstruction.trim().length < 5 && agent.customInstruction.trim().length > 0) {
        alert('에이전트 설명 또는 추가 요구사항은 공백이거나 최소 5자 이상이어야 합니다.');
        return;
      }
    }

    const payloadAgents = createdAgents.map(agent => buildCanonicalAgentPayload(agent));
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
      setCreatedAgents([{ ...DEFAULT_AGENT }]);
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

    // 1. 이전 방의 질문이 보이지 않도록 즉각적으로 해당 방의 캐시된 기록을 UI에 노출 (없으면 빈 리스트)
    const cachedHistory = roomHistories[agentId] || [];
    setChatHistory(cachedHistory);

    // 2. 해당 방의 드래프트가 존재하면 입력 폼에 로드
    setMessage(roomDrafts[agentId] || '');

    // 3. 최신 채팅 이력을 비동기 조회하여 동기화
    try {
      const rawHistory = await agentService.getChatHistory(userId, agentId);
      // DB에 저장된 processSteps(전체 map)를 그대로 사용해 아코디언을 복원 (슬라이스 없이 전원 표시)
      const history = hydrateHistoryProcessSteps(rawHistory);
      // 캐시 갱신
      setRoomHistories(prev => ({ ...prev, [agentId]: history || [] }));

      // 비동기 복귀 시점에도 여전히 이 방이 활성화되어 있을 때만 UI에 반영하여 다른 방 간섭 방지
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory(history || []);
      }
    } catch (err) {
      console.error('채팅 이력 조회 실패:', err);
      if (selectedAgentIdRef.current === agentId) {
        // 에러가 발생해도 이전 캐시를 그대로 보여줍니다.
      }
    }
  };

  const sendMessage = async (e, directMessage = null) => {
    if (e) e.preventDefault();
    const agentId = getAgentId(selectedAgent);
    const inputMsg = directMessage || message.trim();
    if (!inputMsg || !selectedAgent || typingRooms[agentId]) return;
    // ref 기반 동기 가드: state(typingRooms)가 갱신되기 전에 들어오는 두 번째 호출
    // (Enter키 + 버튼클릭 동시 입력 / 빠른 더블클릭 / StrictMode 재호출)을 즉시 차단한다.
    if (sendingRoomsRef.current.has(agentId)) {
      if (import.meta.env.DEV) console.debug('[StudyMate] 중복 전송 차단', { agentId });
      return;
    }
    sendingRoomsRef.current.add(agentId);

    // 이번 전송만의 고유 requestId. 방을 바꾼 뒤 늦게 도착하는 이전 요청 이벤트는 무시한다.
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeRequestRef.current[agentId] = requestId;
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

    const activeLearningMode = learningMode || selectedAgent?.learningMode || 'basic';
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

    // 이번 턴의 AI 메시지를 통째로 교체(누적 갱신)한다. 단계 도착마다 호출된다.
    //  - parentId(=userMsg.id) 기준으로 이 턴의 기존 AI 메시지를 제거 후 재삽입하므로,
    //    같은 이벤트가 여러 번 와도 append되지 않고 항상 1세트만 유지된다(upsert).
    //  - 더 새로운 요청이 시작됐으면(stale) 무시한다.
    const setTurnAiMessages = (aiMsgs) => {
      if (!isActiveRequest()) {
        if (import.meta.env.DEV) console.debug('[StudyMate] [DEDUPED] stale 요청 이벤트 무시', { agentId, requestId });
        return;
      }
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
    const buildStreamAiMsgs = (ps) => buildStageBubbles(ps, userMsg.id, new Date().toISOString());

    try {
      // ── 단계/섹션별 SSE 선출력 우선 시도 (default/debate/socratic 모두 스트리밍, 실패 시 블로킹 폴백) ──
      const STREAMING_ENABLED = (import.meta.env.VITE_STUDYMATE_SSE ?? 'true') !== 'false';
      if (STREAMING_ENABLED) {
        const ts = new Date().toISOString();
        // 일반 단계 누적
        const fullPS = { initialAnswers: [], validatedAnswers: [], peerFeedback: [], personalityValidationSummary: [] };
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
          const idx = d?.agentIndex ?? patch.agentIndex ?? 0;
          const aid = d?.agentId ?? patch.agentId ?? idx;
          const hash = contentHash(d?.content ?? d?.answer ?? patch.content ?? '');
          const key = `${d?.requestId || requestId}::basic::${d?.stageType || 'FIRST_DRAFT'}::${idx}::${aid}::${hash}`;
          const stableKey = `${d?.requestId || requestId}::basic::${d?.stageType || 'FIRST_DRAFT'}::${idx}::${aid}`;
          const prevKey = Array.from(agentAnswerMap.keys()).find((k) => k.startsWith(stableKey));
          if (prevKey && prevKey !== key) agentAnswerMap.delete(prevKey);
          agentAnswerMap.set(key, {
            id: key,
            content: d?.content ?? d?.answer ?? patch.content ?? '',
            sender: 'AI',
            senderName: d?.agentName || patch.agentName || selectedAgent?.name || 'AI',
            agentId: aid,
            agentIndex: idx,
            role: d?.role || patch.role,
            stageType: d?.stageType || 'FIRST_DRAFT',
            createdAt: d?.createdAt || patch.createdAt || ts,
            parentId: userMsg.id,
            isPending: !!patch.isPending,
            isError: !!patch.isError,
            statusText: patch.statusText || '',
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
          const bubbles = buildStageBubbles(ps, userMsg.id, ts);
          if (bubbles.length) { setTurnAiMessages(bubbles); return; }
          // 6) 일반 answers/replies 카드
          const answers = (d && (d.answers || d.replies)) || [];
          if (Array.isArray(answers) && answers.length) {
            setTurnAiMessages(sortByAgentOrder(answers).map((a, i) => ({
              id: `${userMsg.id}::ans::${i}`,
              content: a.answer || a.content || '',
              sender: 'AI',
              senderName: a.agentName || a.agent_name || selectedAgent?.name || 'AI',
              agentId: a.agentId,
              createdAt: ts,
              parentId: userMsg.id,
            })));
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

        try {
          await agentService.streamMessage(userId, agentId, {
            message: inputMsg,
            // 사용자가 고른 학습모드(라디오 상태)를 우선 전송한다(토론/소크라테스 분기).
            learningMode: activeLearningMode,
            rounds: 1,
            ...turnExtras,
          }, {
            onTurnStart: () => {},
            onHeartbeat: (d) => {
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
              if (!d) return;
              upsertAgentMessage(d, { isPending: false, content: d.content || d.answer || '' });
            },
            onAgentError: (d) => {
              if (!d) return;
              upsertAgentMessage(d, { isPending: false, isError: true, content: d.message || '이 에이전트의 응답 생성에 실패했습니다.' });
            },
            // default legacy 모드: 1차/2차/3차 단계 완료 시 즉시 반영. 저장 전에 에이전트 순서로 정렬한다.
            onStageComplete: (d) => {
              if (!d) return;
              if (d.stage === 1) fullPS.initialAnswers = sortByAgentOrder(d.answers || []);
              else if (d.stage === 2) fullPS.validatedAnswers = sortByAgentOrder(d.answers || []);
              else if (d.stage === 3) {
                fullPS.peerFeedback = sortByAgentOrder(d.feedbacks || []);
                fullPS.personalityValidationSummary = d.personalityValidationSummary || [];
              }
              streamRendered = true;
              setTurnAiMessages(buildStreamAiMsgs(fullPS));
            },
            // 토론 모드: 단계(debate_section) 도착 즉시 stageType+side로 upsert 후 갱신.
            onDebateSection: (d) => {
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
              if (!d) return;
              const answer = d.answer ?? (Array.isArray(d.answers) && d.answers[0] && d.answers[0].answer) ?? '';
              streamRendered = true;
              setTurnAiMessages([buildSocraticTurnMessage({
                socraticSteps: [{ stageType: 'SUMMARY', stageTitle: '정리 및 다음 학습 방향', role: '정리자', agentIndex: 3, content: answer, directAnswerSuppressed: false }],
                socraticConfig: socraticConfigAcc,
              }, userMsg.id, ts)]);
            },
            onAllComplete: (d) => {
              streamCompleted = true;
              renderAllComplete(d);
            },
            onError: () => { throw new Error('stream error event'); },
          });
          if (!streamCompleted && !streamRendered) {
            throw new Error('empty stream');
          }
          pendingDetailParentId.current = null;
          return; // 성공 — 바깥 finally에서 typing 해제
        } catch (streamErr) {
          const streamErrMessage = String(streamErr?.message || streamErr || '');
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
        // 사용자가 고른 학습모드(라디오) 우선, 없으면 방 설정/기본 채팅
        learningMode: activeLearningMode,
        rounds: 1, // 프론트단에서 타임아웃 방지를 위해 강제로 1라운드(병렬 단답)만 요청
        ...turnExtras,
      });
      console.debug('[StudyMate] chat response', res);

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
        const blockingStages = buildStageBubbles(res.processSteps, userMsg.id, new Date().toISOString());
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
                  const knowledgeLevel = getAgentKnowledgeLevel(agent);
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
                              agent.agents.map((ag, idx) => (
                                <span key={idx} className="dt-tag">#{ag.name}</span>
                              ))
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
                disabled={agents.length >= 3}
              >
                <Plus size={15} /> 새 AI 그룹 생성 ({agents.length}/3)
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
                          const c = getAvatarColor(idx);
                          return (
                            <div key={ag.id || idx} className="dt-agent-chip">
                              <div className="dt-chip-dot" style={{ backgroundColor: c.text }} />
                              <span>{ag.name}</span>
                              <span style={{ color: '#9ca3af', fontSize: 10 }}>({ag.role})</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}

                {/* 탭 전환 바 */}
                <div className="view-tab-bar">
                  <button
                    id="tab-chat"
                    className={`view-tab-btn ${viewTab === 'chat' ? 'active' : ''}`}
                    onClick={() => {
                      setViewTab('chat');
                      setIsLeftOpen(true);
                      setIsRightOpen(true);
                    }}
                  >
                    <MessageSquare size={13} /> 채팅
                  </button>
                  <button
                    id="tab-mindmap"
                    className={`view-tab-btn ${viewTab === 'mindmap' ? 'active mindmap' : ''}`}
                    onClick={() => {
                      setViewTab('mindmap');
                      setIsLeftOpen(false); // 마인드맵 진입 시 좌측 패널 자동 숨김
                      setIsRightOpen(false); // 마인드맵 진입 시 우측 패널 자동 숨김
                    }}
                  >
                    <Network size={13} /> 마인드맵 (크게 보기)
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

                      if (!isUser && selectedAgent && selectedAgent.agents) {
                        const matchedAgent = selectedAgent.agents.find(
                          (ag) => ag.name === senderName || ag.name === msg.senderName || ag.name === msg.sender_name
                        );
                        if (matchedAgent) {
                          agentPersonality = getAgentPersonality(matchedAgent);
                          agentTheme = getAgentStyleTheme(agentPersonality);
                          agentRole = matchedAgent.role;
                        }
                      }

                      return (
                        <div key={msg.id ?? `${msg.parentId}-${msg.badgeKey}-${idx}`} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                          <div className="chat-bubble-sender" style={{ display: 'flex', alignItems: 'center', gap: '6px', color: isUser ? undefined : agentTheme.accent }}>
                            {!isUser && (
                              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', backgroundColor: agentTheme.tagBg, fontSize: '11px' }}>
                                {agentTheme.icon}
                              </span>
                            )}
                            <span style={{ fontWeight: '700' }}>{senderName}</span>
                            {!isUser && msg.badge && (
                              <span style={{ fontSize: '10px', padding: '1px 7px', borderRadius: '999px', backgroundColor: `${msg.badge.color}22`, color: msg.badge.color, fontWeight: 'bold', whiteSpace: 'nowrap' }}>
                                {msg.badge.text}
                                {msg.badge.hint ? ` · ${msg.badge.hint}` : ''}
                              </span>
                            )}
                            {!isUser && msg.stageTo && (
                              <span style={{ fontSize: '10px', color: '#9ca3af' }}>→ {msg.stageTo}</span>
                            )}
                            {!isUser && agentRole && <span style={{ fontSize: '10px', color: '#9ca3af' }}>({agentRole})</span>}
                            {!isUser && agentPersonality && (
                              <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', backgroundColor: agentTheme.tagBg, color: agentTheme.accent, fontWeight: 'bold' }}>
                                {agentPersonality}
                              </span>
                            )}
                          </div>
                          {hasSimulationPayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', maxWidth: '100%' }}>
                              <SimulationRenderer
                                stages={simulationStages}
                                onChoice={(choice) => {
                                  const label = choice.label || choice.choiceId || 'A';
                                  const promptText = `${label} 선택`;
                                  pendingDetailParentId.current = `${msg.id}::simulation::CHOICE::${label}`;
                                  setMessage(promptText);
                                  setLearningMode('simulation');
                                  setShowMentionPopup(false);
                                  const activeId = getAgentId(selectedAgent);
                                  if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));
                                  const inputEl = document.querySelector('.chat-input-premium input');
                                  if (inputEl) inputEl.focus();
                                }}
                              />
                            </div>
                          ) : debatePayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', maxWidth: '100%' }}>
                              <DebateRenderer stages={debateStages} />
                            </div>
                          ) : socraticPayload ? (
                            <div className="chat-bubble ai" style={{ backgroundColor: agentTheme.bg, border: 'none', maxWidth: '100%' }}>
                              <SocraticRenderer steps={socraticSteps} />
                            </div>
                          ) : (
                            <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`} style={{ whiteSpace: 'pre-wrap', backgroundColor: isUser ? undefined : agentTheme.bg, border: 'none' }}>
                              {msg.content}
                            </div>
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

              {/* ── 마인드맵 뷰 ── */}
              {viewTab === 'mindmap' && (
                <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
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
                    onRequestDetail={(disc, actionType = 'detail') => {
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
                        
                      setMessage(promptText);
                      setShowMentionPopup(true);
                      setMentionFilter(''); // 전체 목록 보여주기
                      
                      const activeId = getAgentId(selectedAgent);
                      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));

                      const inputEl = document.querySelector('.chat-input-premium input');
                      if (inputEl) inputEl.focus();

                      setToastMsg('💡 하단 입력창에 이어서 질문을 작성해주세요.');
                      setTimeout(() => setToastMsg(''), 2500);
                    }}
                  />
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
                    placeholder={viewTab === 'mindmap' ? '마인드맵으로 탐색할 질문을 입력하세요... (@를 입력해 에이전트 호출)' : '메시지를 입력해보세요... (@호출)'}
                    disabled={typingRooms[getAgentId(selectedAgent)]}
                  />
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

        {/* ════ 3. 우측: 저장된 메모 (북마크) 패널 ════ */}
        {isRightOpen && (
          <div className="pane-right animate-fade-in" style={{ width: '320px', flexShrink: 0 }}>
            {!selectedAgent ? (
              <div className="dt-right-empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af', textAlign: 'center', padding: '20px' }}>
                <Bookmark size={36} color="#e5e7eb" style={{ marginBottom: '12px' }} />
                <div style={{ fontSize: '14px', fontWeight: '600', color: '#6b7280' }}>세션을 선택하면<br/>저장된 메모가 표시됩니다</div>
              </div>
            ) : (
              <div className="dt-insight-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px' }}>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
                <Bookmark size={20} color="#10b981" />
                <h3 style={{ 
                  margin: 0, fontSize: '15px', fontWeight: '800', color: '#334155'
                }}>저장된 메모 목록</h3>
                <span style={{ marginLeft: 'auto', background: '#ecfdf5', color: '#10b981', padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: 'bold' }}>
                  {bookmarkedIds.size}개
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px', flex: 1 }}>
                {bookmarkedIds.size === 0 ? (
                  <div style={{ fontSize: '13px', color: '#9ca3af', width: '100%', textAlign: 'center', padding: '40px 0', lineHeight: '1.6' }}>
                    <Bookmark size={24} color="#f1f5f9" style={{ margin: '0 auto 12px' }} fill="#e2e8f0" />
                    유용한 답변에 <br/><strong style={{color: '#64748b'}}>📌 메모하기</strong>를 누르면<br/>이곳에 저장됩니다.
                  </div>
                ) : (
                  Array.from(bookmarkedIds).map((id) => {
                    const msg = chatHistory.find(m => m.id === id);
                    if (!msg) return null;
                    return (
                      <div 
                        key={id} 
                        onClick={() => handleScrollToNode(id)}
                        style={{ 
                          padding: '16px', 
                          background: '#ffffff', 
                          borderRadius: '12px', 
                          border: '1px solid #e2e8f0', 
                          cursor: 'pointer',
                          transition: 'all 0.2s ease',
                          boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = '#34d399';
                          e.currentTarget.style.boxShadow = '0 4px 12px rgba(16,185,129,0.1)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = '#e2e8f0';
                          e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.02)';
                        }}
                      >
                        <div style={{ fontSize: '12px', color: '#10b981', fontWeight: '700', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                           <Bot size={14} /> {msg.senderName || msg.sender_name || 'AI'}
                        </div>
                        <div style={{ fontSize: '13px', color: '#334155', lineHeight: '1.5', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                          "{msg.content}"
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
            )}
          </div>
        )}
      </div>

      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ width: '95%', maxWidth: '600px', maxHeight: '85vh', overflow: 'hidden' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={20} color="var(--color-primary)" /> 새 AI 그룹 스터디 생성
              </h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)} aria-label="닫기"><X size={20} /></button>
            </div>

            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <div style={{ flex: 1, overflowY: 'auto', paddingRight: '4px', display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '16px' }}>

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

                {/* 학습 진행 모드 선택 */}
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '6px' }}>
                    학습 진행 모드
                  </label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {[
                      { value: 'basic', title: '기본 채팅 모드', desc: '각 AI가 바로 답변합니다.' },
                      { value: 'socratic', title: '소크라테스 모드', desc: '질문·힌트·오개념 추적으로 사용자가 스스로 답을 찾게 만드는 문답형 학습을 진행합니다.' },
                      { value: 'debate', title: '토론 모드', desc: '논제를 기준으로 반대측, 찬성측, 중립측이 주장·반박·판정을 수행하는 구조화 토론을 진행합니다.' },
                      { value: 'simulation', title: '상황극 모드', desc: '개념이 작동하는 가상 상황 속에서 역할을 맡고, 선택과 결과를 통해 학습합니다.' },
                    ].map((opt) => (
                      <label
                        key={opt.value}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: '10px',
                          padding: '10px 12px',
                          borderRadius: '10px',
                          border: `1px solid ${learningMode === opt.value ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          backgroundColor: learningMode === opt.value ? 'var(--color-primary-soft, rgba(99,102,241,0.08))' : 'transparent',
                          cursor: 'pointer',
                        }}
                      >
                        <input
                          type="radio"
                          name="learningMode"
                          value={opt.value}
                          checked={learningMode === opt.value}
                          onChange={() => setLearningMode(opt.value)}
                          style={{ marginTop: '3px' }}
                        />
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)' }}>{opt.title}</div>
                          <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginTop: '2px' }}>{opt.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>

                {/* ── 상황극 설정 (상황극 모드에서만) ── */}
                {learningMode === 'simulation' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(29,78,216,0.04)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>상황극 설정</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>상황 속 역할을 맡아 선택하고, 그 결과를 통해 개념·오개념·한계를 체험합니다.</div>

                    <div>
                      <div style={dbLabelStyle}>상황극 유형</div>
                      <select value={simulationConfig.scenarioType} onChange={(e) => setSimulationConfig((c) => ({ ...c, scenarioType: e.target.value }))} style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="realistic">현실 상황</option><option value="roleplay">역할극</option><option value="thought_experiment">사고실험</option><option value="branching_event">사건 분기</option><option value="inside_system">시스템 내부 관찰</option><option value="crisis_response">위기 대응</option><option value="historical_social_case">역사/사회 사례</option><option value="lab_scenario">실험실 상황</option>
                      </select>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>분야</div>
                      <select value={simulationConfig.domain} onChange={(e) => setSimulationConfig((c) => ({ ...c, domain: e.target.value }))} style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="auto">자동 판단</option><option value="computer_science">컴퓨터공학</option><option value="mathematics">수학</option><option value="life_science">생명과학</option><option value="psychology">심리학</option><option value="philosophy">철학</option><option value="environmental_engineering">환경공학</option><option value="business_economics">경영/경제</option><option value="other">기타</option>
                      </select>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>상호작용 방식</div>
                      <select value={simulationConfig.interactionStyle} onChange={(e) => setSimulationConfig((c) => ({ ...c, interactionStyle: e.target.value }))} style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="choice_based">선택지 기반</option><option value="roleplay_dialogue">역할극 대화</option><option value="event_progression">사건 진행형</option><option value="cause_effect_trace">원인-결과 추적형</option><option value="system_exploration">내부 시스템 탐험형</option>
                      </select>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>난이도</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'easy', t: '쉬움' }, { v: 'normal', t: '보통' }, { v: 'hard', t: '어려움' }, { v: 'advanced', t: '심화' }].map((o) => (
                          <button type="button" key={o.v} onClick={() => setSimulationConfig((c) => ({ ...c, difficulty: o.v }))} style={dbChipStyle(simulationConfig.difficulty === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>사용자 역할</div>
                      <select value={simulationConfig.userRoleMode} onChange={(e) => setSimulationConfig((c) => ({ ...c, userRoleMode: e.target.value }))} style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="auto">자동 설정</option><option value="decision_maker">의사결정자</option><option value="observer">관찰자</option><option value="analyst">분석가</option><option value="problem_solver">문제 해결자</option><option value="inner_component">내부 구성요소</option><option value="critical_reviewer">비판적 검토자</option>
                      </select>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>선택지 개수</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[2, 3, 4].map((count) => <button type="button" key={count} onClick={() => setSimulationConfig((c) => ({ ...c, choiceCount: count }))} style={dbChipStyle(Number(simulationConfig.choiceCount) === count)}>{count}개</button>)}
                      </div>
                    </div>

                    <div>
                      <div style={dbLabelStyle}>포함 요소</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[
                          { k: 'includeChoices', t: '선택지 포함' }, { k: 'includeConsequences', t: '결과 변화 포함' },
                          { k: 'includeConceptMapping', t: '개념 연결 포함' }, { k: 'includeMisconceptionTrap', t: '오개념 함정 포함' },
                          { k: 'includeReflectionQuestion', t: '성찰 질문 포함' }, { k: 'includeNextScenario', t: '다음 시나리오 포함' },
                        ].map((o) => <button type="button" key={o.k} onClick={() => setSimulationConfig((c) => ({ ...c, [o.k]: !c[o.k] }))} style={dbChipStyle(!!simulationConfig[o.k])}>{o.t}</button>)}
                      </div>
                    </div>
                  </div>
                )}

                {/* ── 토론 설정 (토론 모드에서만) ── */}
                {learningMode === 'debate' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(124,58,237,0.04)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>토론 설정</div>

                    {/* 논제 설정 방식 */}
                    <div>
                      <div style={dbLabelStyle}>논제 설정 방식</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[{ v: 'auto', t: '자동 생성' }, { v: 'manual', t: '직접 입력' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setDebateConfig((c) => ({ ...c, topicMode: o.v }))}
                            style={dbChipStyle(debateConfig.topicMode === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* 직접 입력 논제 */}
                    {debateConfig.topicMode === 'manual' && (
                      <div>
                        <div style={dbLabelStyle}>직접 입력 논제</div>
                        <input
                          type="text"
                          value={debateConfig.manualTopic}
                          onChange={(e) => setDebateConfig((c) => ({ ...c, manualTopic: e.target.value }))}
                          placeholder="예: OOP를 처음 배울 때 개념 이론보다 실무 예제 중심 학습이 더 효과적인가?"
                          style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}
                        />
                      </div>
                    )}

                    {/* 논제 유형 */}
                    <div>
                      <div style={dbLabelStyle}>논제 유형</div>
                      <select
                        value={debateConfig.motionType}
                        onChange={(e) => setDebateConfig((c) => ({ ...c, motionType: e.target.value }))}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}
                      >
                        <option value="learning_strategy">학습 전략형</option>
                        <option value="concept_definition">개념 정의형</option>
                        <option value="tech_choice">기술 선택형</option>
                        <option value="implementation_design">실무 설계형</option>
                        <option value="pros_cons">찬반 판단형</option>
                      </select>
                    </div>

                    {/* 쟁점 축 */}
                    <div>
                      <div style={dbLabelStyle}>쟁점 축</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {['개념정확성', '학습효율', '실무적용', '오개념위험', '유지보수성', '성능/비용', '시험대비'].map((axis) => (
                          <button type="button" key={axis}
                            onClick={() => setDebateConfig((c) => ({ ...c, issueAxes: toggleInArray(c.issueAxes, axis) }))}
                            style={dbChipStyle(debateConfig.issueAxes.includes(axis))}>{axis}</button>
                        ))}
                      </div>
                    </div>

                    {/* 토론 강도 */}
                    <div>
                      <div style={dbLabelStyle}>토론 강도</div>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {[{ v: 'light', t: '가볍게' }, { v: 'normal', t: '보통' }, { v: 'deep', t: '깊게' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setDebateConfig((c) => ({ ...c, debateDepth: o.v }))}
                            style={dbChipStyle(debateConfig.debateDepth === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* 포함 요소 */}
                    <div>
                      <div style={dbLabelStyle}>포함 요소</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ k: 'includeExamples', t: '예시 포함' }, { k: 'includeCounterexamples', t: '반례 포함' }, { k: 'includeStudyPlan', t: '학습 방향 포함' }].map((o) => (
                          <button type="button" key={o.k}
                            onClick={() => setDebateConfig((c) => ({ ...c, [o.k]: !c[o.k] }))}
                            style={dbChipStyle(!!debateConfig[o.k])}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* 판정 기준 */}
                    <div>
                      <div style={dbLabelStyle}>판정 기준</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {['논리성', '근거성', '반박력', '학습가치', '실무성'].map((cr) => (
                          <button type="button" key={cr}
                            onClick={() => setDebateConfig((c) => ({ ...c, judgeCriteria: toggleInArray(c.judgeCriteria, cr) }))}
                            style={dbChipStyle(debateConfig.judgeCriteria.includes(cr))}>{cr}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {/* ── 소크라테스 설정 (소크라테스 모드에서만) ── */}
                {learningMode === 'socratic' && (
                  <div style={{ marginTop: '12px', padding: '12px', borderRadius: '10px', border: '1px solid var(--color-border)', background: 'rgba(14,165,233,0.05)', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800, color: 'var(--color-text-main)' }}>소크라테스 설정</div>

                    {/* A. 학습 목표 */}
                    <div>
                      <div style={dbLabelStyle}>학습 목표</div>
                      <select value={socraticConfig.goal}
                        onChange={(e) => setSocraticConfig((c) => ({ ...c, goal: e.target.value }))}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="concept_understanding">개념 이해</option>
                        <option value="misconception_correction">오개념 교정</option>
                        <option value="exam_prep">시험 대비</option>
                        <option value="practical_application">실무 적용</option>
                        <option value="interview_prep">면접 대비</option>
                        <option value="code_algorithm_reasoning">코드/알고리즘 사고 훈련</option>
                      </select>
                    </div>

                    {/* B. 질문 강도 */}
                    <div>
                      <div style={dbLabelStyle}>질문 강도</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'gentle', t: '부드럽게' }, { v: 'normal', t: '보통' }, { v: 'strict', t: '엄격하게' }, { v: 'interviewer', t: '면접관처럼' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, questionIntensity: o.v }))}
                            style={dbChipStyle(socraticConfig.questionIntensity === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* C. 힌트 방식 */}
                    <div>
                      <div style={dbLabelStyle}>힌트 방식</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'minimal', t: '거의 없음' }, { v: 'step_by_step', t: '단계별 힌트' }, { v: 'example_hint', t: '예시 힌트' }, { v: 'partial_answer_when_stuck', t: '막히면 부분 정답' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, hintPolicy: o.v }))}
                            style={dbChipStyle(socraticConfig.hintPolicy === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* D. 정답 공개 */}
                    <div>
                      <div style={dbLabelStyle}>정답 공개</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'never', t: '공개 안 함' }, { v: 'final_only', t: '마지막에만' }, { v: 'partial_after_two_failures', t: '2번 틀리면 일부' }, { v: 'full_after_three_stucks', t: '3번 막히면 공개' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, answerRevealPolicy: o.v }))}
                            style={dbChipStyle(socraticConfig.answerRevealPolicy === o.v)}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* E. 질문 유형 */}
                    <div>
                      <div style={dbLabelStyle}>질문 유형</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ v: 'definition', t: '정의' }, { v: 'comparison', t: '비교' }, { v: 'why', t: '이유' }, { v: 'counterexample', t: '반례' }, { v: 'application', t: '적용' }, { v: 'metacognition', t: '메타인지' }, { v: 'code_reasoning', t: '코드 사고' }].map((o) => (
                          <button type="button" key={o.v}
                            onClick={() => setSocraticConfig((c) => ({ ...c, questionTypes: toggleInArray(c.questionTypes, o.v) }))}
                            style={dbChipStyle(socraticConfig.questionTypes.includes(o.v))}>{o.t}</button>
                        ))}
                      </div>
                    </div>

                    {/* F. 진행 방식 */}
                    <div>
                      <div style={dbLabelStyle}>진행 방식</div>
                      <select value={socraticConfig.feedbackStyle === 'concept_check' ? (socraticConfig._flow || 'short_qa') : 'short_qa'}
                        onChange={(e) => setSocraticConfig((c) => ({ ...c, _flow: e.target.value }))}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}>
                        <option value="short_qa">짧은 문답형</option>
                        <option value="deep_step">단계별 깊이 탐색</option>
                        <option value="exam_guided">시험 문제 유도형</option>
                        <option value="practical_case">실무 사례 유도형</option>
                        <option value="interview_pressure">면접 압박형</option>
                      </select>
                    </div>

                    {/* G. 포함 요소 */}
                    <div>
                      <div style={dbLabelStyle}>포함 요소</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                        {[{ k: 'includeExamples', t: '예시 포함' }, { k: 'includeCounterexamples', t: '반례 포함' }, { k: 'includeFinalSummary', t: '마지막 요약' }, { k: 'includeNextStudyPlan', t: '다음 학습 방향' }, { k: 'trackMisconceptions', t: '오개념 추적' }].map((o) => (
                          <button type="button" key={o.k}
                            onClick={() => setSocraticConfig((c) => ({ ...c, [o.k]: !c[o.k] }))}
                            style={dbChipStyle(!!socraticConfig[o.k])}>{o.t}</button>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                <div className="divider" style={{ margin: '8px 0' }} />

                {/* 에이전트 동적 폼 리스트 */}
                {createdAgents.map((agent, index) => (
                  <div
                    key={index}
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <h4 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: '700' }}>
                          <Bot size={16} /> AI 학습메이트 #{index + 1}
                        </h4>

                        {/* 추천 에이전트 생성 버튼 모음 */}
                        <div style={{ display: 'flex', gap: '4px', marginLeft: '4px', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '김민성',
                                role: '명문대 교수',
                                personality: '전문적',
                                knowledgeLevel: '박사 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(59, 130, 246, 0.2)',
                              backgroundColor: 'rgba(59, 130, 246, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#2563EB',
                              cursor: 'pointer'
                            }}
                          >
                            🎓 전문교수
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '둘리',
                                role: '친한친구',
                                personality: '친근함',
                                knowledgeLevel: '입문 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(249, 115, 22, 0.2)',
                              backgroundColor: 'rgba(249, 115, 22, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#EA580C',
                              cursor: 'pointer'
                            }}
                          >
                            ✨ 친근한친구
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '장동탁',
                                role: '4차원 강사',
                                personality: '독특함',
                                knowledgeLevel: '전문가 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(139, 92, 246, 0.2)',
                              backgroundColor: 'rgba(139, 92, 246, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#7C3AED',
                              cursor: 'pointer'
                            }}
                          >
                            👽 독창적강사
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '김영환',
                                role: '까칠한 스승',
                                personality: '냉소적',
                                knowledgeLevel: '학사 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(244, 63, 94, 0.2)',
                              backgroundColor: 'rgba(244, 63, 94, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#E11D48',
                              cursor: 'pointer'
                            }}
                          >
                            😈 냉철한멘토
                          </button>
                        </div>
                      </div>
                      {createdAgents.length > 1 && (
                        <button
                          type="button"
                          style={{
                            background: 'none',
                            border: 'none',
                            color: '#EF4444',
                            cursor: 'pointer',
                            fontSize: '12px',
                            fontWeight: '600',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                          }}
                          onClick={() => {
                            setCreatedAgents(createdAgents.filter((_, i) => i !== index));
                          }}
                        >
                          <X size={14} /> 제거
                        </button>
                      )}
                    </div>

                    {/* 에이전트 프리셋 (역할/성격 프리셋 — learningMode와 별개) */}
                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>
                        에이전트 프리셋 <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>(역할/성격)</span>
                      </label>
                      <select
                        value={agent.agentPreset || ''}
                        onChange={(e) => {
                          const preset = e.target.value;
                          const list = [...createdAgents];
                          list[index] = {
                            ...list[index],
                            agentPreset: preset,
                            // 프리셋 선택 시 성격을 함께 맞춰준다(사용자가 이후 수동 변경 가능).
                            personality: preset ? presetPersonality(preset) : list[index].personality,
                          };
                          setCreatedAgents(list);
                        }}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px' }}
                      >
                        <option value="">선택 안 함 (직접 설정)</option>
                        {AGENT_PRESETS.map((p) => (
                          <option key={p.value} value={p.value}>{p.label} — {p.desc}</option>
                        ))}
                      </select>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
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
                            list[index].name = e.target.value;
                            setCreatedAgents(list);
                          }}
                          placeholder="예: 김영한"
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>역할</label>
                        <input
                          type="text"
                          className="input-field"
                          maxLength="20"
                          required
                          value={agent.role}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].role = e.target.value;
                            setCreatedAgents(list);
                          }}
                          placeholder="예: 자바 전공교수"
                        />
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>성격/말투</label>
                        <select
                          className="input-field"
                          value={agent.personality}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].personality = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {PERSONALITY_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>지식수준</label>
                        <select
                          className="input-field"
                          value={agent.knowledgeLevel}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].knowledgeLevel = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {KNOWLEDGE_LEVEL_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>사용자 추가 요구사항</label>
                      <textarea
                        className="input-field"
                        style={{ height: '50px', paddingTop: '6px', resize: 'none' }}
                        maxLength="1000"
                        value={agent.customInstruction}
                        onChange={(e) => {
                          const list = [...createdAgents];
                          list[index].customInstruction = e.target.value;
                          setCreatedAgents(list);
                        }}
                        placeholder="예: 원어민처럼 영어로만 답변해줘"
                      />
                    </div>
                  </div>
                ))}

                {/* 에이전트 동적 추가 버튼 */}
                {createdAgents.length < 3 && (
                  <button
                    type="button"
                    className="btn-outline"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      width: '100%',
                      padding: '10px',
                      borderRadius: '8px',
                      fontSize: '13px',
                      fontWeight: '600',
                      borderStyle: 'dashed'
                    }}
                    onClick={() => setCreatedAgents([...createdAgents, { ...DEFAULT_AGENT }])}
                  >
                    <Plus size={16} /> AI 학습메이트 추가 ({createdAgents.length}/3)
                  </button>
                )}
              </div>

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

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {(selectedAgent.agents && selectedAgent.agents.length > 0 ? selectedAgent.agents : [selectedAgent]).map((ag, idx) => {
                  const agPersonality = getAgentPersonality(ag);
                  const agTheme = getAgentStyleTheme(agPersonality);
                  const agKnowledge = getAgentKnowledgeLevel(ag);

                  return (
                    <div
                      key={ag.id || idx}
                      style={{
                        border: '1px solid var(--color-border)',
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
                              backgroundColor: agTheme.tagBg,
                              fontSize: '16px'
                            }}
                          >
                            {agTheme.icon}
                          </span>
                          <div>
                            <span style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)' }}>{ag.name}</span>
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
