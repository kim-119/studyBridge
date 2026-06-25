// ─────────────────────────────────────────────────────────────────────────────
// Obsidian Graph 마인드맵 공통 타입/토큰 (단일 출처).
//  · TypeScript 미사용 프로젝트라 enum 대신 동결(freeze)된 상수 객체로 둔다.
//  · GraphNode/GraphEdge 의 형태(shape)는 JSDoc 으로만 문서화한다.
// ─────────────────────────────────────────────────────────────────────────────

/** @typedef {'question'|'agent'|'answer'|'concept'|'validation'|'rebuttal'|'example'|'source'|'roadmap'|'planner'|'tag'|'cluster'} GraphNodeType */
export const NODE_TYPES = Object.freeze({
  QUESTION: 'question',
  AGENT: 'agent',
  ANSWER: 'answer',
  CONCEPT: 'concept',
  VALIDATION: 'validation',
  REBUTTAL: 'rebuttal',
  EXAMPLE: 'example',
  SOURCE: 'source',
  ROADMAP: 'roadmap',
  PLANNER: 'planner',
  TAG: 'tag',
  CLUSTER: 'cluster',
});

/** @typedef {'asked_to'|'answered_by'|'produced'|'contains'|'validated_by'|'rebutted_by'|'exemplified_by'|'related_to'|'sourced_from'|'expanded_to'|'planned_by'|'references'} GraphEdgeType */
export const EDGE_TYPES = Object.freeze({
  ASKED_TO: 'asked_to',
  ANSWERED_BY: 'answered_by',
  PRODUCED: 'produced',
  CONTAINS: 'contains',
  VALIDATED_BY: 'validated_by',
  REBUTTED_BY: 'rebutted_by',
  EXEMPLIFIED_BY: 'exemplified_by',
  RELATED_TO: 'related_to',
  SOURCED_FROM: 'sourced_from',
  EXPANDED_TO: 'expanded_to',
  PLANNED_BY: 'planned_by',
  REFERENCES: 'references',
});

// 노드 타입별 색상 토큰(Obsidian 다크 캔버스 기준). 색상만으로 구분하지 않도록 shape 도 함께 둔다.
export const NODE_COLOR = Object.freeze({
  question: '#A78BFA',   // 보라
  agent: '#60A5FA',      // 파랑
  answer: '#22D3EE',     // 청록
  concept: '#93C5FD',    // 하늘
  validation: '#FB923C', // 주황
  rebuttal: '#F87171',   // 빨강
  example: '#FDE047',    // 노랑
  source: '#34D399',     // 초록
  roadmap: '#2DD4BF',    // 민트
  planner: '#F472B6',    // 분홍
  tag: '#9CA3AF',        // 회색
  cluster: 'rgba(167,139,250,0.18)',
});

// 노드 타입별 한국어 라벨(범례/툴팁). = semanticRole 표시 라벨의 단일 출처.
export const NODE_LABEL_KO = Object.freeze({
  room: '방',
  question: '질문',
  agent: '교수',
  answer: '답변',
  concept: '개념',
  validation: '검증',
  rebuttal: '반박',
  example: '예시',
  source: '자료',
  roadmap: '로드맵',
  planner: '플래너',
  tag: '태그',
  cluster: '클러스터',
});

// 간선 타입(relationRole)별 사용자 표시 라벨(단일 출처). 그래프 pill 은 [라벨] 형태로 표시.
//  · 본문 스니펫("작성"·"포함" 등) 대신 관계 역할을 명확히 보여준다.
export const EDGE_RELATION_LABEL = Object.freeze({
  has_question: '질문',
  asked_to: '질문 대상',
  answered_by: '답변',
  produced: '답변 생성',
  contains: '포함 개념',
  validated_by: '검증',
  rebutted_by: '반박',
  exemplified_by: '예시',
  related_to: '관련 개념',
  sourced_from: '자료 출처',
  expanded_to: '확장',
  planned_by: '계획',
  references: '참조',
});

export const relationLabelForEdgeType = (type) => EDGE_RELATION_LABEL[type] || EDGE_RELATION_LABEL.related_to;

