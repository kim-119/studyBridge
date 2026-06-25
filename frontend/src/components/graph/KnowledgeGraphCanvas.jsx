import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState,
} from 'react';
import {
  styleForEdge, colorForNode, shapeForNode, NODE_TYPES,
  displayLabelForNode, displayLabelForEdge, glowForNode, edgeFlows,
} from '../../utils/graph/graphTypes';
import {
  computeLabelLayout, edgeLabelVisibleAtZoom, LABEL_PRIORITY,
} from '../../utils/graph/graphLabelLayout';
import { getDisplayLabel, getTooltipLabel } from '../../utils/graph/graphLabel';

// 노드 라벨 표시 텍스트: 선택 노드는 더 길게, 그 외는 타입별 grapheme 한도로 절단(한글/이모지 안전).
function nodeLabelText(node, isSel) {
  if (isSel) return getDisplayLabel(node.title || displayLabelForNode(node), { maxChars: 28 });
  return getDisplayLabel(displayLabelForNode(node), { type: node.type });
}

// zoom/pan 안정화 상수(spec 39~41).
const MIN_ZOOM = 0.15;
const MAX_ZOOM = 4.0;
const clampK = (k) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, k));
// 다음 viewport 가 모두 유한값이면 clamp 적용, 아니면 이전 값 유지(NaN/Infinity 차단).
const safeView = (next, prev) => (
  Number.isFinite(next.k) && Number.isFinite(next.x) && Number.isFinite(next.y)
    ? { k: clampK(next.k), x: next.x, y: next.y }
    : prev
);

// gradient/marker id 로 쓰기 위한 색상 → 안전 토큰.
const colorKey = (c) => String(c).replace(/[^a-z0-9]/gi, '');

