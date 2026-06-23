// ─────────────────────────────────────────────────────────────────────────────
// 그래프 저장/렌더 전 구조 검증. mindmap 이 PDF 로 새는 것도 여기서 막는다.
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES, MINDMAP_CONTENT_TYPE, MINDMAP_FILE_TYPE } from './graphTypes';

/**
 * rawGraph 구조 검증.
 * @param {{nodes?:any[], edges?:any[], centerNodeId?:string}} graph
 * @returns {{ok:boolean, errors:string[], warnings:string[]}}
 */
export function validateGraph(graph) {
  const errors = [];
  const warnings = [];
  if (!graph || typeof graph !== 'object') {
    return { ok: false, errors: ['graph 가 비어있습니다.'], warnings };
  }
  const nodes = Array.isArray(graph.nodes) ? graph.nodes : null;
  const edges = Array.isArray(graph.edges) ? graph.edges : null;
  if (!nodes) errors.push('nodes 배열이 없습니다.');
  if (!edges) errors.push('edges 배열이 없습니다.');
  if (errors.length) return { ok: false, errors, warnings };

  const ids = new Set();
  for (const n of nodes) {
    if (!n || !n.id) { errors.push('id 없는 노드'); continue; }
    if (ids.has(n.id)) errors.push(`중복 노드 id: ${n.id}`);
    ids.add(n.id);
  }
  for (const e of edges) {
    if (!e || !e.from || !e.to) { warnings.push('from/to 없는 간선 제거 대상'); continue; }
    if (!ids.has(e.from) || !ids.has(e.to)) warnings.push(`참조 오류 간선: ${e.id || `${e.from}->${e.to}`}`);
  }
  if (graph.centerNodeId && !ids.has(graph.centerNodeId)) errors.push('centerNodeId 가 노드에 없습니다.');
  const hasQuestion = nodes.some((n) => n.type === NODE_TYPES.QUESTION);
  if (!hasQuestion) warnings.push('question 노드가 없습니다.');

  return { ok: errors.length === 0, errors, warnings };
}

/**
 * 자료보관함 저장 메타가 mindmap 규약(PDF 금지)을 지키는지 검증.
 * @param {{contentType?:string, fileType?:string, type?:string}} meta
 * @returns {{ok:boolean, errors:string[]}}
 */
export function validateMindmapArchiveMeta(meta) {
  const errors = [];
  const ct = String(meta?.contentType || '').toLowerCase();
  const ft = String(meta?.fileType || '').toLowerCase();
  if (ct === 'application/pdf') errors.push('mindmap contentType 이 application/pdf 입니다.');
  if (ft === 'pdf') errors.push('mindmap fileType 이 pdf 입니다.');
  if (meta?.contentType && meta.contentType !== MINDMAP_CONTENT_TYPE) {
    errors.push(`contentType 이 ${MINDMAP_CONTENT_TYPE} 가 아닙니다.`);
  }
  if (meta?.fileType && meta.fileType !== MINDMAP_FILE_TYPE) {
    errors.push(`fileType 이 ${MINDMAP_FILE_TYPE} 가 아닙니다.`);
  }
  return { ok: errors.length === 0, errors };
}

/** 잘못된(참조 깨진) 간선을 제거한 그래프를 돌려준다(렌더 방어). */
export function sanitizeGraph(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes : [];
  const ids = new Set(nodes.map((n) => n.id));
  const edges = (Array.isArray(graph?.edges) ? graph.edges : []).filter(
    (e) => e && e.from && e.to && ids.has(e.from) && ids.has(e.to),
  );
  return { ...graph, nodes, edges };
}
