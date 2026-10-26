import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { groupService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import {
  appendLiveChatMessage,
  latestServerId,
  mergeChatHistories,
  reconcileChatWithHistory,
  toLiveChatMessage,
} from './chatMessageModel';
import { describeMemberEvent, splitChatHistory } from './groupStudyModel';
import {
  INITIAL_QUIZ_STATE,
  QUIZ_PHASE,
  applyEndPayload,
  applyRevealPayload,
  applyScoreboardPayload,
  applySessionPayload,
  applySubmittedPayload,
  applyTimerPayload,
  dismissalStorageKey,
  isAnswerable,
  parseDismissedSessions,
  rememberDismissedSession,
  remainingSecondsAt,
  selectAnswer,
  timeTakenSecondsAt,
} from './quizSessionModel';
import { useGroupSocket } from './useGroupSocket';

const QUIZ_TICK_MS = 1000;

function readDismissedSessions(groupId) {
  return parseDismissedSessions(localStorage.getItem(dismissalStorageKey(groupId)));
}

function writeDismissedSession(groupId, sessionId) {
  const next = rememberDismissedSession(readDismissedSessions(groupId), sessionId);
  localStorage.setItem(dismissalStorageKey(groupId), JSON.stringify(next));
}

function isDismissed(groupId, sessionId) {
  if (sessionId == null) return false;
  return readDismissedSessions(groupId).includes(Number(sessionId));
}

function useQuizClock(phase) {
  const [now, setNow] = useState(() => Date.now());
  const isCounting = phase === QUIZ_PHASE.QUESTION || phase === QUIZ_PHASE.NEXT;

  useEffect(() => {
    if (!isCounting) return undefined;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), QUIZ_TICK_MS);
    return () => clearInterval(timer);
  }, [isCounting]);

  return now;
}

function useChatTimeline(groupId, userId) {
  const [liveChat, setLiveChat] = useState([]);
  const [recoveredChat, setRecoveredChat] = useState([]);
  const [recoveryError, setRecoveryError] = useState(null);
  const liveSequenceRef = useRef(0);

  const history = useAsync(() => groupService.getChatHistory(groupId), [groupId]);
  const splitHistory = useMemo(() => splitChatHistory(history.data, userId), [history.data, userId]);

  const chatMessages = useMemo(() => {
    const knownHistory = mergeChatHistories(splitHistory.chat, recoveredChat);
    return reconcileChatWithHistory(knownHistory, liveChat, { baselineServerId: latestServerId(splitHistory.chat) });
  }, [liveChat, recoveredChat, splitHistory.chat]);

  const receiveLiveChat = useCallback((payload) => {
    liveSequenceRef.current += 1;
    const message = toLiveChatMessage(payload, liveSequenceRef.current);
    setLiveChat((previous) => appendLiveChatMessage(previous, message));
  }, []);

  const recoverMissedChat = useCallback(async () => {
    try {
      const entries = await groupService.getChatHistory(groupId);
      setRecoveredChat(splitChatHistory(entries, userId).chat);
      setRecoveryError(null);
    } catch (error) {
      console.warn('재연결 후 놓친 채팅을 불러오지 못했습니다.', error);
      setRecoveryError('재연결 중 놓친 메시지를 불러오지 못했습니다.');
    }
  }, [groupId, userId]);

  return { history, aiHistory: splitHistory.ai, chatMessages, receiveLiveChat, recoverMissedChat, recoveryError };
}

