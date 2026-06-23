import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState,
} from 'react';
import { styleForEdge, colorForNode, shapeForNode, NODE_TYPES } from '../../utils/graph/graphTypes';

// ─────────────────────────────────────────────────────────────────────────────
// 다크 캔버스 SVG 렌더러. pan/zoom + 노드/간선 + 선택/hover 강조.
//  · positions: Map<id,{x,y}> (graphLayout 결과, 논리 좌표).
//  · 부모는 visibleGraph(필터/LOD 적용된 노드·간선)와 positions 를 넘긴다.
//  · 외부 제어: ref.fitView() / ref.centerOnNode(id) / ref.zoomBy(f).
// ─────────────────────────────────────────────────────────────────────────────

function nodeRadius(node, scale = 1) {
  const base = node.type === NODE_TYPES.QUESTION ? 16
    : node.type === NODE_TYPES.AGENT ? 12
      : node.type === NODE_TYPES.SOURCE ? 11
        : node.type === NODE_TYPES.CONCEPT ? 7 : 9;
  const r = base + Math.min(10, (node.degree || 0) * 1.3) + Math.min(4, (node.importance || 0) * 0.5);
  return r * scale;
}

// shape 별 SVG element. circle/square(rect)/diamond/triangle(polygon).
function NodeShape({ shape, r, color, dim }) {
  const opacity = dim ? 0.35 : 1;
  const common = { fill: color, opacity, stroke: '#0b1020', strokeWidth: 1.5 };
  if (shape === 'square') return <rect x={-r} y={-r} width={r * 2} height={r * 2} rx={3} {...common} />;
  if (shape === 'diamond') return <polygon points={`0,${-r * 1.3} ${r * 1.3},0 0,${r * 1.3} ${-r * 1.3},0`} {...common} />;
  if (shape === 'triangle') return <polygon points={`0,${-r * 1.3} ${r * 1.15},${r} ${-r * 1.15},${r}`} {...common} />;
  return <circle r={r} {...common} />;
}

