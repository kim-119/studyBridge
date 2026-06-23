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

// 노드 타입별 한국어 라벨(범례/툴팁).
export const NODE_LABEL_KO = Object.freeze({
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
