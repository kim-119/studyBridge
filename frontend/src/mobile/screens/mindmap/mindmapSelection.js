import { EDGE_TYPES, relationLabelForEdgeType } from '../../../utils/graph/graphTypes.js';

export const EMPHASIS = {
  NORMAL: 'normal',
  SELECTED: 'selected',
  CONNECTED: 'connected',
  DIMMED: 'dimmed',
};

export function relationLabelOf(edge) {
  const type = edge?.relationRole || edge?.type;
  const explicitLabel = String(edge?.displayLabel || '').trim();
  if (explicitLabel) return explicitLabel;
  if (type === EDGE_TYPES.SEMANTIC_RELATION) return String(edge?.label || '').trim() || relationLabelForEdgeType(type);
  return relationLabelForEdgeType(type);
}

function endpointId(endpoint) {
  return endpoint && typeof endpoint === 'object' ? endpoint.id : endpoint;
}

export function neighborhoodOf(view, selectedNodeId) {
  const empty = { selectedNodeId: null, nodeIds: new Set(), edgeIds: new Set(), relations: [] };
  if (!view || selectedNodeId == null) return empty;

  const nodeById = new Map(view.nodes.map((node) => [node.id, node]));
  if (!nodeById.has(selectedNodeId)) return empty;

  const nodeIds = new Set([selectedNodeId]);
  const edgeIds = new Set();
  const relations = [];

  view.edges.forEach((edge) => {
    const fromId = endpointId(edge.from);
    const toId = endpointId(edge.to);
    if (fromId !== selectedNodeId && toId !== selectedNodeId) return;

    const isOutgoing = fromId === selectedNodeId;
    const neighbor = nodeById.get(isOutgoing ? toId : fromId);
    if (!neighbor) return;

    nodeIds.add(neighbor.id);
    edgeIds.add(edge.id);
    relations.push({
      edgeId: edge.id,
      direction: isOutgoing ? 'outgoing' : 'incoming',
      label: edge.relationLabel || relationLabelOf(edge),
      neighbor,
    });
  });

  return { selectedNodeId, nodeIds, edgeIds, relations };
}

export function nodeEmphasis(neighborhood, nodeId) {
  if (neighborhood.selectedNodeId == null) return EMPHASIS.NORMAL;
  if (nodeId === neighborhood.selectedNodeId) return EMPHASIS.SELECTED;
  return neighborhood.nodeIds.has(nodeId) ? EMPHASIS.CONNECTED : EMPHASIS.DIMMED;
}

export function edgeEmphasis(neighborhood, edgeId) {
  if (neighborhood.selectedNodeId == null) return EMPHASIS.NORMAL;
  return neighborhood.edgeIds.has(edgeId) ? EMPHASIS.CONNECTED : EMPHASIS.DIMMED;
}

const RELATION_VIEW_MIN_SPAN = 240;

function expandToMinimumSpan(min, max) {
  const missing = RELATION_VIEW_MIN_SPAN - (max - min);
  if (missing <= 0) return [min, max];
  return [min - missing / 2, max + missing / 2];
}

function boundsOfNodes(nodes) {
  const xs = nodes.map((node) => node.x);
  const ys = nodes.map((node) => node.y);
  const [minX, maxX] = expandToMinimumSpan(Math.min(...xs), Math.max(...xs));
  const [minY, maxY] = expandToMinimumSpan(Math.min(...ys), Math.max(...ys));
  return { minX, minY, maxX, maxY };
}

function touchesNode(edge, nodeId) {
  return endpointId(edge.from) === nodeId || endpointId(edge.to) === nodeId;
}

export function canShowRelationOnly(neighborhood) {
  return neighborhood.selectedNodeId != null;
}

export function visibleGraphOf(view, neighborhood, relationOnly) {
  if (!view || !relationOnly || !canShowRelationOnly(neighborhood)) return view;

  const selectedNodeId = neighborhood.selectedNodeId;
  const edges = view.edges.filter((edge) => touchesNode(edge, selectedNodeId));
  const visibleNodeIds = new Set([selectedNodeId]);
  edges.forEach((edge) => {
    visibleNodeIds.add(endpointId(edge.from));
    visibleNodeIds.add(endpointId(edge.to));
  });
  const nodes = view.nodes.filter((node) => visibleNodeIds.has(node.id));

  return { ...view, nodes, edges, bounds: boundsOfNodes(nodes) };
}