// 노드 표시 라벨: semanticRole 기반(본문 스니펫 금지).
//  · concept 는 실제 개념명, agent 는 교수명을 보여주고, 그 외는 역할 한국어 라벨.
export function displayLabelForNode(node) {
  if (!node) return '';
  const role = node.semanticRole || node.type;
  if (role === 'concept') return node.shortLabel || node.title || node.label || '개념';
  if (role === 'agent') return node.agentName || node.shortLabel || node.label || '교수';
  return NODE_LABEL_KO[role] || node.shortLabel || node.label || '';
}

// 간선 표시 라벨: relationRole 기반.
export function displayLabelForEdge(edge) {
  if (!edge) return '';
  return relationLabelForEdgeType(edge.relationRole || edge.type);
}

// 간선 클릭 시 보여줄 "전체 관계 설명"(단일 출처). 선 위에는 짧은 라벨만, 전체 설명은 여기서 생성한다.
//  · relationRole 기반 관계 문장 + 양 끝 노드 이름 + (있으면) 대상 노드 본문 스니펫.
//  · nodeById: Map<id, node> (없으면 노드 이름 생략하고 관계 문장만).
const EDGE_RELATION_SENTENCE = Object.freeze({
  has_question: (a) => `${a} 방에서 던져진 질문입니다.`,
  asked_to: (a, b) => `${a}이(가) ${b}에게 던진 질문 관계입니다.`,
  answered_by: (a, b) => `${b || '교수'}이(가) "${a}"에 대해 핵심 개념과 구조를 설명한 답변입니다.`,
  produced: (a, b) => `${a}이(가) ${b}을(를) 생성한 관계입니다.`,
  contains: (a, b) => `${a} 안에서 다루는 핵심 개념 "${b}" 입니다.`,
  validated_by: (a, b) => `${b || '검증'}이(가) ${a}의 답변을 상호검증해 오류 가능성을 줄인 관계입니다.`,
  rebutted_by: (a, b) => `${b || '반박'}이(가) ${a}의 답변에서 허점·과장·누락된 전제·반례 가능성을 검토한 반박 관계입니다.`,
  exemplified_by: (a, b) => `${b || '예시'}이(가) ${a}을(를) 학습자 관점의 예시로 보강한 관계입니다.`,
  related_to: (a, b) => `${a}과(와) ${b}이(가) 서로 보완·연결되는 관련 관계입니다.`,
  sourced_from: (a, b) => `${a}이(가) ${b} 자료에서 근거를 가져온 출처 관계입니다.`,
  expanded_to: (a, b) => `${a}을(를) ${b}(으)로 확장·심화한 관계입니다.`,
  planned_by: (a, b) => `${b}이(가) ${a}에 대한 학습 계획을 세운 관계입니다.`,
  references: (a, b) => `${a}이(가) ${b}을(를) 참조한 관계입니다.`,
});

function edgeNodeName(node) {
  if (!node) return '';
  return node.title || displayLabelForNode(node) || node.shortLabel || node.label || '';
}

export function fullDescriptionForEdge(edge, nodeById) {
  if (!edge) return '이 선은 두 노드 사이의 학습 관계를 나타냅니다.';
  // 명시적 전체 설명이 데이터에 있으면 그대로 사용.
  if (edge.fullLabel) return edge.fullLabel;
  if (edge.description) return edge.description;

  const role = edge.relationRole || edge.type;
  const fromNode = nodeById?.get?.(edge.from);
  const toNode = nodeById?.get?.(edge.to);
  const a = edgeNodeName(fromNode) || '이 항목';
  const b = edgeNodeName(toNode) || '연결된 항목';

  const sentenceFn = EDGE_RELATION_SENTENCE[role];
  let sentence = sentenceFn
    ? sentenceFn(a, b)
    : `${a}과(와) ${b} 사이의 ${relationLabelForEdgeType(role)} 관계입니다.`;

  // 대상 노드 본문(검증/반박/예시 등 실제 내용)이 있으면 덧붙인다.
  const body = String(toNode?.body || toNode?.markdownBody || '').trim();
  if (body && body !== b) {
    const snippet = body.length > 320 ? `${body.slice(0, 320)}…` : body;
    sentence += `\n\n${snippet}`;
  }
  return sentence;
}

