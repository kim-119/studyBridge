// ─────────────────────────────────────────────────────────────────────────────
// PDF 로 오염되었을 수 있는 자료보관함 mindmap 데이터를 graph 로 복구한다.
//  · 운영 환경에 그런 항목이 없더라도, 들어오면 안전하게 mindmap 으로 정규화한다.
//  · migrationStatus: clean | migrated | needs_review.
// ─────────────────────────────────────────────────────────────────────────────
import { MINDMAP_VIEW_TYPE, MINDMAP_CONTENT_TYPE, MINDMAP_FILE_TYPE } from './graphTypes';
import { sanitizeGraph, validateGraph } from './graphValidation';

const looksLikeGraphJson = (raw) => {
  if (!raw || typeof raw !== 'string') return null;
  try {
    const obj = JSON.parse(raw);
    const g = obj?.rawGraphJson ? (typeof obj.rawGraphJson === 'string' ? JSON.parse(obj.rawGraphJson) : obj.rawGraphJson) : obj;
    if (g && Array.isArray(g.nodes) && Array.isArray(g.edges)) return g;
  } catch { /* not json */ }
  return null;
};

/**
 * 단일 archive item 을 검사해 mindmap 복구 결과를 돌려준다.
 * @param {object} item  { materialType, contentType, originalFileName, contentJson, title, sourceType }
 * @returns {{item:object, status:'clean'|'migrated'|'needs_review', changed:boolean}}
 */
export function migrateArchiveItem(item) {
  if (!item || typeof item !== 'object') return { item, status: 'clean', changed: false };

  const type = String(item.materialType || item.type || '').toUpperCase();
  const contentType = String(item.contentType || '').toLowerCase();
  const fileName = String(item.originalFileName || '').toLowerCase();
  const isPdfish = type === 'PDF' || contentType === 'application/pdf' || fileName.endsWith('.pdf');

  // 이미 mindmap 이면 통과.
  if (type === 'MINDMAP') return { item, status: 'clean', changed: false };
  if (!isPdfish) return { item, status: 'clean', changed: false };

  // PDF 처럼 보이지만 그래프 JSON 을 품고 있으면 복구.
  const graph = looksLikeGraphJson(item.contentJson);
  const titleHint = /mindmap|graph|마인드맵/i.test(String(item.title || ''));
  const sourceHint = String(item.sourceType || '').toLowerCase() === 'multi_agent_chat';

  if (graph) {
    const valid = validateGraph(graph);
    if (valid.ok || valid.errors.length === 0) {
      return {
        item: {
          ...item,
          materialType: 'MINDMAP',
          type: 'mindmap',
          viewType: MINDMAP_VIEW_TYPE,
          fileType: MINDMAP_FILE_TYPE,
          contentType: MINDMAP_CONTENT_TYPE,
          rawGraphJson: sanitizeGraph(graph),
          migrationStatus: 'migrated',
        },
        status: 'migrated',
        changed: true,
      };
    }
  }

  if (titleHint || sourceHint) {
    return { item: { ...item, migrationStatus: 'needs_review' }, status: 'needs_review', changed: true };
  }
  return { item, status: 'clean', changed: false };
}

/**
 * 목록 일괄 검사 로그.
 * @param {object[]} items
 * @returns {{migratedCount:number, needsReviewCount:number, skippedCount:number, items:object[]}}
 */
export function migrateArchiveList(items) {
  let migratedCount = 0;
  let needsReviewCount = 0;
  let skippedCount = 0;
  const out = (Array.isArray(items) ? items : []).map((it) => {
    const r = migrateArchiveItem(it);
    if (r.status === 'migrated') migratedCount += 1;
    else if (r.status === 'needs_review') needsReviewCount += 1;
    else skippedCount += 1;
    return r.item;
  });
  return { migratedCount, needsReviewCount, skippedCount, items: out };
}
