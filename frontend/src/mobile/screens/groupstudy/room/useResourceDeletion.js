import { useState } from 'react';
import { groupService } from '../../../../services/api';
import { RESOURCE_KIND, runResourceDeletion } from '../resourceDeleteModel';

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

    const outcome = await runResourceDeletion({
      kind,
      resourceId,
      deleteRequest: (id) => DELETE_REQUEST[kind](groupId, id),
      removeFromList: listQuery.setData,
      reloadList: listQuery.reload,
    });

    setErrorMessage(outcome.errorMessage);
    setDeletingId(null);
  };

  return { deletingId, errorMessage, remove };
}
