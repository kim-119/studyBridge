import React, { useMemo, useState } from 'react';
import ObsidianGraphView from './ObsidianGraphView';
import LegacyMindMapView from './LegacyMindMapView';
import GraphErrorBoundary from './GraphErrorBoundary';
import { convertMindMapToObsidianGraph } from '../../utils/graph/mindmapToObsidianGraph';
import { buildObsidianMarkdown } from '../../utils/graph/obsidianMarkdownExport';
import { generateJsonCanvas } from '../../utils/graph/jsonCanvasExport';
import { computeLayout } from '../../utils/graph/graphLayout';
import {
  MINDMAP_VIEW_TYPE, MINDMAP_CONTENT_TYPE, MINDMAP_FILE_TYPE,
} from '../../utils/graph/graphTypes';

// ─────────────────────────────────────────────────────────────────────────────
// 마인드맵 생성 화면(StudyMate)의 기본 뷰. 기존 입력을 Obsidian Graph 로 변환한다.
//  · 기본 진입 = Obsidian Graph. 오류/데이터 부족 시 LegacyMindMapView 로 fallback.
//  · 저장은 자료보관함 graph(JSON)로만. PDF 저장 경로 없음.
// ─────────────────────────────────────────────────────────────────────────────
export default function ObsidianMindMapView({
  question, agents = [], messages = [], interactions = [],
  onSaveToArchive, saving = false, savedLabel,
}) {
  const [showLegacy, setShowLegacy] = useState(false);

  const graph = useMemo(
    () => convertMindMapToObsidianGraph({ question, agents, messages, interactions }),
    [question, agents, messages, interactions],
  );

  const title = useMemo(() => {
    const q = String(question || '').trim();
    return q ? `마인드맵 - ${q.slice(0, 40)}` : '교수 답변 마인드맵';
  }, [question]);

  const handleSave = () => {
    if (!onSaveToArchive || saving) return;
    // 저장 직전 전체 그래프 좌표 계산(Canvas export 좌표 보존).
    computeLayout(graph, { centerNodeId: graph.centerNodeId });
    const payload = {
      title,
      type: 'mindmap',
      viewType: MINDMAP_VIEW_TYPE,
      fileType: MINDMAP_FILE_TYPE,
      contentType: MINDMAP_CONTENT_TYPE,
      sourceType: 'multi_agent_chat',
      sourceId: String(graph.centerNodeId || 'session'),
      rawGraphJson: { nodes: graph.nodes, edges: graph.edges, centerNodeId: graph.centerNodeId, stats: graph.stats },
      obsidianMarkdown: buildObsidianMarkdown(graph, { title }),
      canvasJson: generateJsonCanvas(graph),
      nodeCount: graph.stats.nodeCount,
      edgeCount: graph.stats.edgeCount,
      tags: ['StudyBridge', 'mindmap'],
    };
    onSaveToArchive(payload);
  };

  if (showLegacy) {
    return (
      <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '6px 8px', background: '#111827' }}>
          <button type="button" className="obsg-btn" onClick={() => setShowLegacy(false)}>← Obsidian Graph 보기</button>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          <LegacyMindMapView question={question} agents={agents} messages={messages} interactions={interactions} />
        </div>
      </div>
    );
  }

  const extraActions = (
    <>
      {onSaveToArchive && (
        <button type="button" className="obsg-btn is-active" onClick={handleSave} disabled={saving}>
          {savedLabel || (saving ? '저장 중…' : '자료보관함에 저장')}
        </button>
      )}
      <button type="button" className="obsg-btn" onClick={() => setShowLegacy(true)}>Legacy 카드 보기</button>
    </>
  );

  return (
    <GraphErrorBoundary
      fallback={<LegacyMindMapView question={question} agents={agents} messages={messages} interactions={interactions} />}
    >
      <ObsidianGraphView graph={graph} title={title} extraActions={extraActions} />
    </GraphErrorBoundary>
  );
}