export function useGroupRoom(groupId, { userId, displayName, onSelfRemoved, onParticipantRemoved }) {
  const [quiz, setQuiz] = useState(INITIAL_QUIZ_STATE);
  const [quizError, setQuizError] = useState(null);
  const callbacksRef = useRef({ onSelfRemoved, onParticipantRemoved });
  callbacksRef.current = { onSelfRemoved, onParticipantRemoved };

  const chat = useChatTimeline(groupId, userId);

  const applySession = useCallback(
    (payload) => {
      if (!payload || isDismissed(groupId, payload.sessionId)) return;
      setQuizError(null);
      setQuiz((previous) => applySessionPayload(previous, payload, Date.now()));
    },
    [groupId]
  );

  const subscriptions = useMemo(
    () => ({
      chat: chat.receiveLiveChat,
      members: (payload) => {
        const outcome = describeMemberEvent(payload, userId);
        if (outcome.kind === 'self-removed') callbacksRef.current.onSelfRemoved?.(outcome.message);
        if (outcome.kind === 'other-removed') callbacksRef.current.onParticipantRemoved?.(outcome.targetUserId);
      },
      'quiz/session': applySession,
      'quiz/question': applySession,
      'quiz/next': applySession,
      'quiz/timer': (payload) => setQuiz((previous) => applyTimerPayload(previous, payload, Date.now())),
      'quiz/submitted': (payload) => setQuiz((previous) => applySubmittedPayload(previous, payload)),
      'quiz/reveal': (payload) => setQuiz((previous) => applyRevealPayload(previous, payload)),
      'quiz/scoreboard': (payload) => setQuiz((previous) => applyScoreboardPayload(previous, payload)),
      'quiz/end': (payload) => setQuiz((previous) => applyEndPayload(previous, payload)),
      'quiz/error': (payload) => {
        setQuiz(INITIAL_QUIZ_STATE);
        setQuizError(payload?.message || '퀴즈를 시작하지 못했습니다.');
      },
    }),
    [applySession, chat.receiveLiveChat, userId]
  );

  const socket = useGroupSocket(groupId, { subscriptions, onReconnected: chat.recoverMissedChat });

  useEffect(() => {
    if (!socket.isConnected) return;

    groupService
      .getQuizSession(groupId)
      .then(applySession)
      .catch((error) => {
        if (error?.response?.status !== 404) console.warn('진행 중인 퀴즈를 확인하지 못했습니다.', error);
      });
  }, [applySession, groupId, socket.isConnected]);

  const now = useQuizClock(quiz.phase);

  const sendChat = useCallback(
    (content) =>
      socket.publish('chat', {
        senderId: userId,
        senderName: displayName,
        content,
      }),
    [displayName, socket, userId]
  );

  const startQuiz = useCallback(
    (quizId) => {
      setQuizError(null);
      const sent = socket.publish('quiz/start', { quizId: Number(quizId), userId: Number(userId) });
      if (!sent) setQuizError('실시간 연결이 준비되지 않았습니다. 잠시 후 다시 시도해주세요.');
    },
    [socket, userId]
  );

  const submitAnswer = useCallback(
    (answerIndex) => {
      const submittedAt = Date.now();
      if (!isAnswerable(quiz, submittedAt)) return;

      const sent = socket.publish('quiz/submit', {
        userId: Number(userId),
        questionId: quiz.question.questionId,
        submittedAnswer: answerIndex,
        timeTakenSeconds: timeTakenSecondsAt(quiz, submittedAt),
      });

      if (sent) {
        setQuiz((previous) => selectAnswer(previous, answerIndex));
      } else {
        setQuizError('실시간 연결이 끊겨 답안을 제출하지 못했습니다.');
      }
    },
    [quiz, socket, userId]
  );

  const dismissQuiz = useCallback(() => {
    if (quiz.sessionId != null) writeDismissedSession(groupId, quiz.sessionId);
    setQuiz(INITIAL_QUIZ_STATE);
  }, [groupId, quiz.sessionId]);

  return {
    socketState: socket.state,
    socketReconnectAttempt: socket.reconnectAttempt,
    isSocketConnected: socket.isConnected,
    reconnectSocket: socket.reconnect,
    history: chat.history,
    chatMessages: chat.chatMessages,
    chatRecoveryError: chat.recoveryError,
    aiHistory: chat.aiHistory,
    sendChat,
    quiz,
    quizRemainingSeconds: remainingSecondsAt(quiz, now),
    canAnswerQuiz: isAnswerable(quiz, now),
    quizError,
    clearQuizError: () => setQuizError(null),
    startQuiz,
    submitAnswer,
    dismissQuiz,
  };
}
