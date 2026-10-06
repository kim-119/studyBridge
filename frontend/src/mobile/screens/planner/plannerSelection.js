export const EMPTY_SELECTION = Object.freeze({ isSelecting: false, selectedIds: [] });

export function startSelecting() {
  return { isSelecting: true, selectedIds: [] };
}

export function toggleSelected(selection, plannerId) {
  const isSelected = selection.selectedIds.includes(plannerId);
  return {
    ...selection,
    selectedIds: isSelected
      ? selection.selectedIds.filter((id) => id !== plannerId)
      : [...selection.selectedIds, plannerId],
  };
}

export function isAllSelected(selection, visibleIds) {
  return visibleIds.length > 0 && visibleIds.every((id) => selection.selectedIds.includes(id));
}

export function toggleSelectAll(selection, visibleIds) {
  return { ...selection, selectedIds: isAllSelected(selection, visibleIds) ? [] : [...visibleIds] };
}

export function pruneSelection(selection, visibleIds) {
  const kept = selection.selectedIds.filter((id) => visibleIds.includes(id));
  if (kept.length === selection.selectedIds.length) return selection;
  return { ...selection, selectedIds: kept };
}

export function bulkDeleteConfirmMessage(count) {
  return `선택한 플래너 ${count}개를 삭제할까요? 연결된 일정도 함께 정리되며 되돌릴 수 없습니다.`;
}

function failureMessageOf(error) {
  return error?.response?.data?.message || '선택한 플래너를 삭제하지 못했습니다. 잠시 후 다시 시도해주세요.';
}

export async function runBulkDelete({ plannerIds, bulkDelete }) {
  if (plannerIds.length === 0) return { ok: false, deletedIds: [], message: '삭제할 플래너를 선택해주세요.' };

  try {
    const response = await bulkDelete(plannerIds);
    if (response?.success === false) {
      return { ok: false, deletedIds: [], message: response.message || failureMessageOf(null) };
    }
    const deletedCount = response?.deletedCount ?? plannerIds.length;
    return {
      ok: true,
      deletedIds: [...plannerIds],
      message: response?.message || `${deletedCount}개의 플래너를 삭제했습니다.`,
    };
  } catch (error) {
    return { ok: false, deletedIds: [], message: failureMessageOf(error) };
  }
}

export function withoutPlanners(planners, deletedIds) {
  if (!Array.isArray(planners)) return planners;
  const deleted = new Set(deletedIds.map(String));
  return planners.filter((planner) => !deleted.has(String(planner.id)));
}
