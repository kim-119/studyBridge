export const MATERIAL_KIND = {
  DOCUMENT: 'document',
  PLANNER: 'planner',
  STUDY_JOURNAL: 'study-journal',
  MINDMAP: 'mindmap',
  REVIEW_NOTE: 'review-note',
};

export const REVIEW_NOTE_CONTEXT = 'review-note';

export function materialKindOf(material) {
  const type = String(material?.materialType || '').toUpperCase();

  if (type === 'PLANNER' || material?.plannerId != null) return MATERIAL_KIND.PLANNER;
  if (type === 'STUDY_LOG') return MATERIAL_KIND.STUDY_JOURNAL;
  if (type === 'MINDMAP') return MATERIAL_KIND.MINDMAP;
  if (type === 'REVIEW_NOTE') return MATERIAL_KIND.REVIEW_NOTE;
  return MATERIAL_KIND.DOCUMENT;
}

export function isDocxMaterial(material) {
  return String(material?.originalFileName || '').toLowerCase().endsWith('.docx');
}

export function materialDetailPath(materialId) {
  return `/archive/${materialId}`;
}

export function reviewNoteMaterialPath(materialId) {
  return `/archive/${materialId}?context=${REVIEW_NOTE_CONTEXT}`;
}

export function reviewNotePath(reviewNoteId) {
  return `/review-notes/${reviewNoteId}`;
}

export function findReviewNoteForMaterial(reviewNotes, materialId) {
  const target = String(materialId);
  return (Array.isArray(reviewNotes) ? reviewNotes : []).find(
    (note) => String(note.archiveMaterialId ?? '') === target
  );
}
