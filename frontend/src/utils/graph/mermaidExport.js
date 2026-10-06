// ─────────────────────────────────────────────────────────────────────────────
// Mermaid `graph TD` 내보내기. 80개 초과면 center 기준 2-hop 만 출력한다.
// ─────────────────────────────────────────────────────────────────────────────
import { escapeMermaidLabel } from './wikilink';

function twoHopSubset(graph, centerId) {
  const adj = new Map();
  graph.edges.forEach((e) => {
    if (!adj.has(e.from)) adj.set(e.from, []);
    if (!adj.has(e.to)) adj.set(e.to, []);
    adj.get(e.from).push(e.to);
    adj.get(e.to).push(e.from);
  });
  const keep = new Set([centerId]);
  let frontier = [centerId];
  for (let d = 0; d < 2; d += 1) {
    const next = [];
    frontier.forEach((id) => (adj.get(id) || []).forEach((nb) => {
      if (!keep.has(nb)) { keep.add(nb); next.push(nb); }
    }));
    frontier = next;
  }
  return keep;
}

/**
 * @param {{nodes:any[], edges:any[], centerNodeId?:string}} graph
 * @returns {string}
 */
export function generateMermaidGraph(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const keep = nodes.length > 80 && graph.centerNodeId
    ? twoHopSubset(graph, graph.centerNodeId)
    : new Set(nodes.map((n) => n.id));

  const idToMermaid = new Map();
  let i = 0;
  const lines = ['graph TD'];
  nodes.forEach((n) => {
    if (!keep.has(n.id)) return;
    i += 1;
    const mid = `N${i}`;
    idToMermaid.set(n.id, mid);
    lines.push(`  ${mid}["${escapeMermaidLabel(n.shortLabel || n.label || n.title)}"]`);
  });
  edges.forEach((e) => {
    const a = idToMermaid.get(e.from);
    const b = idToMermaid.get(e.to);
    if (!a || !b) return;
    const lab = escapeMermaidLabel(e.label || '');
    lines.push(lab ? `  ${a} -->|${lab}| ${b}` : `  ${a} --> ${b}`);
  });
  return lines.join('\n');
}
