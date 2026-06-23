import React, { useCallback, useMemo, useRef, useState } from 'react';
import KnowledgeGraphCanvas from './KnowledgeGraphCanvas';
import GraphToolbar from './GraphToolbar';
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
// Obsidian Graph 오케스트레이터. 마인드맵 생성 화면과 자료보관함 뷰어가 공유한다.
//  · rawGraph(graph) 를 받아 필터/레이아웃/검색/상세를 관리한다.
//  · PDF 저장/변환/Viewer 진입 경로는 존재하지 않는다.
// ─────────────────────────────────────────────────────────────────────────────
export default function ObsidianGraphView({ graph: rawGraph, title = '마인드맵', extraActions = null }) {
  const graph = useMemo(() => sanitizeGraph(rawGraph || { nodes: [], edges: [] }), [rawGraph]);
  const bigGraph = graph.nodes.length > 80;

  const [mode, setMode] = useState(bigGraph ? 'global' : 'local');
  const [depth, setDepth] = useState(2);
  const [filters, setFilters] = useState(DEFAULT_FILTERS);
  const [centerNodeId, setCenterNodeId] = useState(graph.centerNodeId || (graph.nodes[0] && graph.nodes[0].id));
  const [selected, setSelected] = useState(null);
  const [searchOpen, setSearchOpen] = useState(false);

  const canvasRef = useRef(null);

  const linkIndex = useMemo(() => buildLinkIndex(graph), [graph]);

  const visibleGraph = useMemo(
    () => computeVisibleGraph(graph, { mode, centerNodeId, depth, filters }),
    [graph, mode, centerNodeId, depth, filters],
  );

  const layout = useMemo(
    () => computeLayout(visibleGraph, { centerNodeId }),
    [visibleGraph, centerNodeId],
  );

  const presentTypes = useMemo(
    () => Array.from(new Set(visibleGraph.nodes.map((n) => n.type))),
    [visibleGraph.nodes],
  );

  const toggleFilter = useCallback((key) => {
    setFilters((f) => ({ ...f, [key]: !f[key] }));
  }, []);

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

  const exportMd = useCallback(() => {
    downloadObsidianMarkdown(graph, { title });
  }, [graph, title]);

  const exportCanvas = useCallback(() => {
    computeLayout(graph, { centerNodeId }); // 전체 그래프 좌표 보장
    downloadJsonCanvas(graph, { title });
  }, [graph, centerNodeId, title]);

  // ESC: 선택/검색 닫기.
  const onKeyDown = useCallback((e) => {
    if (e.key === 'Escape') { setSelected(null); setSearchOpen(false); }
  }, []);

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="obsg-root" onKeyDown={onKeyDown} tabIndex={-1}>
      <GraphToolbar
        mode={mode}
        onSetMode={setMode}
        onFit={() => canvasRef.current?.fitView?.()}
        onCenterQuestion={centerQuestion}
        onToggleSearch={() => setSearchOpen((v) => !v)}
        searchOpen={searchOpen}
        filters={filters}
        onToggleFilter={toggleFilter}
        depth={depth}
        onSetDepth={setDepth}
        onExportMarkdown={exportMd}
        onExportCanvas={exportCanvas}
        extraActions={extraActions}
      />

      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        <KnowledgeGraphCanvas
          ref={canvasRef}
          graph={visibleGraph}
          positions={layout.positions}
          bounds={layout.bounds}
          selectedNodeId={selected?.id}
          centerNodeId={centerNodeId}
          neighbors={linkIndex.neighbors}
          showNodeLabels
          onNodeClick={(n) => setSelected(n)}
          onNodeDoubleClick={handleCenterNode}
          onBackgroundClick={() => setSelected(null)}
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

        <div className="obsg-stats">
          {mode === 'local' ? 'Local' : 'Global'} · 노드 {visibleGraph.nodes.length}/{graph.nodes.length} · 연결 {visibleGraph.edges.length}
        </div>

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
