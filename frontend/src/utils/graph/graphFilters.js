// ─────────────────────────────────────────────────────────────────────────────
// 필터/Local·Global visible 그래프 계산.
//  · Local: centerNodeId 에서 depth 만큼 BFS.
//  · Global: 전체(타입 필터만 적용).
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES } from './graphTypes';

export const DEFAULT_FILTERS = Object.freeze({
  showAgents: true,
  showAnswers: true,
  showConcepts: true,
  showValidation: true,
  showRebuttal: true,
  showExamples: false, // 예시는 기본 숨김
  showSources: true,
  showRoadmaps: true,
  showPlanners: true,
  showTags: false,
  showOrphans: false, // 고립 노드 기본 숨김
});

// 노드 타입 → 필터 키 매핑(단일 출처). 범례 클릭 필터에서 재사용.
//  · question/cluster 는 토글 불가(키 없음) — 항상 표시.
export const TYPE_FILTER_KEY = {
  [NODE_TYPES.AGENT]: 'showAgents',
  [NODE_TYPES.ANSWER]: 'showAnswers',
  [NODE_TYPES.CONCEPT]: 'showConcepts',
  [NODE_TYPES.VALIDATION]: 'showValidation',
  [NODE_TYPES.REBUTTAL]: 'showRebuttal',
  [NODE_TYPES.EXAMPLE]: 'showExamples',
  [NODE_TYPES.SOURCE]: 'showSources',
  [NODE_TYPES.ROADMAP]: 'showRoadmaps',
  [NODE_TYPES.PLANNER]: 'showPlanners',
  [NODE_TYPES.TAG]: 'showTags',
};

const passesTypeFilter = (node, filters) => {
  if (node.type === NODE_TYPES.QUESTION || node.type === NODE_TYPES.CLUSTER) return true;
  const key = TYPE_FILTER_KEY[node.type];
  if (!key) return true;
  return filters[key] !== false;
};

/**
 * @param {{nodes:any[], edges:any[]}} graph
 * @param {{mode:'local'|'global', centerNodeId?:string, depth?:number, filters?:object}} opts
 * @returns {{nodes:any[], edges:any[]}}
 */
export function computeVisibleGraph(graph, opts) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const { mode = 'local', centerNodeId, depth = 2, filters = DEFAULT_FILTERS } = opts || {};
  const byId = new Map(nodes.map((n) => [n.id, n]));

  // 인접 리스트.
  const adj = new Map();
  edges.forEach((e) => {
    if (!adj.has(e.from)) adj.set(e.from, []);
    if (!adj.has(e.to)) adj.set(e.to, []);
    adj.get(e.from).push(e.to);
    adj.get(e.to).push(e.from);
  });

  let allowedIds;
  if (mode === 'local' && centerNodeId && byId.has(centerNodeId)) {
    // BFS depth.
    allowedIds = new Set([centerNodeId]);
    let frontier = [centerNodeId];
    for (let d = 0; d < Math.max(0, depth); d += 1) {
      const next = [];
      frontier.forEach((id) => {
        (adj.get(id) || []).forEach((nb) => {
          if (!allowedIds.has(nb)) { allowedIds.add(nb); next.push(nb); }
        });
      });
      frontier = next;
      if (!frontier.length) break;
    }
  } else {
    allowedIds = new Set(nodes.map((n) => n.id));
  }

  // 타입 필터.
  let visibleNodes = nodes.filter((n) => allowedIds.has(n.id) && passesTypeFilter(n, filters));
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  let visibleEdges = edges.filter((e) => visibleIds.has(e.from) && visibleIds.has(e.to));

  // 고립 노드 제거(옵션). 중심 노드는 항상 보존.
  if (!filters.showOrphans) {
    const connected = new Set();
    visibleEdges.forEach((e) => { connected.add(e.from); connected.add(e.to); });
    visibleNodes = visibleNodes.filter(
      (n) => connected.has(n.id) || n.id === centerNodeId || n.type === NODE_TYPES.QUESTION,
    );
    const ids2 = new Set(visibleNodes.map((n) => n.id));
    visibleEdges = visibleEdges.filter((e) => ids2.has(e.from) && ids2.has(e.to));
  }

  return { nodes: visibleNodes, edges: visibleEdges };
}
