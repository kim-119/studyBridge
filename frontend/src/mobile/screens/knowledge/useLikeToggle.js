import { useCallback, useRef, useState } from 'react';
import { knowledgeService } from '../../../services/api';
import { describeApiError } from '../../data/useAsync';
import { likeStateOf, toggledLikeState } from './knowledgeModel';

export function useLikeToggle(updatePost) {
  const pendingIds = useRef(new Set());
  const [pendingCount, setPendingCount] = useState(0);
  const [errorMessage, setErrorMessage] = useState(null);

  const markPending = useCallback((blogId, isPending) => {
    if (isPending) pendingIds.current.add(blogId);
    else pendingIds.current.delete(blogId);
    setPendingCount(pendingIds.current.size);
  }, []);

  const requestToggle = useCallback(
    async (post) => {
      const blogId = post.blogId;
      if (pendingIds.current.has(blogId)) return;

      const previous = likeStateOf(post);
      markPending(blogId, true);
      setErrorMessage(null);
      updatePost(blogId, (current) => ({ ...current, ...toggledLikeState(previous) }));

      try {
        const response = await knowledgeService.toggleLike(blogId);
        if (response) updatePost(blogId, (current) => ({ ...current, ...likeStateOf(response) }));
      } catch (error) {
        updatePost(blogId, (current) => ({ ...current, ...previous }));
        setErrorMessage(`좋아요를 반영하지 못했습니다. ${describeApiError(error)}`);
      } finally {
        markPending(blogId, false);
      }
    },
    [markPending, updatePost]
  );

  const toggleLike = useCallback(
    (post) => {
      requestToggle(post);
    },
    [requestToggle]
  );

  const isPending = useCallback((blogId) => pendingCount > 0 && pendingIds.current.has(blogId), [pendingCount]);

  return { toggleLike, isPending, errorMessage };
}
