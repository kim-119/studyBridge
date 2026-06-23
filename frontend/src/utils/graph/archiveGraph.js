// ─────────────────────────────────────────────────────────────────────────────
// 자료보관함 mindmap material → Obsidian 방(room) 메타 + 그래프 파서(단일 출처).
//  · 저장 payload(content_json) 또는 migration 으로 들어온 rawGraphJson 을 모두 안전 파싱.
//  · UI 에는 "마인드맵" 대신 "옵시디언"으로 표기하되, 내부 호환을 위해 mindmap 타입을 읽을 수 있다.
// ─────────────────────────────────────────────────────────────────────────────
import { sanitizeGraph } from './graphValidation';

const tryParse = (v) => {
  if (!v) return null;
  if (typeof v === 'object') return v;
  try { return JSON.parse(v); } catch { return null; }
};

/** material 이 옵시디언(그래프) 자료인지 판정. type==='obsidian' 또는 mindmap+obsidian_graph. */
export function isObsidianMaterial(m) {
  if (!m) return false;
  const type = String(m.materialType || m.type || '').toUpperCase();
  if (type === 'OBSIDIAN' || type === 'MINDMAP') return true;
  const payload = tryParse(m.contentJson);
  return payload?.viewType === 'obsidian_graph';
}

/** material → 방(room) 메타. 그래프 본문은 포함하지 않는다(목록 경량). */
export function roomFromMaterial(m) {
  const payload = tryParse(m.contentJson) || {};
  const tags = (m.keywords ? String(m.keywords).split(',') : [])
    .map((t) => t.trim()).filter(Boolean);
  return {
    id: m.materialId,
    title: m.title || '옵시디언 방',
    sourceType: payload.sourceType || 'multi_agent_chat',
    sourceId: payload.sourceId || null,
    nodeCount: Number(payload.nodeCount) || 0,
    edgeCount: Number(payload.edgeCount) || 0,
    tags,
    updatedAt: m.updatedAt || m.uploadedAt || null,
    createdAt: m.uploadedAt || null,
  };
}

/**
 * material(상세 응답) → 렌더 가능한 그래프. 실패 시 null(자동 legacy 금지 — 호출측이 오류 UI 처리).
 */
export function parseArchiveGraph(material) {
  const payload = tryParse(material?.contentJson);
  let raw = payload?.rawGraphJson ? (tryParse(payload.rawGraphJson) || payload.rawGraphJson) : null;
  if (!raw && material?.rawGraphJson) raw = tryParse(material.rawGraphJson) || material.rawGraphJson;
  if (!raw && payload && Array.isArray(payload.nodes)) raw = payload;
  if (!raw || !Array.isArray(raw.nodes)) return null;
  return sanitizeGraph(raw);
}
