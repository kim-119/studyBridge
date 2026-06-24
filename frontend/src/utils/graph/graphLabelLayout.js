// ─────────────────────────────────────────────────────────────────────────────
// Graph label collision avoidance (Obsidian Graph View).
//  · 노드 라벨 / 간선 라벨 / 노드 원형 점 / 선택 halo 가 서로 겹치지 않도록 배치.
//  · 모든 계산은 "논리 좌표(layout positions)" 기준. 캔버스의 <g scale(k)> 안에서
//    렌더되므로 텍스트/박스 크기도 같은 논리 단위로 추정한다(아래 estimateTextWidth).
//  · 순수 함수 — KnowledgeGraphCanvas 가 상태(선택/hover/zoom/mode)를 풀어서 넘긴다.
//    회귀 테스트는 graphLabelLayout.test.mjs 참고.
// ─────────────────────────────────────────────────────────────────────────────

// ── 라벨 priority(낮을수록 먼저 배치 = 우선) ──────────────────────────────────
// spec 3단계: selected node > hovered node > question/room node > node
//            > selected edge > hovered edge > local edge > global edge
export const LABEL_PRIORITY = Object.freeze({
  SELECTED_NODE: 0,
  HOVERED_NODE: 1,
  KEY_NODE: 2, // question / room(agent) 등 핵심 노드
  NODE: 3,
  SELECTED_EDGE: 4,
  HOVERED_EDGE: 5,
  LOCAL_EDGE: 6,
  GLOBAL_EDGE: 7,
});

// 간선 라벨 법선 offset 후보(논리 px). 0 → ±12 → ±24 …
export const EDGE_OFFSETS = [0, 12, -12, 24, -24, 36, -36, 48, -48];
// 선택/hover/1-hop 간선은 더 멀리까지 시도(spec 7단계).
export const EDGE_OFFSETS_BOOSTED = [...EDGE_OFFSETS, 64, -64, 80, -80];

// pill padding(spec 13단계). collision box 는 padding 포함 크기.
const EDGE_PILL_PAD_X = 6;
const EDGE_PILL_PAD_Y = 2;
const NODE_LABEL_PAD_X = 4;

const EDGE_FONT = 10;
const NODE_FONT = 11;
const EDGE_LABEL_H = EDGE_FONT + EDGE_PILL_PAD_Y * 2 + 4; // ≈ 18
const NODE_LABEL_H = NODE_FONT + 4; // ≈ 15
// 노드 라벨은 점 아래로 (r + 12) 만큼 떨어진 곳에 baseline. 박스 center 보정값.
const NODE_LABEL_GAP = 12;

