import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { agentService } from '../../../services/api';
import { createCancelRegistry } from '../../../utils/studymate/streamCancelRegistry';
import { STREAM_PHASES, createStreamStateMachine } from '../../../utils/studymate/streamStateMachine';
import { createTurnGuard } from '../../../utils/studymate/turnGuard';
import { describeApiError } from '../../data/useAsync';

function answerTextOf(payload) {
  return (
    payload?.answer ??
    payload?.content ??
    payload?.text ??
    payload?.message ??
    payload?.delta ??
    ''
  );
}

function agentNameOf(payload) {
  return payload?.agentName || payload?.agent_name || payload?.name || 'AI 메이트';
}

function describeStreamError(error) {
  if (error?.name === 'StreamHttpError') {
    if (error.authFailure) return '로그인이 만료되었습니다. 다시 로그인해주세요.';
    if (error.forbidden) return '이 대화방에 접근할 권한이 없습니다.';
    if (error.notFound) return '삭제된 대화방입니다.';
    if (error.serverMessage) return error.serverMessage;
    if (error.retryable) return '서버가 혼잡합니다. 잠시 후 다시 시도해주세요.';
  }

  if (error?.name === 'AbortError') return null;

  return describeApiError(error);
}

const MAX_RETRY_ATTEMPTS = 2;
const RETRY_BACKOFF_MS = [1500, 4000];

export function useStudyMateStream(roomId) {
  const [messages, setMessages] = useState([]);
  const [phase, setPhase] = useState(STREAM_PHASES.IDLE);
  const [errorMessage, setErrorMessage] = useState(null);
  const [retryAttempt, setRetryAttempt] = useState(0);
  const [isReconnecting, setReconnecting] = useState(false);
  const [canRetry, setCanRetry] = useState(false);
  const lastQuestionRef = useRef(null);
  const retryTimerRef = useRef(null);

  const cancelRegistry = useMemo(() => createCancelRegistry(), []);
  const turnGuard = useMemo(() => createTurnGuard(), []);
  const machineRef = useRef(null);

  const appendAnswer = useCallback((payload) => {
    const text = answerTextOf(payload);
    if (!text) return;

    const agentName = agentNameOf(payload);

    setMessages((previous) => {
      const last = previous[previous.length - 1];

      if (last && last.role === 'assistant' && last.agentName === agentName && !last.isSealed) {
        const updated = [...previous];
        updated[updated.length - 1] = { ...last, text: last.text + text };
        return updated;
      }

      return [...previous, { id: `${agentName}-${previous.length}`, role: 'assistant', agentName, text }];
    });
  }, []);

  const stop = useCallback(() => {
    clearTimeout(retryTimerRef.current);
    cancelRegistry.cancel(roomId, 'user-stop');
    machineRef.current?.cancel('user-stop');
    setReconnecting(false);
    setPhase(STREAM_PHASES.CANCELLED);
  }, [cancelRegistry, roomId]);

  const send = useCallback(
    async (question, { isRetry = false } = {}) => {
      const text = question.trim();
      if (!text || machineRef.current?.isLoading) return;

      lastQuestionRef.current = text;
      setErrorMessage(null);
      setCanRetry(false);
      if (!isRetry) {
        setRetryAttempt(0);
        setReconnecting(false);
      }
      if (!isRetry) {
        setMessages((previous) => [
          ...previous,
          { id: `user-${previous.length}`, role: 'user', text },
        ]);
      }

      const machine = createStreamStateMachine(setPhase);
      machineRef.current = machine;

      const turn = turnGuard.begin(roomId);
      const controller = new AbortController();
      cancelRegistry.register(roomId, controller, turn.requestId);

      machine.open();

      try {
        await agentService.streamMessage(
          null,
          roomId,
          { message: text, requestId: turn.requestId },
          {
            onTurnStart: () => machine.event('turn_start'),
            onHeartbeat: () => machine.event('heartbeat'),
            onAgentAnswer: (data) => {
              if (!turn.isActive()) return;
              machine.event('agent_answer');
              appendAnswer(data);
            },
            onStageComplete: (data) => {
              if (!turn.isActive()) return;
              machine.event('stage_complete');
              appendAnswer(data);
            },
            onSocraticStep: (data) => {
              if (!turn.isActive()) return;
              machine.event('socratic_step');
              appendAnswer(data);
            },
            onDebateSection: (data) => {
              if (!turn.isActive()) return;
              machine.event('debate_section');
              appendAnswer(data);
            },
            onSimulationStage: (data) => {
              if (!turn.isActive()) return;
              machine.event('simulation_stage');
              appendAnswer(data);
            },
            onAgentError: (data) => setErrorMessage(data?.message || 'AI 응답 중 오류가 발생했습니다.'),
            onError: (data) => {
              machine.fail('stream_error');
              setErrorMessage(data?.message || 'AI 응답이 중단되었습니다.');
            },
            onAllComplete: () => machine.allComplete(),
            onDone: () => machine.done(),
            onControlEvent: (event) => machine.event(event),
          },
          { requestId: turn.requestId, signal: controller.signal }
        );

        machine.close();
        setReconnecting(false);
        setRetryAttempt(0);
      } catch (error) {
        const message = describeStreamError(error);
        machine.fail('exception');

        // 업스트림 재시작/과부하(retryable)와 네트워크 단절은 자동 재시도한다.
        // 401/403/404 처럼 재시도로 해결되지 않는 오류는 사용자에게 바로 알린다.
        const isRetryable = error?.retryable === true || error?.name === 'TypeError';

        if (isRetryable && retryAttempt < MAX_RETRY_ATTEMPTS) {
          setReconnecting(true);
          setRetryAttempt((attempt) => attempt + 1);
          retryTimerRef.current = setTimeout(
            () => send(text, { isRetry: true }),
            RETRY_BACKOFF_MS[Math.min(retryAttempt, RETRY_BACKOFF_MS.length - 1)]
          );
          return;
        }

        setReconnecting(false);
        setCanRetry(isRetryable);
        if (message) setErrorMessage(message);
      } finally {
        cancelRegistry.release(roomId, turn.requestId);
        setMessages((previous) =>
          previous.map((entry) => (entry.role === 'assistant' ? { ...entry, isSealed: true } : entry))
        );
      }
    },
    [appendAnswer, cancelRegistry, retryAttempt, roomId, turnGuard]
  );

  useEffect(() => {
    return () => {
      clearTimeout(retryTimerRef.current);
      cancelRegistry.cancel(roomId, 'unmount');
    };
  }, [cancelRegistry, roomId]);

  const retry = useCallback(() => {
    if (lastQuestionRef.current) send(lastQuestionRef.current, { isRetry: true });
  }, [send]);

  return {
    messages,
    setMessages,
    phase,
    isStreaming:
      phase === STREAM_PHASES.CONNECTING ||
      phase === STREAM_PHASES.STREAMING ||
      phase === STREAM_PHASES.FINALIZING,
    errorMessage,
    isReconnecting,
    retryAttempt,
    canRetry,
    send,
    stop,
    retry,
  };
}