const KnowledgeGraphCanvas = forwardRef(function KnowledgeGraphCanvas(props, ref) {
  const {
    graph, positions, bounds, selectedNodeId, centerNodeId, neighbors,
    showNodeLabels = true, showEdgeLabels = false, showArrows = true,
    nodeScale = 1, linkThickness = 1, labelThreshold: labelThresholdProp,
    onZoomChange, onNodeClick, onNodeDoubleClick, onBackgroundClick,
  } = props;

  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 520 });
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const [hoverId, setHoverId] = useState(null);
  const dragRef = useRef(null);

  // 컨테이너 크기 추적.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    const measure = () => setSize({ w: el.clientWidth || 800, h: el.clientHeight || 520 });
    measure();
    let ro;
    if (typeof ResizeObserver !== 'undefined') { ro = new ResizeObserver(measure); ro.observe(el); }
    return () => { if (ro) ro.disconnect(); };
  }, []);

  const fitView = useCallback(() => {
    const padding = 60;
    const gw = Math.max(1, bounds.maxX - bounds.minX);
    const gh = Math.max(1, bounds.maxY - bounds.minY);
    const k = Math.min((size.w - padding) / gw, (size.h - padding) / gh, 2.2);
    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    setView({ k: k > 0 && Number.isFinite(k) ? k : 1, x: size.w / 2 - cx * k, y: size.h / 2 - cy * k });
  }, [bounds, size.w, size.h]);

  // 그래프/크기 바뀌면 자동 fit.
  useEffect(() => { fitView(); }, [fitView, graph]);

  const centerOnNode = useCallback((id) => {
    const p = positions.get(id);
    if (!p) return;
    setView((v) => ({ ...v, x: size.w / 2 - p.x * v.k, y: size.h / 2 - p.y * v.k }));
  }, [positions, size.w, size.h]);

  const zoomBy = useCallback((factor) => {
    setView((v) => {
      const k = Math.min(2.6, Math.max(0.15, v.k * factor));
      const cx = size.w / 2; const cy = size.h / 2;
      return { k, x: cx - ((cx - v.x) / v.k) * k, y: cy - ((cy - v.y) / v.k) * k };
    });
  }, [size.w, size.h]);

  useImperativeHandle(ref, () => ({ fitView, centerOnNode, zoomBy }), [fitView, centerOnNode, zoomBy]);

  // pan.
  const onPointerDown = (e) => {
    if (e.target.closest('[data-node-id]')) return;
    dragRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onPointerMove = (e) => {
    if (!dragRef.current) return;
    setView((v) => ({ ...v, x: dragRef.current.vx + (e.clientX - dragRef.current.x), y: dragRef.current.vy + (e.clientY - dragRef.current.y) }));
  };
  const endDrag = () => { dragRef.current = null; };

  const onWheel = (e) => {
    e.preventDefault();
    const rect = wrapRef.current?.getBoundingClientRect();
    const px = rect ? e.clientX - rect.left : size.w / 2;
    const py = rect ? e.clientY - rect.top : size.h / 2;
    setView((v) => {
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      const k = Math.min(2.6, Math.max(0.15, v.k * factor));
      return { k, x: px - ((px - v.x) / v.k) * k, y: py - ((py - v.y) / v.k) * k };
    });
  };

  const focusId = hoverId || selectedNodeId;
  const focusSet = useMemo(() => {
    if (!focusId) return null;
    const s = new Set([focusId]);
    const nb = neighbors?.get(focusId);
    if (nb) nb.forEach((id) => s.add(id));
    return s;
  }, [focusId, neighbors]);

  const labelThreshold = labelThresholdProp != null
    ? labelThresholdProp
    : (graph.nodes.length > 120 ? 1.1 : graph.nodes.length > 60 ? 0.7 : 0);
  const edgeColors = useMemo(() => Array.from(new Set(graph.edges.map((e) => styleForEdge(e.type).color))), [graph.edges]);

  // 줌 레벨을 부모(상태바)로 보고.
  useEffect(() => { onZoomChange?.(Math.round(view.k * 100)); }, [view.k, onZoomChange]);

  return (
    <div
      ref={wrapRef}
      className={`obsg-canvas-wrap${dragRef.current ? ' is-panning' : ''}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerLeave={endDrag}
      onWheel={onWheel}
    >
      {graph.nodes.length === 0 ? (
        <div className="obsg-empty">
          <span>표시할 노드가 없습니다.</span>
          <span style={{ fontSize: 12 }}>필터를 조정하거나 질문을 입력해 보세요.</span>
        </div>
      ) : (
        <svg className="obsg-svg" width={size.w} height={size.h}>
          <defs>
            {edgeColors.map((c) => (
              <marker key={c} id={`obsg-arrow-${c.replace(/[^a-z0-9]/gi, '')}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" fill={c} />
              </marker>
            ))}
          </defs>
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {/* 간선 */}
            {graph.edges.map((e) => {
              const a = positions.get(e.from);
              const b = positions.get(e.to);
              if (!a || !b) return null;
              const st = styleForEdge(e.type);
              const active = !focusSet || (focusSet.has(e.from) && focusSet.has(e.to));
              const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
              const labelOn = (showEdgeLabels || (focusSet && active)) && e.label;
              const pw = Math.max(28, String(e.label).length * 8 + 14);
              return (
                <g key={e.id}>
                  <line
                    className="obsg-edge"
                    x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                    stroke={st.color}
                    strokeWidth={(active ? 1.6 : 1) * linkThickness}
                    strokeOpacity={focusSet ? (active ? 0.85 : 0.12) : 0.28}
                    strokeDasharray={st.dashed ? '5 4' : undefined}
                    markerEnd={showArrows && st.directed ? `url(#obsg-arrow-${st.color.replace(/[^a-z0-9]/gi, '')})` : undefined}
                  />
                  {labelOn ? (
                    <foreignObject x={mid.x - pw / 2} y={mid.y - 10} width={pw} height={20} style={{ overflow: 'visible', pointerEvents: 'none' }}>
                      <div className="obsg-edge-pill"><span>{e.label}</span></div>
                    </foreignObject>
                  ) : null}
                </g>
              );
            })}
            {/* 노드 */}
            {graph.nodes.map((n) => {
              const p = positions.get(n.id);
              if (!p) return null;
              const r = nodeRadius(n, nodeScale);
              const dim = !!(focusSet && !focusSet.has(n.id));
              const isSel = n.id === selectedNodeId;
              const isCenter = n.id === centerNodeId;
              const showLabel = showNodeLabels && (view.k >= labelThreshold || isSel || isCenter || n.id === hoverId || (focusSet && focusSet.has(n.id)));
              return (
                <g
                  key={n.id}
                  data-node-id={n.id}
                  className="obsg-node-hit"
                  transform={`translate(${p.x},${p.y})`}
                  onClick={(ev) => { ev.stopPropagation(); onNodeClick?.(n); }}
                  onDoubleClick={(ev) => { ev.stopPropagation(); onNodeDoubleClick?.(n); }}
                  onPointerEnter={() => setHoverId(n.id)}
                  onPointerLeave={() => setHoverId((h) => (h === n.id ? null : h))}
                  role="button"
                  tabIndex={0}
                  aria-label={`${n.title || n.label}`}
                  onKeyDown={(ev) => { if (ev.key === 'Enter') onNodeClick?.(n); }}
                >
                  {(isSel || isCenter) && (
                    <circle r={r + 6} fill="none" stroke={isSel ? '#a5b4fc' : colorForNode(n.type)} strokeWidth={isSel ? 2.5 : 1.5} opacity={0.8} />
                  )}
                  <NodeShape shape={shapeForNode(n.type)} r={r} color={colorForNode(n.type)} dim={dim} />
                  {showLabel ? (
                    <text className={`obsg-node-label${dim ? ' is-dim' : ''}`} x={0} y={r + 12} textAnchor="middle">
                      {n.shortLabel || n.label}
                    </text>
                  ) : null}
                </g>
              );
            })}
          </g>
        </svg>
      )}
      {/* 배경 클릭 → 선택 해제 */}
      <div
        style={{ position: 'absolute', inset: 0, zIndex: -1 }}
        onClick={() => onBackgroundClick?.()}
        aria-hidden="true"
      />
    </div>
  );
});

export default KnowledgeGraphCanvas;
