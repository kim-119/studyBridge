import { NODE_COLOR } from '../../../utils/graph/graphTypes';
import { sanitizeGraph, validateGraph } from '../../../utils/graph/graphValidation';
import { computeLayout } from '../../../utils/graph/graphLayout';

function tryParse(value) {
  if (!value) return null;
  if (typeof value === 'object') return value;

  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

/**
 * 마인드맵 자료(MaterialType.MINDMAP)에서 그래프를 꺼낸다.
 * 저장 경로가 여러 세대라 contentJson.rawGraphJson → rawGraphJson → contentJson 순으로 본다.
 */
export function parseMindmapGraph(material) {
  const payload = tryParse(material?.contentJson);

  let raw = payload?.rawGraphJson ? tryParse(payload.rawGraphJson) || payload.rawGraphJson : null;
  if (!raw && material?.rawGraphJson) raw = tryParse(material.rawGraphJson) || material.rawGraphJson;
  if (!raw && payload && Array.isArray(payload.nodes)) raw = payload;

  if (!raw || !Array.isArray(raw.nodes)) return null;
  return sanitizeGraph(raw);
}

export function buildMindmapView(graph, centerNodeId) {
  if (!graph) return null;

  const check = validateGraph(graph);
  if (!check.ok) return { error: check.errors?.[0] || '손상된 마인드맵 데이터' };

  const layout = computeLayout(graph, { centerNodeId });

  const nodes = graph.nodes.map((node) => ({
    id: node.id,
    label: node.label || node.title || node.name || String(node.id),
    type: node.type || 'concept',
    detail: node.detail || node.description || node.summary || '',
    depth: node.depth ?? 0,
    x: node.position?.x ?? 0,
    y: node.position?.y ?? 0,
    color: NODE_COLOR[node.type] || NODE_COLOR.concept || '#60C95A',
  }));

  const positionOf = new Map(nodes.map((node) => [node.id, node]));

  const edges = graph.edges
    .map((edge, index) => {
      const from = positionOf.get(edge.from);
      const to = positionOf.get(edge.to);
      if (!from || !to) return null;

      return { id: `${edge.from}-${edge.to}-${index}`, type: edge.type || 'related_to', from, to };
    })
    .filter(Boolean);

  return {
    nodes,
    edges,
    bounds: layout.bounds,
    mode: layout.mode,
    depth: nodes.reduce((max, node) => Math.max(max, node.depth), 0),
  };
}

export function matchNodes(nodes, keyword) {
  if (!keyword) return [];
  const needle = keyword.trim().toLowerCase();
  if (!needle) return [];

  return nodes.filter(
    (node) =>
      node.label.toLowerCase().includes(needle) || node.detail.toLowerCase().includes(needle)
  );
}
