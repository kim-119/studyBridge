import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { agentService } from '../../../services/api';
import { createCancelRegistry } from '../../../utils/studymate/streamCancelRegistry';
import { STREAM_PHASES } from '../../../utils/studymate/streamStateMachine';
import { createTurnGuard } from '../../../utils/studymate/turnGuard';
import {
  appendUnique,
  closePendingMessages,
  historyToMessages,
  isUserMessage,
  lastRealMessage,
  mergeLiveMessages,
  reconcileHistory,
  removeFailedTurn,
  replaceTurnMessages,
} from './chatMessages';
import {
  buildStreamPayload,
  captureConversationState,
  consumeSimulationChoice,
  nextRegenerateAttempt,
  resolveActiveLearningMode,
  resolveTurnTarget,
  sanitizeQuestion,
  selectSimulationChoice,
} from './streamPayload';
import { createTurnState } from './turnAccumulator';
import { runStreamTurn } from './streamTurn';

const DUPLICATE_SEND_WINDOW_MS = 1500;
const POST_STREAM_RECONCILE_MS = 1500;
const PENDING_TURN_REFRESH_MS = [8000, 20000, 45000];
const ACTIVE_PHASES = new Set([STREAM_PHASES.CONNECTING, STREAM_PHASES.STREAMING, STREAM_PHASES.FINALIZING]);

function isDuplicateSend(lastSend, text) {
  return Boolean(lastSend) && lastSend.text === text && Date.now() - lastSend.at < DUPLICATE_SEND_WINDOW_MS;
}

function useLatest(value) {
  const ref = useRef(value);
  useEffect(() => {
    ref.current = value;
  }, [value]);
  return ref;
}

function useTimers() {
  const timers = useRef([]);
  const schedule = useCallback((callback, delay) => {
    timers.current.push(setTimeout(callback, delay));
  }, []);
  const clearAll = useCallback(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  }, []);
  useEffect(() => clearAll, [clearAll]);
  return useMemo(() => ({ schedule, clearAll }), [schedule, clearAll]);
}

