import { computeLayout } from '../../../utils/graph/graphLayout';
import { generateJsonCanvas } from '../../../utils/graph/jsonCanvasExport';
import { buildObsidianMarkdown } from '../../../utils/graph/obsidianMarkdownExport';
import { MINDMAP_CONTENT_TYPE, MINDMAP_FILE_TYPE, MINDMAP_VIEW_TYPE } from '../../../utils/graph/graphTypes';

export function mindmapTitleOf(question) {
  const trimmed = String(question || '').trim();
  return trimmed ? `마인드맵 - ${trimmed.slice(0, 40)}` : '교수 답변 마인드맵';
}

export function buildMindmapArchivePayload(graph, question) {
  const title = mindmapTitleOf(question);
  computeLayout(graph, { centerNodeId: graph.centerNodeId });

  return {
    title,
    type: 'mindmap',
    viewType: MINDMAP_VIEW_TYPE,
    fileType: MINDMAP_FILE_TYPE,
    contentType: MINDMAP_CONTENT_TYPE,
    sourceType: 'multi_agent_chat',
    sourceId: String(graph.centerNodeId || 'session'),
    rawGraphJson: {
      nodes: graph.nodes,
      edges: graph.edges,
      centerNodeId: graph.centerNodeId,
      stats: graph.stats,
      semanticStatus: graph.semanticStatus || null,
    },
    obsidianMarkdown: buildObsidianMarkdown(graph, { title }),
    canvasJson: generateJsonCanvas(graph),
    nodeCount: graph.stats.nodeCount,
    edgeCount: graph.stats.edgeCount,
    tags: ['StudyBridge', 'mindmap'],
  };
}
