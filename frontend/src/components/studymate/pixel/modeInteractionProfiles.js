// ─────────────────────────────────────────────────────────────────────────────
// 모드별 교수 3인 인터랙션 안무(visual choreography) + 관계 라벨 정의.
//   · 순수 데이터/헬퍼만 둔다(시각 layer). SSE schema / 백엔드 payload / 최종 답변 내용은 건드리지 않는다.
//   · 프론트는 인터랙션을 "지어내지" 않는다. 백엔드 이벤트의 실제 내용만 정규화해 표시하고,
//     professor_motion 이 없을 때만 기존 이벤트로 visual fallback 을 적용한다.
//   · 교수 역할 3종 고정: book(문헌)/theory(이론)/ai(AI). 교수 수를 늘리지 않는다.
// ─────────────────────────────────────────────────────────────────────────────

import { roleForAgentIndex, ROLE_NAMES } from './professorSprites';

// 허용되는 sprite visual state(이 외 값은 무시) — professorSprites.STATE_ANIM 키와 일치.
export const VALID_VISUAL_STATES = new Set([
  'idle', 'hovered', 'selected', 'walking_to_question', 'thinking',
  'answering', 'validating', 'peer_feedback', 'returning', 'completed', 'error',
]);

export const PROFESSOR_ROLES = ['theory', 'book', 'ai'];

// ── (1)(2) 모드별 phase → 교수 visual state 매핑 ──────────────────────────────
export const MODE_INTERACTION_PROFILES = {
  basic: [
    { phase: 'question_received', states: { theory: 'thinking', book: 'thinking', ai: 'thinking' } },
    { phase: 'draft_answer', states: { theory: 'walking_to_question', book: 'thinking', ai: 'thinking' } },
    { phase: 'evidence_check', states: { theory: 'thinking', book: 'answering', ai: 'thinking' } },
    { phase: 'explain_simple', states: { theory: 'thinking', book: 'validating', ai: 'answering' } },
    { phase: 'cross_feedback', states: { theory: 'peer_feedback', book: 'peer_feedback', ai: 'peer_feedback' } },
    { phase: 'final_synthesis', states: { theory: 'completed', book: 'completed', ai: 'completed' } },
  ],
  socratic: [
    { phase: 'diagnostic_question', states: { theory: 'answering', book: 'thinking', ai: 'thinking' } },
    { phase: 'hint', states: { theory: 'thinking', book: 'thinking', ai: 'answering' } },
    { phase: 'misconception_check', states: { theory: 'validating', book: 'peer_feedback', ai: 'thinking' } },
    { phase: 'followup_question', states: { theory: 'answering', book: 'validating', ai: 'thinking' } },
    { phase: 'mini_summary', states: { theory: 'completed', book: 'completed', ai: 'completed' } },
  ],
  debate: [
    { phase: 'pro_claim', states: { theory: 'answering', book: 'thinking', ai: 'thinking' } },
    { phase: 'con_rebuttal', states: { theory: 'thinking', book: 'peer_feedback', ai: 'thinking' } },
    { phase: 'counter_rebuttal', states: { theory: 'peer_feedback', book: 'answering', ai: 'thinking' } },
    { phase: 'judge', states: { theory: 'validating', book: 'validating', ai: 'answering' } },
    { phase: 'balanced_conclusion', states: { theory: 'completed', book: 'completed', ai: 'completed' } },
  ],
  simulation: [
    { phase: 'scene_setup', states: { theory: 'thinking', book: 'thinking', ai: 'answering' } },
    { phase: 'role_action', states: { theory: 'answering', book: 'answering', ai: 'thinking' } },
    { phase: 'consequence_feedback', states: { theory: 'validating', book: 'peer_feedback', ai: 'thinking' } },
    { phase: 'debrief', states: { theory: 'completed', book: 'completed', ai: 'completed' } },
  ],
};

// ── (8) 모드별 phase → 사용자 표시 관계 라벨 ──────────────────────────────────
export const MODE_PHASE_LABELS = {
  basic: {
    question_received: '질문 접수', draft_answer: '초안 작성', evidence_check: '근거 보강',
    explain_simple: '쉬운 설명', cross_feedback: '논리 검증', final_synthesis: '보완 반영',
  },
  socratic: {
    diagnostic_question: '유도 질문', hint: '힌트', misconception_check: '오개념 점검',
    followup_question: '재질문', mini_summary: '정리',
  },
  debate: {
    pro_claim: '주장', con_rebuttal: '반박', counter_rebuttal: '재반박',
    judge: '판정', balanced_conclusion: '균형 결론',
  },
  simulation: {
    scene_setup: '상황 설정', role_action: '역할 대사', consequence_feedback: '상황 반응',
    debrief: '디브리핑',
  },
};

// 모드별 관계 라벨 순서(스테이지 식별이 애매할 때 도착 순서로 라벨링하는 fallback).
export const MODE_RELATION_LABELS = {
  basic: ['근거 보강', '논리 검증', '쉬운 설명', '보완 반영'],
  socratic: ['유도 질문', '힌트', '오개념 점검', '재질문'],
  debate: ['주장', '반박', '재반박', '판정'],
  simulation: ['역할 대사', '상황 반응', '결과 피드백', '디브리핑'],
};