// CJK(한글/한자/가나/전각) 인지 — 폭 추정용.
const CJK_RE = /[　-鿿가-힣＀-￯]/;
const NARROW_RE = /[iIl.,'!|:;()[\]{}]/;

/** 텍스트의 렌더 폭(논리 px)을 폰트 크기 기준으로 추정. */
export function estimateTextWidth(text, fontSize = NODE_FONT) {
  let w = 0;
  for (const ch of String(text || '')) {
    if (CJK_RE.test(ch)) w += fontSize * 1.02;
    else if (NARROW_RE.test(ch)) w += fontSize * 0.34;
    else w += fontSize * 0.58;
  }
  return w;
}

/** 간선 라벨 박스 크기(padding 포함). foreignObject width 와 동일하게 쓴다. */
export function edgeLabelSize(text) {
  const w = estimateTextWidth(text, EDGE_FONT) + EDGE_PILL_PAD_X * 2;
  return { w: Math.max(24, Math.min(w, 84)), h: EDGE_LABEL_H };
}

/** 노드 라벨 박스(center 좌표 + 크기). 점(cx,cy,r) 아래에 위치. */
export function nodeLabelBox(cx, cy, r, text) {
  const w = estimateTextWidth(text, NODE_FONT) + NODE_LABEL_PAD_X * 2;
  return {
    x: cx,
    y: cy + r + NODE_LABEL_GAP + NODE_LABEL_H / 2,
    w,
    h: NODE_LABEL_H,
  };
}

// ── 충돌 판정 ────────────────────────────────────────────────────────────────
/** center 기준 두 사각형 overlap 여부(여백 padding 포함). */
export function rectsOverlap(a, b, padding = 4) {
  return (
    Math.abs(a.x - b.x) * 2 < a.w + b.w + padding * 2
    && Math.abs(a.y - b.y) * 2 < a.h + b.h + padding * 2
  );
}

/** 원(circle.x/y/r) 과 center 기준 사각형 overlap 여부. */
export function circleRectOverlap(circle, rect, padding = 4) {
  const dx = Math.abs(circle.x - rect.x) - rect.w / 2;
  const dy = Math.abs(circle.y - rect.y) - rect.h / 2;
  const reach = circle.r + padding;
  if (dx > reach || dy > reach) return false;
  if (dx <= 0 || dy <= 0) return true;
  return dx * dx + dy * dy <= reach * reach;
}

/** 후보 박스가 점유 영역(원/사각형) 과 충돌하는지. */
function collides(box, occupied, pad) {
  for (let i = 0; i < occupied.circles.length; i += 1) {
    if (circleRectOverlap(occupied.circles[i], box, pad.circle)) return true;
  }
  for (let i = 0; i < occupied.rects.length; i += 1) {
    if (rectsOverlap(occupied.rects[i], box, pad.rect)) return true;
  }
  return false;
}

/**
 * 간선 라벨 위치를 edge 중앙 → 법선 offset 순으로 탐색.
 * @returns {{x,y,w,h,offset,hidden:boolean}}
 */
export function resolveEdgeLabelPosition(edge, labelSize, occupied, options = {}) {
  const pad = { circle: options.circlePad ?? 4, rect: options.rectPad ?? 4 };
  const midX = (edge.sx + edge.tx) / 2;
  const midY = (edge.sy + edge.ty) / 2;
  let dx = edge.tx - edge.sx;
  let dy = edge.ty - edge.sy;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const candidates = edge.boosted ? EDGE_OFFSETS_BOOSTED : EDGE_OFFSETS;
  for (let i = 0; i < candidates.length; i += 1) {
    const off = candidates[i];
    const box = {
      x: midX + nx * off,
      y: midY + ny * off,
      w: labelSize.w,
      h: labelSize.h,
    };
    if (!collides(box, occupied, pad)) {
      return { ...box, offset: off, hidden: false };
    }
  }
  return { x: midX, y: midY, w: labelSize.w, h: labelSize.h, offset: 0, hidden: true };
}

// ── zoom level 별 간선 라벨 표시 정책(spec 10·11단계) ────────────────────────
// 반환: edge 가 "후보 표시 대상"인지 여부.
export function edgeLabelVisibleAtZoom(edge, zoom, ctx) {
  // 항상 보이는 케이스: 선택/hover 간선, edgeLabelsAlwaysOn.
  if (edge.selected || edge.hovered) return true;
  if (ctx.alwaysOn) return true;
  if (zoom < 0.6) return false; // 매우 축소 → 간선 라벨 숨김
  if (edge.oneHop) return true; // 선택 노드 1-hop 은 우선
  if (ctx.mode === 'global') {
    // Global: 1-hop / hover / 큰 zoom 에서만
    return zoom > 1.2 && ctx.edgeLabelsOn;
  }
  // Local: 0.6~1.0 은 focus 주변만, 1.0 이상은 전부(collision 으로 정리)
  if (zoom < 1.0) return edge.focus === true;
  return ctx.edgeLabelsOn || edge.focus === true;
}

/**
 * 전체 라벨 레이아웃 계산.
 * @param {object} input
 *  - nodes: [{ id, x, y, r, haloR, text, showLabel, priority }]
 *  - edges: [{ id, sx, sy, tx, ty, text, candidate, boosted, priority }]
 *  - options: { circlePad, rectPad, nodeNodePad }
 * @returns {{ nodeLabels: Map<id,{box,hidden}>, edgeLabels: Map<id,{x,y,w,h,hidden}> }}
 */
export function computeLabelLayout(input) {
  const { nodes = [], edges = [], options = {} } = input;
  const pad = { circle: options.circlePad ?? 4, rect: options.rectPad ?? 4 };
  const nodeNodePad = options.nodeNodePad ?? 2;

  const occupied = { circles: [], rects: [] };

  // 1) 노드 점 + halo 는 항상 점유(라벨이 점/halo 를 가리지 않도록).
  nodes.forEach((n) => {
    occupied.circles.push({ x: n.x, y: n.y, r: Math.max(n.r, n.haloR || 0) });
  });

  // 2) 노드 라벨을 priority 순으로 배치. 낮은 priority 라벨끼리 겹치면 양보(숨김).
  const nodeLabels = new Map();
  const sortedNodes = nodes
    .filter((n) => n.showLabel && n.text)
    .sort((a, b) => a.priority - b.priority);
  sortedNodes.forEach((n) => {
    const box = nodeLabelBox(n.x, n.y, n.r, n.text);
    // 핵심/선택/hover 라벨(priority < NODE)은 항상 표시 + 점유.
    const mustShow = n.priority < LABEL_PRIORITY.NODE;
    const clash = !mustShow
      && occupied.rects.some((r) => rectsOverlap(r, box, nodeNodePad));
    if (clash) {
      nodeLabels.set(n.id, { box, hidden: true });
      return;
    }
    nodeLabels.set(n.id, { box, hidden: false });
    occupied.rects.push(box);
  });

  // 3) 간선 라벨을 priority 순으로 배치. 이미 배치된 라벨/노드를 침범하지 않음.
  const edgeLabels = new Map();
  const sortedEdges = edges
    .filter((e) => e.candidate && e.text)
    .sort((a, b) => a.priority - b.priority);
  sortedEdges.forEach((e) => {
    const size = edgeLabelSize(e.text);
    const placed = resolveEdgeLabelPosition(e, size, occupied, pad);
    edgeLabels.set(e.id, placed);
    if (!placed.hidden) {
      occupied.rects.push({ x: placed.x, y: placed.y, w: placed.w, h: placed.h });
    }
  });

  return { nodeLabels, edgeLabels };
}
