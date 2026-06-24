import React, { useCallback, useMemo, useRef, useState } from 'react';
import KnowledgeGraphCanvas from './KnowledgeGraphCanvas';
import GraphToolbar from './GraphToolbar';
import GraphSettingsPanel from './GraphSettingsPanel';
import GraphNodeDetailPanel from './GraphNodeDetailPanel';
import GraphSearchPanel from './GraphSearchPanel';
import GraphLegend from './GraphLegend';
import { sanitizeGraph } from '../../utils/graph/graphValidation';
import { buildLinkIndex } from '../../utils/graph/graphBacklinks';
import { computeVisibleGraph, DEFAULT_FILTERS } from '../../utils/graph/graphFilters';
import { computeLayout } from '../../utils/graph/graphLayout';
import { downloadObsidianMarkdown, downloadJsonCanvas } from '../../utils/graph/graphExportActions';
import './obsidianGraph.css';

// ─────────────────────────────────────────────────────────────────────────────
// Obsidian Graph 오케스트레이터. 마인드맵 생성 화면과 자료보관함/옵시디언 뷰어가 공유한다.
//  · rawGraph(graph) → 필터/레이아웃/검색/상세 + Filters/Groups/Display/Forces 설정.
//  · 다크 캔버스 + 작은 점 노드 + 얇은 간선 + floating 툴바(Obsidian parity).
//  · PDF 저장/변환/Viewer 진입 경로는 존재하지 않는다.
// ─────────────────────────────────────────────────────────────────────────────
const DEFAULT_DISPLAY = Object.freeze({
  showArrows: true, showNodeLabels: true, showEdgeLabels: null, nodeScale: 1, linkThickness: 1, textFade: null,
});
const DEFAULT_FORCES = Object.freeze({ repel: 1, linkDistance: 1, center: 1 });