export const normalizeMode = (mode) => {
  const m = String(mode || '').toLowerCase();
  if (m === 'basic' || m === 'socratic' || m === 'debate' || m === 'simulation') return m;
  return 'basic';
};

export const getModeProfile = (mode) => MODE_INTERACTION_PROFILES[normalizeMode(mode)] || MODE_INTERACTION_PROFILES.basic;

// phase → states (없으면 null). professor_motion.phase 또는 interaction phase 로 안무를 끌어올 때 사용.
export const phaseStatesFor = (mode, phase) => {
  const row = getModeProfile(mode).find((r) => r.phase === phase);
  return row ? row.states : null;
};

// professor_motion.states 를 안전한 {theory,book,ai} 로 정규화(허용 state 만, 누락 role 은 idle).
export const normalizeMotionStates = (states) => {
  const out = {};
  PROFESSOR_ROLES.forEach((role) => {
    const s = states && states[role];
    out[role] = VALID_VISUAL_STATES.has(s) ? s : 'idle';
  });
  return out;
};

// stageType 키워드 → 모드별 관계 라벨(없으면 도착 순서 idx 로 fallback).
const STAGE_LABEL_RULES = {
  debate: [
    [/CLAIM|OPENING|PRO/i, '주장'],
    [/COUNTER/i, '재반박'],
    [/REBUTTAL|CON/i, '반박'],
    [/JUDGE|MEDIAT|CLOSING|VERDICT/i, '판정'],
  ],
  socratic: [
    [/DIAGNOS|FIRST|OPEN/i, '유도 질문'],
    [/HINT/i, '힌트'],
    [/MISCONCEPT|CHECK/i, '오개념 점검'],
    [/FOLLOW|APPLICATION|COUNTEREX|NEXT/i, '재질문'],
  ],
  simulation: [
    [/ROLE|CHOICE|USER/i, '역할 대사'],
    [/REACT|CONSEQUENCE|NPC/i, '상황 반응'],
    [/FEEDBACK|LEARNING/i, '결과 피드백'],
    [/END|DEBRIEF|REFLECT/i, '디브리핑'],
  ],
  basic: [
    [/EVIDENCE|SOURCE|VALID/i, '논리 검증'],
    [/FEEDBACK|PEER/i, '보완 반영'],
    [/EXPLAIN|SIMPLE/i, '쉬운 설명'],
    [/DRAFT|FIRST|ANSWER/i, '근거 보강'],
  ],
};

export const relationLabelFor = (mode, stageType, idx = 0) => {
  const m = normalizeMode(mode);
  const st = String(stageType || '');
  const rules = STAGE_LABEL_RULES[m] || [];
  for (const [re, label] of rules) {
    if (re.test(st)) return label;
  }
  const list = MODE_RELATION_LABELS[m];
  return list[Math.max(0, idx) % list.length];
};

const roleName = (role) => ROLE_NAMES[role] || role || '';
const pickContent = (d) => String(
  (d && (d.content ?? d.answer ?? d.feedback ?? d.question ?? d.message ?? d.text)) || ''
).trim();
const pickRefs = (d) => {
  const r = (d && (d.sourceRefs ?? d.sources ?? d.evidence ?? d.refs)) || [];
  return Array.isArray(r) ? r : [];
};
const roleFromAny = (d, key) => {
  // agentIndex 계열 → role. 명시 role 이 있으면 우선.
  const explicit = d && (d[`${key}Role`] || d[`${key}_role`]);
  if (explicit && PROFESSOR_ROLES.includes(String(explicit))) return String(explicit);
  const idx = d && (d[`${key}AgentIndex`] ?? d[`${key}_agent_index`] ?? d[`${key}Index`]);
  if (idx != null && Number.isFinite(Number(idx))) return roleForAgentIndex(idx);
  return null;
};

// ── (11) 인터랙션 dedupe key ──────────────────────────────────────────────────
export const interactionKeyOf = ({ turnId, mode, phase, kind, agentId, targetAgentId, eventId }) =>
  `${turnId}:${mode}:${phase}:${kind}:${agentId ?? 'na'}:${targetAgentId || 'none'}:${eventId || ''}`;

