// ─────────────────────────────────────────────────────────────────────────────
// 레이아웃 계산. nodeCount 에 따라 radial / force-directed 자동 선택.
//  · 결정적(deterministic): 같은 그래프면 같은 좌표(새로고침 후 동일 구조).
//  · 반환: { positions: Map<id,{x,y}>, bounds:{minX,minY,maxX,maxY}, mode }
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES } from './graphTypes';

export function pickLayoutMode(nodeCount) {
  if (nodeCount <= 30) return 'radial-local';
  if (nodeCount <= 80) return 'radial-expanded';
  if (nodeCount <= 200) return 'force-directed';
  if (nodeCount <= 500) return 'clustered-force';
  return 'clustered-lod-search-first';
}

const RING_RADIUS = [0, 170, 320, 470, 620];

// 교수(agent) 노드 고정 각도(라디안). theory 좌, book 하, ai 우.
const AGENT_ANGLE = { theory: Math.PI, book: Math.PI / 2, ai: 0 };

function buildAdjacency(edges) {
  const adj = new Map();
  edges.forEach((e) => {
    if (!adj.has(e.from)) adj.set(e.from, []);
    if (!adj.has(e.to)) adj.set(e.to, []);
    adj.get(e.from).push(e.to);
    adj.get(e.to).push(e.from);
  });
  return adj;
}

// BFS 레벨(중심으로부터의 거리).
function bfsLevels(nodes, edges, centerId) {
  const adj = buildAdjacency(edges);
  const level = new Map();
  const start = centerId && nodes.some((n) => n.id === centerId) ? centerId : (nodes[0] && nodes[0].id);
  if (start == null) return level;
  level.set(start, 0);
  let frontier = [start];
  let d = 0;
  while (frontier.length) {
    const next = [];
    d += 1;
    frontier.forEach((id) => {
      (adj.get(id) || []).forEach((nb) => {
        if (!level.has(nb)) { level.set(nb, d); next.push(nb); }
      });
    });
    frontier = next;
  }
  // 연결 안 된 노드는 가장 바깥 ring 으로.
  nodes.forEach((n) => { if (!level.has(n.id)) level.set(n.id, Math.min(4, d + 1)); });
  return level;
}

function radialLayout(nodes, edges, centerId) {
  const level = bfsLevels(nodes, edges, centerId);
  const byLevel = new Map();
  nodes.forEach((n) => {
    const lv = Math.min(4, level.get(n.id) ?? 4);
    if (!byLevel.has(lv)) byLevel.set(lv, []);
    byLevel.get(lv).push(n);
  });
  const positions = new Map();
  byLevel.forEach((group, lv) => {
    const r = RING_RADIUS[Math.min(lv, RING_RADIUS.length - 1)];
    if (lv === 0) { positions.set(group[0].id, { x: 0, y: 0 }); return; }
    const count = group.length;
    group.forEach((n, i) => {
      let angle;
      if (lv === 1 && n.type === NODE_TYPES.AGENT && AGENT_ANGLE[n.agentRole] != null) {
        angle = AGENT_ANGLE[n.agentRole];
      } else {
        angle = (2 * Math.PI * i) / count - Math.PI / 2 + (lv * 0.35);
      }
      positions.set(n.id, { x: Math.cos(angle) * r, y: Math.sin(angle) * r });
    });
  });
  return positions;
}

function forceLayout(nodes, edges, centerId, iterations) {
  const positions = new Map();
  const n = nodes.length || 1;
  // 초기 위치: 원 위에 index 순으로(결정적).
  nodes.forEach((node, i) => {
    if (node.id === centerId) { positions.set(node.id, { x: 0, y: 0 }); return; }
    const a = (2 * Math.PI * i) / n;
    const r = 120 + (i % 7) * 40;
    positions.set(node.id, { x: Math.cos(a) * r, y: Math.sin(a) * r });
  });
  const idIndex = new Map(nodes.map((node, i) => [node.id, i]));
  const k = 90; // 이상 간선 길이
  const repel = 9000;
  for (let it = 0; it < iterations; it += 1) {
    const disp = nodes.map(() => ({ x: 0, y: 0 }));
    // 반발력.
    for (let a = 0; a < nodes.length; a += 1) {
      for (let b = a + 1; b < nodes.length; b += 1) {
        const pa = positions.get(nodes[a].id);
        const pb = positions.get(nodes[b].id);
        let dx = pa.x - pb.x;
        let dy = pa.y - pb.y;
        let dist2 = dx * dx + dy * dy;
        if (dist2 < 1) { dx = (a - b) || 1; dy = 1; dist2 = 2; }
        const f = repel / dist2;
        const dist = Math.sqrt(dist2);
        disp[a].x += (dx / dist) * f; disp[a].y += (dy / dist) * f;
        disp[b].x -= (dx / dist) * f; disp[b].y -= (dy / dist) * f;
      }
    }
    // 인력(간선).
    edges.forEach((e) => {
      const ia = idIndex.get(e.from);
      const ib = idIndex.get(e.to);
      if (ia == null || ib == null) return;
      const pa = positions.get(e.from);
      const pb = positions.get(e.to);
      const dx = pa.x - pb.x;
      const dy = pa.y - pb.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (dist * dist) / k / 100;
      disp[ia].x -= (dx / dist) * f; disp[ia].y -= (dy / dist) * f;
      disp[ib].x += (dx / dist) * f; disp[ib].y += (dy / dist) * f;
    });
    const cool = 1 - it / (iterations + 1);
    nodes.forEach((node, i) => {
      if (node.id === centerId) return;
      const p = positions.get(node.id);
      const dlen = Math.sqrt(disp[i].x * disp[i].x + disp[i].y * disp[i].y) || 1;
      const limit = 30 * cool;
      p.x += (disp[i].x / dlen) * Math.min(dlen, limit);
      p.y += (disp[i].y / dlen) * Math.min(dlen, limit);
    });
  }
  return positions;
}

function boundsOf(positions) {
  let minX = Infinity; let minY = Infinity; let maxX = -Infinity; let maxY = -Infinity;
  positions.forEach((p) => {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
    if (p.x > maxX) maxX = p.x;
    if (p.y > maxY) maxY = p.y;
  });
  if (!Number.isFinite(minX)) { minX = 0; minY = 0; maxX = 1; maxY = 1; }
  return { minX, minY, maxX, maxY };
}

/**
 * @param {{nodes:any[], edges:any[]}} graph
 * @param {{centerNodeId?:string, modeOverride?:string}} [opts]
 */
export function computeLayout(graph, opts = {}) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const edges = Array.isArray(graph?.edges) ? graph.edges : [];
  const centerId = opts.centerNodeId;
  const mode = opts.modeOverride || pickLayoutMode(nodes.length);
  let positions;
  if (mode === 'radial-local' || mode === 'radial-expanded') {
    positions = radialLayout(nodes, edges, centerId);
  } else {
    const iter = nodes.length > 300 ? 80 : 140;
    positions = forceLayout(nodes, edges, centerId, iter);
  }
  // position 을 노드에도 반영(렌더/메타 보존).
  nodes.forEach((nd) => { nd.position = positions.get(nd.id) || { x: 0, y: 0 }; });
  return { positions, bounds: boundsOf(positions), mode };
}