// ─────────────────────────────────────────────────────────────────────────────
// 다크 캔버스 SVG 렌더러. pan/zoom + 노드/간선 + 선택/hover 강조.
//  · positions: Map<id,{x,y}> (graphLayout 결과, 논리 좌표).
//  · 부모는 visibleGraph(필터/LOD 적용된 노드·간선)와 positions 를 넘긴다.
//  · 시각 고도화(spec): 궤도 depth glow(2.5D), 곡선 간선, 등장/펄스/흐름 애니메이션,
//    타입 하이라이트(범례 hover), 발표 모드.
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
//  · fillOpacity 로 depth(궤도) 별 미세한 입체감을 준다.
function NodeShape({ shape, r, color, dim, fillOpacity = 1 }) {
  const opacity = dim ? 0.32 : fillOpacity;
  const common = {
    fill: color, opacity, stroke: 'rgba(8,11,24,0.9)', strokeWidth: 1.5,
  };
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
    mode = 'local', edgeLabelsAlwaysOn = false,
    highlightType = null, presentation = false,
    onZoomChange, onNodeClick, onNodeDoubleClick, onBackgroundClick,
  } = props;

  const wrapRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 520 });
  const [view, setView] = useState({ k: 1, x: 0, y: 0 });
  const [hoverId, setHoverId] = useState(null);
  const dragRef = useRef(null);

  // 컨테이너 크기 추적. 동일 크기면 setState 생략(ResizeObserver loop 방지, spec 51).
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return undefined;
    let raf = 0;
    const measure = () => {
      const w = el.clientWidth || 800;
      const h = el.clientHeight || 520;
      setSize((prev) => (prev.w === w && prev.h === h ? prev : { w, h }));
    };
    measure();
    let ro;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => {
        // rAF 안에서 갱신해 "ResizeObserver loop completed with undelivered notifications" 회피.
        if (raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(measure);
      });
      ro.observe(el);
    }
    return () => { if (raf) cancelAnimationFrame(raf); if (ro) ro.disconnect(); };
  }, []);

  // 오른쪽 상세 패널이 열리면 그만큼 우측 inset 을 빼고 가시영역 중앙에 맞춘다(spec 31·89).
  const rightInset = props.rightInset || 0;

  const fitView = useCallback(() => {
    const padding = 60;
    const usableW = Math.max(120, size.w - rightInset);
    const gw = Math.max(1, bounds.maxX - bounds.minX);
    const gh = Math.max(1, bounds.maxY - bounds.minY);
    const kRaw = Math.min((usableW - padding) / gw, (size.h - padding) / gh, 2.2);
    const k = clampK(kRaw > 0 && Number.isFinite(kRaw) ? kRaw : 1);
    const cx = (bounds.minX + bounds.maxX) / 2;
    const cy = (bounds.minY + bounds.maxY) / 2;
    // 가시영역(좌측 usableW)의 중앙을 그래프 중심으로.
    setView((v) => safeView({ k, x: usableW / 2 - cx * k, y: size.h / 2 - cy * k }, v));
  }, [bounds, size.w, size.h, rightInset]);

  // 그래프/크기 바뀌면 자동 fit.
  useEffect(() => { fitView(); }, [fitView, graph]);

  const centerOnNode = useCallback((id) => {
    const p = positions.get(id);
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
    const usableW = Math.max(120, size.w - rightInset);
    setView((v) => safeView({ ...v, x: usableW / 2 - p.x * v.k, y: size.h / 2 - p.y * v.k }, v));
  }, [positions, size.w, size.h, rightInset]);

  const zoomBy = useCallback((factor) => {
    setView((v) => {
      const k = clampK(v.k * factor);
      const cx = size.w / 2; const cy = size.h / 2;
      return safeView({ k, x: cx - ((cx - v.x) / v.k) * k, y: cy - ((cy - v.y) / v.k) * k }, v);
    });
  }, [size.w, size.h]);

  // 이상 상태 복구(spec 55): zoom=1, pan=0 으로 리셋 후 fit.
  const resetView = useCallback(() => {
    setHoverId(null);
    fitView();
  }, [fitView]);

  useImperativeHandle(ref, () => ({ fitView, centerOnNode, zoomBy, resetView }), [fitView, centerOnNode, zoomBy, resetView]);

  // pan.
  const onPointerDown = (e) => {
    if (e.target.closest('[data-node-id]')) return;
    dragRef.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
  };
  const onPointerMove = (e) => {
    if (!dragRef.current) return;
    const nx = dragRef.current.vx + (e.clientX - dragRef.current.x);
    const ny = dragRef.current.vy + (e.clientY - dragRef.current.y);
    setView((v) => safeView({ ...v, x: nx, y: ny }, v));
  };
  const endDrag = () => { dragRef.current = null; };

  // wheel zoom: rAF 로 coalesce 해 이벤트 폭주 시 setState 과다/렉 방지(spec 42).
  const wheelRaf = useRef(0);
  const wheelPending = useRef(null);
  const onWheel = (e) => {
    e.preventDefault();
    const rect = wrapRef.current?.getBoundingClientRect();
    const px = rect ? e.clientX - rect.left : size.w / 2;
    const py = rect ? e.clientY - rect.top : size.h / 2;
    wheelPending.current = { px, py, factor: e.deltaY < 0 ? 1.12 : 0.89 };
    if (wheelRaf.current) return;
    wheelRaf.current = requestAnimationFrame(() => {
      wheelRaf.current = 0;
      const w = wheelPending.current;
      wheelPending.current = null;
      if (!w) return;
      setView((v) => {
        const k = clampK(v.k * w.factor);
        return safeView({ k, x: w.px - ((w.px - v.x) / v.k) * k, y: w.py - ((w.py - v.y) / v.k) * k }, v);
      });
    });
  };
  // unmount 시 대기 중 rAF 취소(spec 52).
  useEffect(() => () => { if (wheelRaf.current) cancelAnimationFrame(wheelRaf.current); }, []);

  // ── 강조 상태: hover/선택 focus(이웃 포함) 또는 범례 타입 하이라이트 ──────────
  const focusId = hoverId || selectedNodeId;
  const focusSet = useMemo(() => {
    if (!focusId) return null;
    const s = new Set([focusId]);
    const nb = neighbors?.get(focusId);
    if (nb) nb.forEach((id) => s.add(id));
    return s;
  }, [focusId, neighbors]);

  // 범례 hover → 해당 타입만 강조(focus 가 없을 때만 적용).
  const typeHi = !focusSet && highlightType ? highlightType : null;
  const anyHi = !!focusSet || !!typeHi;
  const nodeActive = useCallback((n) => {
    if (focusSet) return focusSet.has(n.id);
    if (typeHi) return n.type === typeHi;
    return true;
  }, [focusSet, typeHi]);
  const edgeActive = useCallback((e) => {
    if (focusSet) return focusSet.has(e.from) && focusSet.has(e.to);
    if (typeHi) return e.type === typeHi;
    return true;
  }, [focusSet, typeHi]);

  const labelThreshold = labelThresholdProp != null
    ? labelThresholdProp
    : (graph.nodes.length > 120 ? 1.1 : graph.nodes.length > 60 ? 0.7 : 0);

  // present 색상(arrow marker + halo gradient defs 단일 생성).
  const edgeColors = useMemo(() => Array.from(new Set(graph.edges.map((e) => styleForEdge(e.type).color))), [graph.edges]);
  const haloColors = useMemo(() => {
    const s = new Set(['#a5b4fc']); // 선택 노드 glow(인디고)는 항상 포함.
    graph.nodes.forEach((n) => { if (glowForNode(n.type) > 0) s.add(colorForNode(n.type)); });
    return Array.from(s);
  }, [graph.nodes]);

  // id → depth(궤도 레벨) 조회맵. 간선 등장 stagger 에 재사용(O(E*N) find 회피).
  const depthById = useMemo(() => {
    const m = new Map();
    graph.nodes.forEach((n) => m.set(n.id, Math.min(4, n.depth || 0)));
    return m;
  }, [graph.nodes]);

  // 같은 두 노드 사이 다중 간선 곡률 index(겹침 회피, spec 4·다중관계).
  const pairIndex = useMemo(() => {
    const seen = new Map();
    const idx = new Map();
    graph.edges.forEach((e) => {
      const key = e.from < e.to ? `${e.from}|${e.to}` : `${e.to}|${e.from}`;
      const c = seen.get(key) || 0;
      idx.set(e.id, c);
      seen.set(key, c + 1);
    });
    return idx;
  }, [graph.edges]);

  // ── 라벨 충돌 회피 레이아웃(노드 라벨/간선 라벨/점/halo 가 안 겹치게) ──────────
  //  · 논리 좌표로 모든 박스를 계산 → priority 순 배치 → 충돌 시 법선 offset → 숨김.
  //  · zoom/mode/선택/hover 변화에만 재계산(useMemo). spec 1~20단계.
  const labelLayout = useMemo(() => {
    const k = view.k;
    const focus = hoverId || selectedNodeId;
    const fset = (() => {
      if (!focus) return null;
      const s = new Set([focus]);
      const nb = neighbors?.get(focus);
      if (nb) nb.forEach((id) => s.add(id));
      return s;
    })();

    const nodeInputs = [];
    graph.nodes.forEach((n) => {
      const p = positions.get(n.id);
      if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
      const r = nodeRadius(n, nodeScale);
      const isSel = n.id === selectedNodeId;
      const isCenter = n.id === centerNodeId;
      const isHover = n.id === hoverId;
      const inFocus = fset ? fset.has(n.id) : false;
      const showLabel = showNodeLabels
        && (k >= labelThreshold || isSel || isCenter || isHover || inFocus);
      let priority = LABEL_PRIORITY.NODE;
      if (isSel) priority = LABEL_PRIORITY.SELECTED_NODE;
      else if (isHover) priority = LABEL_PRIORITY.HOVERED_NODE;
      else if (n.type === NODE_TYPES.QUESTION || n.type === NODE_TYPES.AGENT) {
        priority = LABEL_PRIORITY.KEY_NODE;
      }
      nodeInputs.push({
        id: n.id,
        x: p.x,
        y: p.y,
        r,
        haloR: isSel ? r + 8 : isCenter ? r + 6 : 0,
        // semanticRole 기반 라벨(본문 스니펫 금지) + grapheme 절단. 렌더 텍스트와 동일해야 충돌 박스가 맞다.
        text: showLabel ? nodeLabelText(n, isSel) : '',
        showLabel,
        priority,
      });
    });

    const edgeInputs = [];
    graph.edges.forEach((e) => {
      const a = positions.get(e.from);
      const b = positions.get(e.to);
      // edge endpoint 누락/비정상 좌표면 라벨 skip(노드/간선 본체 렌더는 별도, spec 49·50).
      if (!a || !b) return;
      if (![a.x, a.y, b.x, b.y].every(Number.isFinite)) return;
      const isSelEdge = !!selectedNodeId && (e.from === selectedNodeId || e.to === selectedNodeId);
      const isHovEdge = !!hoverId && (e.from === hoverId || e.to === hoverId);
      const inFocus = fset ? (fset.has(e.from) && fset.has(e.to)) : false;
      const visible = edgeLabelVisibleAtZoom(
        { selected: isSelEdge, hovered: isHovEdge, focus: inFocus, oneHop: isSelEdge },
        k,
        { mode, edgeLabelsOn: showEdgeLabels, alwaysOn: edgeLabelsAlwaysOn },
      );
      const candidate = visible && (showEdgeLabels || inFocus || isSelEdge || isHovEdge);
      let priority = mode === 'global' ? LABEL_PRIORITY.GLOBAL_EDGE : LABEL_PRIORITY.LOCAL_EDGE;
      if (isSelEdge) priority = LABEL_PRIORITY.SELECTED_EDGE;
      else if (isHovEdge) priority = LABEL_PRIORITY.HOVERED_EDGE;
      edgeInputs.push({
        id: e.id,
        sx: a.x,
        sy: a.y,
        tx: b.x,
        ty: b.y,
        // relationRole 기반 [라벨] 형태(예: [답변]·[검증]·[반박]·[자료 출처]).
        text: `[${displayLabelForEdge(e)}]`,
        candidate,
        boosted: isSelEdge || isHovEdge,
        priority,
      });
    });

    return computeLabelLayout({
      nodes: nodeInputs,
      edges: edgeInputs,
      options: { circlePad: 4, rectPad: 4, nodeNodePad: 2 },
    });
  }, [
    graph, positions, view.k, selectedNodeId, centerNodeId, hoverId, neighbors,
    showNodeLabels, showEdgeLabels, labelThreshold, nodeScale, mode, edgeLabelsAlwaysOn,
  ]);

  // 줌 레벨을 부모(상태바)로 보고.
  useEffect(() => { onZoomChange?.(Math.round(view.k * 100)); }, [view.k, onZoomChange]);

  // 두 점 사이 path(다중 간선/강조 시 약간의 곡선, 단일은 직선 → 라벨 중점 정확도 유지).
  const edgePath = useCallback((a, b, pi) => {
    if (!pi) return `M${a.x},${a.y} L${b.x},${b.y}`;
    const mx = (a.x + b.x) / 2;
    const my = (a.y + b.y) / 2;
    const dx = b.x - a.x; const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len; const ny = dx / len;
    const curv = (pi % 2 ? 1 : -1) * Math.ceil(pi / 2) * 18;
    return `M${a.x},${a.y} Q${mx + nx * curv},${my + ny * curv} ${b.x},${b.y}`;
  }, []);

  return (
    <div
      ref={wrapRef}
      className={`obsg-canvas-wrap${dragRef.current ? ' is-panning' : ''}${presentation ? ' is-present' : ''}`}
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
              <marker key={c} id={`obsg-arrow-${colorKey(c)}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                <path d="M0 0 L10 5 L0 10 z" fill={c} />
              </marker>
            ))}
            {/* 노드 glow halo 용 radial gradient(색상별 1개 재사용 — per-node filter 회피). */}
            {haloColors.map((c) => (
              <radialGradient key={c} id={`obsg-halo-${colorKey(c)}`}>
                <stop offset="0%" stopColor={c} stopOpacity="0.55" />
                <stop offset="55%" stopColor={c} stopOpacity="0.16" />
                <stop offset="100%" stopColor={c} stopOpacity="0" />
              </radialGradient>
            ))}
          </defs>
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {/* 간선 */}
            {graph.edges.map((e) => {
              const a = positions.get(e.from);
              const b = positions.get(e.to);
              // source/target 누락·비정상 좌표 간선은 렌더 skip(앱 crash 금지, spec 49).
              if (!a || !b) return null;
              if (![a.x, a.y, b.x, b.y].every(Number.isFinite)) return null;
              const st = styleForEdge(e.type);
              const active = !anyHi || edgeActive(e);
              const flow = anyHi && active && edgeFlows(e.type);
              const pi = pairIndex.get(e.id) || 0;
              const baseOpacity = presentation ? 0.5 : 0.32;
              // 충돌 회피로 계산된 라벨 위치(center). hidden 이면 렌더 안 함.
              const placed = labelLayout.edgeLabels.get(e.id);
              const labelOn = placed && !placed.hidden;
              const cls = `obsg-edge obsg-edge-enter${flow ? ' obsg-edge-flow' : ''}`;
              return (
                <g key={e.id} style={{ '--obsg-d': `${(depthById.get(e.to) || 0) * 90}ms` }}>
                  <path
                    className={cls}
                    d={edgePath(a, b, pi)}
                    fill="none"
                    stroke={st.color}
                    strokeWidth={(active ? 1.8 : 1) * linkThickness}
                    strokeOpacity={anyHi ? (active ? 0.92 : 0.08) : baseOpacity}
                    strokeDasharray={!flow && st.dashed ? '5 4' : undefined}
                    strokeLinecap="round"
                    markerEnd={showArrows && st.directed ? `url(#obsg-arrow-${colorKey(st.color)})` : undefined}
                  />
                  {labelOn ? (
                    <foreignObject
                      x={placed.x - placed.w / 2}
                      y={placed.y - placed.h / 2}
                      width={placed.w}
                      height={placed.h}
                      style={{ overflow: 'visible', pointerEvents: 'none' }}
                    >
                      <div className="obsg-edge-pill"><span>{`[${displayLabelForEdge(e)}]`}</span></div>
                    </foreignObject>
                  ) : null}
                </g>
              );
            })}
            {/* 노드 */}
            {graph.nodes.map((n) => {
              const p = positions.get(n.id);
              if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) return null;
              const r = nodeRadius(n, nodeScale);
              const dim = anyHi && !nodeActive(n);
              const isSel = n.id === selectedNodeId;
              const isCenter = n.id === centerNodeId;
              const isHover = n.id === hoverId;
              const depth = Math.min(4, n.depth || 0);
              const color = colorForNode(n.type);
              const nodeLbl = labelLayout.nodeLabels.get(n.id);
              const showLabel = showNodeLabels
                && (view.k >= labelThreshold || isSel || isCenter || isHover || (focusSet && focusSet.has(n.id)))
                && !(nodeLbl && nodeLbl.hidden);

              // glow 강도: 타입 기본 + 선택/중심/hover boost, depth 가 멀수록 약화.
              let glow = glowForNode(n.type);
              if (isSel) glow = Math.max(glow, 1);
              else if (isCenter) glow = Math.max(glow, 0.85);
              else if (isHover) glow = Math.max(glow, 0.7);
              const depthF = 1 - Math.min(0.5, depth * 0.12);
              const haloOpacity = glow > 0 ? Math.min(0.9, glow * 0.5 * depthF) * (dim ? 0.2 : 1) : 0;
              const haloR = r * (1.9 + glow * 0.7);
              const haloColor = isSel ? '#a5b4fc' : color;
              // depth 가 멀수록 채움 약간 옅게(공간 깊이감), 강조 시 또렷하게.
              const fillOpacity = isSel || isCenter ? 1 : Math.max(0.78, 1 - depth * 0.05);

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
                  {/* 내부 vis 그룹: 등장/hover scale 애니메이션(외부 그룹 translate 보존). */}
                  <g
                    className={`obsg-node-vis obsg-node-enter${dim ? ' is-dim' : ''}`}
                    style={{ '--obsg-d': `${depth * 90}ms` }}
                  >
                    {haloOpacity > 0 ? (
                      <circle
                        className={`obsg-halo${isSel ? ' obsg-pulse' : ''}`}
                        r={haloR}
                        fill={`url(#obsg-halo-${colorKey(haloColor)})`}
                        opacity={haloOpacity}
                      />
                    ) : null}
                    {(isSel || isCenter) && (
                      <circle className={isSel ? 'obsg-sel-ring' : undefined} r={r + 6} fill="none" stroke={isSel ? '#c7d2fe' : color} strokeWidth={isSel ? 2.5 : 1.5} opacity={0.85} />
                    )}
                    <NodeShape shape={shapeForNode(n.type)} r={r} color={color} dim={dim} fillOpacity={fillOpacity} />
                    {showLabel ? (
                      <text
                        className={`obsg-node-label${dim ? ' is-dim' : ''}${isSel ? ' selected' : ''}`}
                        x={0}
                        y={r + 12}
                        textAnchor="middle"
                      >
                        {/* hover/touch 시 전체 title 툴팁(grapheme 정규화, spec 37). */}
                        <title>{getTooltipLabel(n.title || n.label)}</title>
                        {nodeLabelText(n, isSel)}
                      </text>
                    ) : null}
                  </g>
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