export default function ObsidianGraphView({ graph: rawGraph, title = '마인드맵', extraActions = null }) {
  const graph = useMemo(() => sanitizeGraph(rawGraph || { nodes: [], edges: [] }), [rawGraph]);
  const bigGraph = graph.nodes.length > 80;

  const [mode, setMode] = useState(bigGraph ? 'global' : 'local');
  const [depth, setDepth] = useState(2);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [centerNodeId, setCenterNodeId] = useState(graph.centerNodeId || (graph.nodes[0] && graph.nodes[0].id));
  const [selected, setSelected] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [zoomPct, setZoomPct] = useState(100);

  // 표시(Display)/힘(Forces) 설정. showEdgeLabels/textFade 가 null 이면 mode 기반 기본값을 쓴다.
  const [display, setDisplay] = useState(DEFAULT_DISPLAY);
  const [forces, setForces] = useState(DEFAULT_FORCES);

  const canvasRef = useRef(null);

  const linkIndex = useMemo(() => buildLinkIndex(graph), [graph]);

  const visibleGraph = useMemo(
    () => computeVisibleGraph(graph, { mode, centerNodeId, depth, filters }),
    [graph, mode, centerNodeId, depth, filters],
  );

  const baseLayout = useMemo(
    () => computeLayout(visibleGraph, { centerNodeId }),
    [visibleGraph, centerNodeId],
  );

  // Forces → 레이아웃 좌표를 중심 기준으로 spread 스케일(밀어내기/링크거리 평균, center 로 보정).
  const layout = useMemo(() => {
    const spread = ((forces.repel + forces.linkDistance) / 2) / Math.max(0.4, forces.center);
    if (Math.abs(spread - 1) < 0.001) return baseLayout;
    const b = baseLayout.bounds;
    const cx = (b.minX + b.maxX) / 2;
    const cy = (b.minY + b.maxY) / 2;
    const positions = new Map();
    baseLayout.positions.forEach((p, id) => {
      positions.set(id, { x: cx + (p.x - cx) * spread, y: cy + (p.y - cy) * spread });
    });
    const bounds = {
      minX: cx + (b.minX - cx) * spread, maxX: cx + (b.maxX - cx) * spread,
      minY: cy + (b.minY - cy) * spread, maxY: cy + (b.maxY - cy) * spread,
    };
    return { ...baseLayout, positions, bounds };
  }, [baseLayout, forces]);

  const presentTypes = useMemo(
    () => Array.from(new Set(visibleGraph.nodes.map((n) => n.type))),
    [visibleGraph.nodes],
  );

  // mode 기반 기본값 + 사용자 override.
  const edgeLabelsOn = display.showEdgeLabels == null ? (mode === 'local') : display.showEdgeLabels;
  const textFade = display.textFade == null
    ? (graph.nodes.length > 120 ? 1.1 : graph.nodes.length > 60 ? 0.7 : 0)
    : display.textFade;

  const toggleFilter = useCallback((key) => setFilters((f) => ({ ...f, [key]: !f[key] })), []);
  const setDisplayKey = useCallback((key, val) => setDisplay((d) => ({ ...d, [key]: val })), []);
  const setForcesKey = useCallback((key, val) => setForces((f) => ({ ...f, [key]: val })), []);

  const handleSelectNode = useCallback((node) => {
    setSelected(node);
    canvasRef.current?.centerOnNode?.(node.id);
  }, []);

  const handleCenterNode = useCallback((node) => {
    setCenterNodeId(node.id);
    setMode('local');
    setSelected(node);
  }, []);

  const centerQuestion = useCallback(() => {
    const qid = graph.centerNodeId || (graph.nodes.find((n) => n.type === 'question') || {}).id;
    if (qid) { setCenterNodeId(qid); setMode('local'); canvasRef.current?.centerOnNode?.(qid); }
  }, [graph]);

  const exportMd = useCallback(() => { downloadObsidianMarkdown(graph, { title }); }, [graph, title]);
  const exportCanvas = useCallback(() => {
    computeLayout(graph, { centerNodeId });
    downloadJsonCanvas(graph, { title });
  }, [graph, centerNodeId, title]);

  // 단축키: ESC 닫기, 0 fit, L/G mode, E 간선이름, F 검색.
  const onKeyDown = useCallback((e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    if (e.key === 'Escape') { setSelected(null); setSearchOpen(false); setSettingsOpen(false); return; }
    if ((e.key === 'f' || e.key === 'F') && (e.metaKey || e.ctrlKey)) { e.preventDefault(); setSearchOpen((v) => !v); return; }
    if (e.key === '0') { canvasRef.current?.fitView?.(); return; }
    if (e.key === 'l' || e.key === 'L') setMode('local');
    else if (e.key === 'g' || e.key === 'G') setMode('global');
    else if (e.key === 'e' || e.key === 'E') setDisplayKey('showEdgeLabels', !edgeLabelsOn);
  }, [edgeLabelsOn, setDisplayKey]);

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="obsg-root" onKeyDown={onKeyDown} tabIndex={-1}>
      <div className={`obsg-stage${settingsOpen ? ' has-settings' : ''}`}>
        <KnowledgeGraphCanvas
          ref={canvasRef}
          graph={visibleGraph}
          positions={layout.positions}
          bounds={layout.bounds}
          selectedNodeId={selected?.id}
          centerNodeId={centerNodeId}
          neighbors={linkIndex.neighbors}
          showNodeLabels={display.showNodeLabels}
          showEdgeLabels={edgeLabelsOn}
          showArrows={display.showArrows}
          nodeScale={display.nodeScale}
          linkThickness={display.linkThickness}
          labelThreshold={textFade}
          mode={mode}
          edgeLabelsAlwaysOn={display.showEdgeLabels === true}
          onZoomChange={setZoomPct}
          onNodeClick={(n) => setSelected(n)}
          onNodeDoubleClick={handleCenterNode}
          onBackgroundClick={() => setSelected(null)}
        />

        {/* floating 툴바(캔버스 위 오버레이) */}
        <GraphToolbar
          mode={mode}
          onSetMode={setMode}
          onFit={() => canvasRef.current?.fitView?.()}
          onCenterQuestion={centerQuestion}
          onToggleSearch={() => setSearchOpen((v) => !v)}
          searchOpen={searchOpen}
          depth={depth}
          onSetDepth={setDepth}
          showEdgeLabels={edgeLabelsOn}
          onToggleEdgeLabels={() => setDisplayKey('showEdgeLabels', !edgeLabelsOn)}
          settingsOpen={settingsOpen}
          onToggleSettings={() => setSettingsOpen((v) => !v)}
          onExportMarkdown={exportMd}
          onExportCanvas={exportCanvas}
          extraActions={extraActions}
        />

        {searchOpen && (
          <GraphSearchPanel
            nodes={graph.nodes}
            onPick={(n) => { handleSelectNode(n); setSearchOpen(false); }}
            onClose={() => setSearchOpen(false)}
          />
        )}

        <GraphLegend presentTypes={presentTypes} />

        <div className="obsg-zoom">
          <button type="button" onClick={() => canvasRef.current?.zoomBy?.(1.2)} aria-label="확대">＋</button>
          <button type="button" onClick={() => canvasRef.current?.zoomBy?.(0.83)} aria-label="축소">－</button>
        </div>

        {/* status bar */}
        <div className="obsg-stats">
          {mode === 'local' ? 'Local' : 'Global'} · 노드 {visibleGraph.nodes.length}/{graph.nodes.length} · 간선 {visibleGraph.edges.length}
          {selected ? ` · 선택: ${selected.shortLabel || selected.label}` : ''} · 줌 {zoomPct}%
        </div>

        {settingsOpen && (
          <GraphSettingsPanel
            graph={graph}
            filters={filters}
            onToggleFilter={toggleFilter}
            display={{ ...display, showEdgeLabels: edgeLabelsOn, textFade }}
            onDisplay={setDisplayKey}
            forces={forces}
            onForces={setForcesKey}
            onResetForces={() => setForces(DEFAULT_FORCES)}
            onClose={() => setSettingsOpen(false)}
          />
        )}

        {selected && (
          <GraphNodeDetailPanel
            node={selected}
            linkIndex={linkIndex}
            onSelectNode={handleSelectNode}
            onCenterNode={handleCenterNode}
            onClose={() => setSelected(null)}
          />
        )}
      </div>
    </div>
  );
}