// ── (3)(7)(12) 백엔드 이벤트 → 정규화된 인터랙션 레코드(들). 내용은 백엔드 실제값만 사용. ──
//  kind: 'interaction_event' | 'synthesis_diff' | 'peer_feedback' | 'debate' | 'socratic' | 'simulation' | 'validation'
//  반환: 인터랙션 레코드 배열(없으면 []). 각 레코드는 ProfessorInteractionTimeline 에서 그대로 렌더.
export const deriveInteractions = (mode, kind, data, turnId, seqHint = 0) => {
  const m = normalizeMode(mode);
  if (!data) return [];

  const make = (over) => {
    const fromRole = over.fromRole || null;
    const targetRole = over.targetRole || null;
    const rec = {
      turnId,
      mode: m,
      kind,
      phase: over.phase || '',
      phaseLabel: over.phaseLabel || over.relationLabel || '',
      relationLabel: over.relationLabel || '',
      fromRole,
      fromName: fromRole ? roleName(fromRole) : (over.fromName || ''),
      targetRole,
      targetName: targetRole ? roleName(targetRole) : (over.targetName || ''),
      content: over.content || '',
      sourceRefs: over.sourceRefs || [],
      appliedToFinal: over.appliedToFinal ?? null,
      agentId: over.agentId ?? null,
      targetAgentId: over.targetAgentId ?? null,
      eventId: over.eventId || (data.eventId ?? data.event_id ?? ''),
    };
    rec.key = interactionKeyOf(rec);
    return rec;
  };

  // 백엔드가 명시 interaction_event 를 주면 그대로(최우선·고신뢰) 표시한다.
  if (kind === 'interaction_event') {
    const fromRole = roleFromAny(data, 'from') || roleFromAny(data, 'agent');
    const targetRole = roleFromAny(data, 'target') || roleFromAny(data, 'to');
    const phase = data.phase || '';
    return [make({
      phase,
      phaseLabel: (MODE_PHASE_LABELS[m] && MODE_PHASE_LABELS[m][phase]) || data.phaseLabel || '',
      relationLabel: data.relationLabel || relationLabelFor(m, data.stageType || phase, seqHint),
      fromRole, targetRole,
      content: pickContent(data),
      sourceRefs: pickRefs(data),
      appliedToFinal: data.appliedToFinal ?? data.applied_to_final ?? null,
      agentId: data.agentId ?? data.fromAgentId ?? null,
      targetAgentId: data.targetAgentId ?? data.toAgentId ?? null,
      eventId: data.eventId ?? data.event_id ?? '',
    })];
  }

  // synthesis_diff: 어떤 인터랙션이 최종 답변에 반영됐는지. 별도 '보완 반영' 행으로 표시.
  if (kind === 'synthesis_diff') {
    const items = Array.isArray(data.diffs || data.items) ? (data.diffs || data.items) : [data];
    return items.map((it, i) => {
      const fromRole = roleFromAny(it, 'from') || roleFromAny(it, 'agent');
      return make({
        phase: 'final_synthesis',
        phaseLabel: '최종 반영',
        relationLabel: relationLabelFor(m, 'SYNTHESIS', MODE_RELATION_LABELS[m].length - 1),
        fromRole,
        content: pickContent(it),
        sourceRefs: pickRefs(it),
        appliedToFinal: it.appliedToFinal ?? it.applied ?? true,
        agentId: it.agentId ?? null,
        eventId: it.eventId ?? `${data.eventId ?? ''}#${i}`,
      });
    });
  }

  // 아래는 professor_motion/interaction_event 가 없을 때 '실제 콘텐츠 이벤트'를 라벨링한 fallback.
  if (kind === 'peer_feedback') {
    const fbs = Array.isArray(data.feedbacks) ? data.feedbacks
      : (Array.isArray(data) ? data : [data]);
    return fbs.map((fb, i) => {
      const fromRole = roleFromAny(fb, 'from') || roleFromAny(fb, 'agent');
      const targetRole = roleFromAny(fb, 'to') || roleFromAny(fb, 'target');
      const content = pickContent(fb);
      if (!content) return null;
      return make({
        phase: 'cross_feedback',
        phaseLabel: m === 'debate' ? '재반박' : '상호 피드백',
        relationLabel: relationLabelFor(m, fb.stageType || 'FEEDBACK', i),
        fromRole, targetRole,
        content,
        sourceRefs: pickRefs(fb),
        appliedToFinal: fb.appliedToFinal ?? null,
        agentId: fb.agentId ?? fb.fromAgentId ?? i,
        targetAgentId: fb.toAgentId ?? null,
        eventId: fb.eventId ?? `${turnId}#fb${i}`,
      });
    }).filter(Boolean);
  }

  // debate_section / socratic_step / simulation_stage / validation: 단건 이벤트 → 1행.
  if (kind === 'debate' || kind === 'socratic' || kind === 'simulation' || kind === 'validation') {
    const content = pickContent(data);
    if (!content) return [];
    const fromRole = roleFromAny(data, 'agent') || roleForAgentIndex(data.agentIndex ?? seqHint);
    return [make({
      phase: data.stageType || '',
      phaseLabel: data.stageTitle || data.stageType || '',
      relationLabel: relationLabelFor(m, data.stageType, seqHint),
      fromRole,
      content,
      sourceRefs: pickRefs(data),
      appliedToFinal: data.appliedToFinal ?? null,
      agentId: data.agentId ?? data.agentIndex ?? seqHint,
      eventId: data.eventId ?? `${turnId}#${kind}${data.stageType || seqHint}`,
    })];
  }

  return [];
};
