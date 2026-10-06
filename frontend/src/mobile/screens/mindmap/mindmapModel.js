import { EDGE_RELATION_LABEL, NODE_LABEL_KO, colorForNode, styleForEdge } from '../../../utils/graph/graphTypes';
import { validateGraph } from '../../../utils/graph/graphValidation';
import { computeLayout } from '../../../utils/graph/graphLayout';
import { relationLabelOf } from './mindmapSelection';
import { cleanNodeLabel } from './nodeLabel';

function toViewNode(node) {
  const type = node.type || 'concept';
  const title = cleanNodeLabel(node.title || node.label || node.name) || String(node.id);

  return {
    id: node.id,
    type,
    typeLabel: NODE_LABEL_KO[type] || type,
    title,
    label: cleanNodeLabel(node.displayLabel || node.shortLabel || node.label) || title,
    detail: node.detail || node.body || node.markdownBody || node.description || node.summary || '',
    depth: node.depth ?? 0,
    x: node.position?.x ?? 0,
    y: node.position?.y ?? 0,
    color: colorForNode(type),
  };
}

function toViewEdge(edge, index, positionOf) {
  const from = positionOf.get(edge.from);
  const to = positionOf.get(edge.to);
  if (!from || !to) return null;

  const type = edge.type || 'related_to';
  const style = styleForEdge(type);
  return {
    id: edge.id || `${edge.from}-${edge.to}-${index}`,
    type,
    from,
    to,
    relationLabel: cleanNodeLabel(relationLabelOf(edge)),
    color: style.color,
    dashed: style.dashed,
  };
}

export function buildMindmapView(graph, centerNodeId) {
  if (!graph) return null;

  const check = validateGraph(graph);
  if (!check.ok) return { error: check.errors?.[0] || '손상된 마인드맵 데이터' };

  const layout = computeLayout(graph, { centerNodeId: centerNodeId ?? graph.centerNodeId });
  const nodes = graph.nodes.map(toViewNode);
  const positionOf = new Map(nodes.map((node) => [node.id, node]));
  const edges = graph.edges.map((edge, index) => toViewEdge(edge, index, positionOf)).filter(Boolean);

  return {
    nodes,
    edges,
    bounds: layout.bounds,
    mode: layout.mode,
    depth: nodes.reduce((max, node) => Math.max(max, node.depth), 0),
  };
}

export function legendOf(view) {
  if (!view?.nodes) return { nodeTypes: [], edgeTypes: [] };

  const nodeTypes = Array.from(new Set(view.nodes.map((node) => node.type))).map((type) => ({
    type,
    label: NODE_LABEL_KO[type] || type,
    color: colorForNode(type),
  }));
  const edgeTypes = Array.from(new Set(view.edges.map((edge) => edge.type))).map((type) => ({
    type,
    label: EDGE_RELATION_LABEL[type] || type,
    color: styleForEdge(type).color,
    dashed: styleForEdge(type).dashed,
  }));

  return { nodeTypes, edgeTypes };
}

export function matchNodes(nodes, keyword) {
  const needle = String(keyword || '').trim().toLowerCase();
  if (!needle) return [];

  return nodes.filter(
    (node) =>
      node.label.toLowerCase().includes(needle) ||
      node.title.toLowerCase().includes(needle) ||
      node.detail.toLowerCase().includes(needle)
  );
}
