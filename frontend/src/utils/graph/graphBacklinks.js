// ─────────────────────────────────────────────────────────────────────────────
// backlink / outgoing link 계산(상세 패널의 "이 노드를 참조하는/연결한 항목").
// ─────────────────────────────────────────────────────────────────────────────

/**
 * @param {{nodes:any[], edges:any[]}} graph
 * @returns {{backlinks:Map<string,Array>, outgoing:Map<string,Array>, neighbors:Map<string,Set<string>>}}
 */
export function buildLinkIndex(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const backlinks = new Map();
  const outgoing = new Map();
  const neighbors = new Map();

  const addNeighbor = (a, b) => {
    if (!neighbors.has(a)) neighbors.set(a, new Set());
    neighbors.get(a).add(b);
  };

  edges.forEach((e) => {
    const fromNode = byId.get(e.from);
    const toNode = byId.get(e.to);
    if (!fromNode || !toNode) return;
    if (!outgoing.has(e.from)) outgoing.set(e.from, []);
    outgoing.get(e.from).push({ edge: e, node: toNode });
    if (!backlinks.has(e.to)) backlinks.set(e.to, []);
    backlinks.get(e.to).push({ edge: e, node: fromNode });
    addNeighbor(e.from, e.to);
    addNeighbor(e.to, e.from);
  });

  return { backlinks, outgoing, neighbors };
}
