import { useState } from 'react';
import { groupService } from '../../../../services/api';
import { RESOURCE_KIND, describeDeleteFailure, shouldReloadAfterDeleteFailure } from '../resourceDeleteModel';

const DELETE_REQUEST = {
  [RESOURCE_KIND.MATERIAL]: (groupId, resourceId) => groupService.deleteGroupMaterial(groupId, resourceId),
  [RESOURCE_KIND.QUIZ]: (groupId, resourceId) => groupService.deleteGroupQuiz(groupId, resourceId),
};

export function useResourceDeletion(groupId, kind, listQuery) {
  const [deletingId, setDeletingId] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  const remove = async (resourceId) => {
    if (deletingId !== null) return;
    setDeletingId(resourceId);
    setErrorMessage(null);

    try {
      await DELETE_REQUEST[kind](groupId, resourceId);
      await listQuery.reload().catch(() => {});
    } catch (error) {
      setErrorMessage(describeDeleteFailure(error, kind));
      if (shouldReloadAfterDeleteFailure(error)) await listQuery.reload().catch(() => {});
    } finally {
      setDeletingId(null);
    }
  };

  return { deletingId, errorMessage, remove };
}
