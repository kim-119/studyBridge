import { useCallback, useEffect, useRef, useState } from 'react';
import { applyGroupAiFrame, buildGroupAiRequestBody, captureConversationState } from './groupAiModel';
import { describeGroupAiError, streamGroupAiChat } from './groupAiStream';

function createRequestId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function useGroupAiChat(groupId, { displayName, historyMessages }) {
  const [liveMessages, setLiveMessages] = useState([]);
  const [isStreaming, setStreaming] = useState(false);
  const activeRequestRef = useRef(null);
  const abortRef = useRef(null);
  const conversationStateRef = useRef({});

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const appendForActiveRequest = useCallback((requestId, update) => {
    setLiveMessages((previous) => (activeRequestRef.current === requestId ? update(previous) : previous));
  }, []);

  const send = useCallback(
    async (question) => {
      const message = question.trim();
      if (!message || activeRequestRef.current) return;

      const requestId = createRequestId();
      const controller = new AbortController();
      activeRequestRef.current = requestId;
      abortRef.current = controller;
      setStreaming(true);
      setLiveMessages((previous) => [
        ...previous,
        { id: `user-${requestId}`, senderName: displayName, content: message, isUser: true },
      ]);

      try {
        await streamGroupAiChat(
          groupId,
          buildGroupAiRequestBody(message, conversationStateRef.current),
          {
            signal: controller.signal,
            onFrame: (frame) => {
              conversationStateRef.current = captureConversationState(conversationStateRef.current, frame.parsed);
              appendForActiveRequest(requestId, (previous) => applyGroupAiFrame(previous, frame, requestId));
            },
          }
        );
      } catch (error) {
        if (error?.name !== 'AbortError') {
          appendForActiveRequest(requestId, (previous) => [
            ...previous,
            {
              id: `error-${requestId}`,
              senderName: 'System',
              content: describeGroupAiError(error),
              isUser: false,
              isError: true,
            },
          ]);
        }
      } finally {
        if (activeRequestRef.current === requestId) {
          activeRequestRef.current = null;
          abortRef.current = null;
          setStreaming(false);
        }
      }
    },
    [appendForActiveRequest, displayName, groupId]
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    activeRequestRef.current = null;
    abortRef.current = null;
    setStreaming(false);
  }, []);

  return {
    messages: [...(historyMessages || []), ...liveMessages],
    isStreaming,
    send,
    stop,
  };
}
