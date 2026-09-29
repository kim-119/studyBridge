// ─────────────────────────────────────────────────────────────────────────────
// JSON Canvas(.canvas) 내보내기 — Obsidian Canvas 호환 형식.
// ─────────────────────────────────────────────────────────────────────────────

// Obsidian Canvas 는 색을 1~6 프리셋 또는 hex 로 받는다. 노드 타입을 프리셋에 매핑.
const CANVAS_COLOR = {
  question: '6', // purple
  agent: '5',    // blue
  answer: '4',   // cyan-ish (green preset)
  concept: '5',
  validation: '2', // orange
  rebuttal: '1',   // red
  example: '3',    // yellow
  source: '4',     // green
  roadmap: '4',
  planner: '6',
};

/**
 * @param {{nodes:any[], edges:any[]}} graph
 * @returns {{nodes:object[], edges:object[]}}
 */
export function generateJsonCanvas(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const canvasNodes = nodes.map((n) => {
    const pos = n.position || { x: 0, y: 0 };
    const width = n.type === 'question' ? 320 : 240;
    const height = Math.min(420, 80 + Math.ceil(String(n.body || '').length / 40) * 18);
    const text = `# ${n.title || n.label}\n\n${n.body || ''}`;
    return {
      id: n.id,
      type: 'text',
      text,
      x: Math.round(pos.x * 2.4),
      y: Math.round(pos.y * 2.4),
      width,
      height,
      color: CANVAS_COLOR[n.type] || '5',
    };
  });
  const canvasEdges = edges.map((e) => ({
    id: e.id,
    fromNode: e.from,
    toNode: e.to,
    label: e.label || undefined,
  }));
  return { nodes: canvasNodes, edges: canvasEdges };
}
