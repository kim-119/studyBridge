import { quizIdOf } from './quizGenerationModel.js';

export const RESOURCE_KIND = {
  MATERIAL: 'material',
  QUIZ: 'quiz',
};

const FAILURE_FALLBACK = {
  [RESOURCE_KIND.MATERIAL]: '자료 삭제에 실패했습니다. 잠시 후 다시 시도해주세요.',
  [RESOURCE_KIND.QUIZ]: '퀴즈 삭제에 실패했습니다. 잠시 후 다시 시도해주세요.',
};

export const DELETE_CONFIRM_MESSAGE = {
  [RESOURCE_KIND.MATERIAL]: '이 자료를 삭제할까요? 파일도 함께 삭제되며 되돌릴 수 없습니다. 이미 생성된 퀴즈는 남습니다.',
  [RESOURCE_KIND.QUIZ]: '이 퀴즈를 삭제할까요? 완료된 세션 기록도 함께 정리됩니다. 되돌릴 수 없습니다.',
};

export function describeDeleteFailure(error, kind) {
  const status = error?.response?.status;
  const serverMessage = error?.response?.data?.message;

  if (status === 403) return '방장만 삭제할 수 있습니다.';
  if (status === 404) return '이미 삭제되었거나 이 방의 항목이 아닙니다.';
  if (status === 409) return serverMessage || '진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다.';
  return serverMessage || FAILURE_FALLBACK[kind];
}

export function shouldReloadAfterDeleteFailure(error) {
  return error?.response?.status === 404;
}

const RESOURCE_ID_OF = {
  [RESOURCE_KIND.MATERIAL]: (material) => material?.id,
  [RESOURCE_KIND.QUIZ]: quizIdOf,
};

export function resourceIdOf(kind, resource) {
  return RESOURCE_ID_OF[kind](resource);
}

export function withoutResource(list, kind, resourceId) {
  if (!Array.isArray(list)) return list;
  return list.filter((resource) => String(resourceIdOf(kind, resource)) !== String(resourceId));
}

export async function runResourceDeletion({ kind, resourceId, deleteRequest, removeFromList, reloadList }) {
  try {
    await deleteRequest(resourceId);
  } catch (error) {
    if (shouldReloadAfterDeleteFailure(error)) await reloadList().catch(() => {});
    return { ok: false, errorMessage: describeDeleteFailure(error, kind) };
  }

  removeFromList((list) => withoutResource(list, kind, resourceId));
  reloadList().catch(() => {});
  return { ok: true, errorMessage: null };
}