// 노드 타입별 shape('circle'|'square'|'diamond'|'triangle'). 색맹 대비 — 색 외 구분 수단.
export const NODE_SHAPE = Object.freeze({
  question: 'diamond',
  agent: 'square',
  answer: 'circle',
  concept: 'circle',
  validation: 'triangle',
  rebuttal: 'triangle',
  example: 'circle',
  source: 'square',
  roadmap: 'square',
  planner: 'square',
  tag: 'circle',
  cluster: 'circle',
});

// 간선 타입별 색/스타일 토큰. dashed=점선, directed=화살표.
export const EDGE_STYLE = Object.freeze({
  asked_to: { color: '#60A5FA', dashed: false, directed: true, label: '질문' },
  answered_by: { color: '#60A5FA', dashed: false, directed: true, label: '답변' },
  produced: { color: '#22D3EE', dashed: false, directed: true, label: '작성' },
  contains: { color: '#64748B', dashed: false, directed: true, label: '포함' },
  validated_by: { color: '#FB923C', dashed: true, directed: true, label: '검증' },
  rebutted_by: { color: '#F87171', dashed: true, directed: true, label: '반박' },
  exemplified_by: { color: '#FDE047', dashed: false, directed: true, label: '예시' },
  related_to: { color: '#A78BFA', dashed: false, directed: false, label: '관련' },
  sourced_from: { color: '#34D399', dashed: false, directed: true, label: '출처' },
  expanded_to: { color: '#2DD4BF', dashed: false, directed: true, label: '확장' },
  planned_by: { color: '#F472B6', dashed: false, directed: true, label: '계획' },
  references: { color: '#64748B', dashed: true, directed: true, label: '참조' },
});

// 마인드맵 저장 포맷 상수(자료보관함 오염 방지의 단일 출처).
export const MINDMAP_VIEW_TYPE = 'obsidian_graph';
export const MINDMAP_CONTENT_TYPE = 'application/vnd.studybridge.mindmap+json';
export const MINDMAP_FILE_TYPE = 'mindmap';

// 다크 테마 토큰(캔버스/패널).
export const GRAPH_THEME = Object.freeze({
  background: '#0b1020',
  panel: '#111827',
  panelBorder: '#1f2937',
  textPrimary: '#f9fafb',
  textSecondary: '#9ca3af',
  edge: 'rgba(148,163,184,0.35)',
  grid: 'rgba(148,163,184,0.06)',
});

export const styleForEdge = (type) => EDGE_STYLE[type] || EDGE_STYLE.related_to;
export const colorForNode = (type) => NODE_COLOR[type] || NODE_COLOR.concept;
export const shapeForNode = (type) => NODE_SHAPE[type] || 'circle';
export const labelForNodeType = (type) => NODE_LABEL_KO[type] || type;

// ── 2.5D 입체감 토큰 ─────────────────────────────────────────────────────────
// 노드 타입별 glow(halo) 강도(0~1). 색만으로 구분하지 않도록 shape 와 병행한다.
//  · 수가 많아지기 쉬운 concept/tag/example 은 성능을 위해 halo 를 생략(0)한다.
//  · 선택/중심/hover 노드는 렌더 시 별도로 강한 glow 를 덧입힌다(graphTypes 비의존).
export const NODE_GLOW = Object.freeze({
  question: 1.0,
  agent: 0.7,
  answer: 0.6,
  source: 0.55,
  roadmap: 0.55,
  planner: 0.55,
  validation: 0.5,
  rebuttal: 0.5,
  example: 0,
  concept: 0,
  tag: 0,
  cluster: 0,
});
export const glowForNode = (type) => NODE_GLOW[type] ?? 0;

// 선택/focus 시 "빛이 흐르는" flow 애니메이션을 줄 간선 타입(= AI 사고 흐름 강조).
//  · 항상 흐르면 산만하므로, 강조(선택/hover/타입 하이라이트) 상태에서만 활성화한다.
export const EDGE_FLOW_TYPES = Object.freeze(new Set([
  'asked_to', 'answered_by', 'produced', 'validated_by', 'rebutted_by', 'expanded_to', 'sourced_from',
]));
export const edgeFlows = (type) => EDGE_FLOW_TYPES.has(type);