export function useStudyMateStream({ roomId, room, stage }) {
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState(STREAM_PHASES.IDLE);
  const [followUps, setFollowUps] = useState([]);
  const [syncError, setSyncError] = useState(null);
  const roomRef = useLatest(room);
  const stageRef = useLatest(stage);
  const conversationRef = useRef({});
  const regenerateRef = useRef(null);
  const pinnedAgentRef = useRef(null);
  const lastSendRef = useRef(null);
  const latestRequestRef = useRef(null);
  const cancelRegistry = useMemo(() => createCancelRegistry(), []);
  const turnGuard = useMemo(() => createTurnGuard(), []);
  const timers = useTimers();

  const isStreaming = ACTIVE_PHASES.has(phase);
  const isStreamingRef = useLatest(isStreaming);

  const reconcileFromServer = useCallback(async () => {
    try {
      const history = await agentService.getChatHistory(null, roomId);
      setMessages((previous) => reconcileHistory(historyToMessages(history), previous));
      setSyncError(null);
    } catch (error) {
      setSyncError(error);
    }
  }, [roomId]);

  const schedulePendingTurnRefresh = useCallback(
    (list) => {
      if (!isUserMessage(lastRealMessage(list))) return;
      PENDING_TURN_REFRESH_MS.forEach((delay) => {
        timers.schedule(() => {
          if (!isStreamingRef.current) reconcileFromServer();
        }, delay);
      });
    },
    [isStreamingRef, reconcileFromServer, timers]
  );

  const loadHistory = useCallback(
    (history) => {
      const list = historyToMessages(history);
      setMessages((previous) => mergeLiveMessages(list, previous));
      schedulePendingTurnRefresh(list);
    },
    [schedulePendingTurnRefresh]
  );

  const render = useCallback((parentId, turnMessages) => {
    setMessages((previous) => replaceTurnMessages(previous, parentId, turnMessages));
  }, []);

  const send = useCallback(
    async (rawText, { retryOf } = {}) => {
      const text = sanitizeQuestion(rawText);
      const currentRoom = roomRef.current;
      const currentStage = stageRef.current;
      if (!text || !currentRoom || isDuplicateSend(lastSendRef.current, text)) return;

      cancelRegistry.cancel(roomId, 'new_question');
      lastSendRef.current = { text, at: Date.now() };
      setFollowUps([]);
      timers.clearAll();
      if (retryOf) setMessages((previous) => removeFailedTurn(previous, retryOf));

      const turnToken = turnGuard.begin(roomId);
      const requestId = turnToken.requestId;
      latestRequestRef.current = requestId;

      const roomAgents = currentRoom.agents || [];
      const mode = resolveActiveLearningMode(currentRoom.learningMode, text);
      const target = resolveTurnTarget(text, roomAgents, pinnedAgentRef.current);
      const regenerateAttempt = nextRegenerateAttempt(regenerateRef.current, text);
      const payload = buildStreamPayload({
        message: text,
        room: currentRoom,
        mode,
        target,
        conversationState: conversationRef.current,
        requestId,
        regenerateAttempt,
      });
      conversationRef.current = consumeSimulationChoice(conversationRef.current, mode);

      setMessages((previous) => [...previous, { id: requestId, sender: 'USER', content: text, createdAt: new Date().toISOString() }]);
      currentStage.beginTurn({ mode, target, message: text });
      currentStage.setTurnRequestId(requestId);

      const outcome = await runStreamTurn({
        roomId,
        payload,
        turnToken,
        cancelRegistry,
        stage: currentStage,
        retryMessage: text,
        turn: createTurnState({ parentId: requestId, requestId, roomAgents, target, mode, fallbackAgentName: currentRoom.name }),
        onPhase: setPhase,
        render: (turnMessages) => render(requestId, turnMessages),
        appendNotice: (notice) => setMessages((previous) => appendUnique(previous, notice)),
        closePending: (parentId) => setMessages((previous) => closePendingMessages(previous, parentId)),
        setFollowUps,
        captureState: (data) => {
          conversationRef.current = captureConversationState(conversationRef.current, data, mode);
        },
      });

      if (turnToken.isActive()) {
        currentStage.endTurn({ failed: Boolean(outcome.failed), cancelled: Boolean(outcome.cancelled) });
        turnToken.end();
      }
      if (outcome.succeeded) regenerateRef.current = { question: text, attempt: regenerateAttempt };
      if (latestRequestRef.current === requestId) timers.schedule(reconcileFromServer, POST_STREAM_RECONCILE_MS);
    },
    [cancelRegistry, reconcileFromServer, render, roomId, roomRef, stageRef, timers, turnGuard]
  );

  const stop = useCallback(() => {
    cancelRegistry.cancel(roomId, 'user_stop');
  }, [cancelRegistry, roomId]);

  const retry = useCallback((notice) => send(notice.retryMessage, { retryOf: notice }), [send]);

  const pinAgent = useCallback((agentId) => {
    pinnedAgentRef.current = agentId ?? null;
  }, []);

  const chooseSimulationOption = useCallback((choice) => {
    conversationRef.current = selectSimulationChoice(conversationRef.current, choice);
    return `${choice?.label || choice?.choiceId || 'A'} 선택`;
  }, []);

  useEffect(() => {
    return () => cancelRegistry.cancelAll('unmount');
  }, [cancelRegistry]);

  return {
    messages,
    loadHistory,
    isStreaming,
    phase,
    followUps,
    syncErrorMessage: syncError ? '대화 기록을 서버와 맞추지 못했습니다. 잠시 후 다시 열어주세요.' : null,
    send,
    stop,
    retry,
    pinAgent,
    chooseSimulationOption,
  };
}
