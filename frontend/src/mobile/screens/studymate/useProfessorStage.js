import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  BUBBLE_TTL,
  CASUAL_PHASE,
  COMPLETED_HOLD_MS,
  COMPLETED_PHASE,
  FALLBACK_PHASES,
  PHASE_A,
  isCasualShortInput,
  makeBubbleText,
} from '../../../components/studymate/pixel/basicInteractionChoreography';
import {
  deriveInteractions,
  normalizeMotionStates,
  phaseStatesFor,
} from '../../../components/studymate/pixel/modeInteractionProfiles';
import { professorDisplayName, professorRoleOfSlot } from './professorActions';

const IDLE_STATES = { theory: 'idle', book: 'idle', ai: 'idle' };
const SINGLE_SECONDARY_STATES = new Set(['idle', 'thinking', 'listening', 'validating']);

function singleScopeStates(states, targetRole) {
  if (!targetRole || !states || typeof states !== 'object') return states;
  return Object.fromEntries(Object.entries(states).map(([role, state]) => [role, role === targetRole ? state : 'idle']));
}

function useTimerBag() {
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

export function useProfessorStage(roomAgents) {
  const [visualStates, setVisualStates] = useState(IDLE_STATES);
  const [bubbles, setBubbles] = useState({});
  const [statusMessage, setStatusMessage] = useState('');
  const [selectedRole, setSelectedRole] = useState(null);
  const [interactions, setInteractions] = useState([]);
  const [turnDoneAt, setTurnDoneAt] = useState(0);
  const turnRef = useRef({ scope: 'all', mode: 'basic', seenInteractions: new Set(), interactionSeq: 0 });
  const fillerTimers = useTimerBag();
  const bubbleTimers = useTimerBag();

  const displayName = useCallback((role) => professorDisplayName(roomAgents, role), [roomAgents]);

  const setRoleState = useCallback((role, state) => {
    if (!role) return;
    setVisualStates((previous) => (previous[role] === state ? previous : { ...previous, [role]: state }));
  }, []);

  const setBubble = useCallback(
    (role, bubble) => {
      if (!role) return;
      setBubbles((previous) => ({ ...previous, [role]: bubble }));
      const ttl = bubble && BUBBLE_TTL[bubble.kind];
      if (ttl > 0) {
        bubbleTimers.schedule(() => {
          setBubbles((previous) => (previous[role] === bubble ? { ...previous, [role]: null } : previous));
        }, ttl);
      }
    },
    [bubbleTimers]
  );

  const applyPhase = useCallback(
    (phase) => {
      if (phase.message != null) setStatusMessage(phase.message);
      if (phase.states) setVisualStates(normalizeMotionStates(phase.states));
      Object.entries(phase.bubbles || {}).forEach(([role, bubble]) => setBubble(role, bubble));
    },
    [setBubble]
  );

  const setSlotState = useCallback(
    (slot, state) => {
      const turn = turnRef.current;
      if (turn.backendMotionDriven || slot == null) return;
      const role = professorRoleOfSlot(slot);
      const isOffTarget = turn.scope === 'single' && Number.isInteger(turn.targetSlot) && slot !== turn.targetSlot;
      setRoleState(role, isOffTarget && !SINGLE_SECONDARY_STATES.has(state) ? 'idle' : state);
    },
    [setRoleState]
  );

  const setAllStates = useCallback(
    (state) => {
      const turn = turnRef.current;
      if (turn.backendMotionDriven) return;
      if (turn.scope === 'single') {
        setRoleState(turn.targetRole, state);
        return;
      }
      setVisualStates({ theory: state, book: state, ai: state });
    },
    [setRoleState]
  );

  const scheduleFallbackPhases = useCallback(() => {
    FALLBACK_PHASES.forEach((phase) => {
      fillerTimers.schedule(() => {
        const turn = turnRef.current;
        if (turn.backendMotionDriven || turn.sawRealAnswer || turn.ended) return;
        applyPhase(phase);
      }, phase.at);
    });
  }, [applyPhase, fillerTimers]);

  const beginTurn = useCallback(
    ({ mode, target, message }) => {
      fillerTimers.clearAll();
      bubbleTimers.clearAll();
      turnRef.current = {
        mode,
        message,
        scope: target?.scope === 'single' ? 'single' : 'all',
        targetSlot: target?.agentIndex,
        targetRole: target?.professorRole,
        seenInteractions: new Set(),
        interactionSeq: 0,
      };
      setInteractions([]);
      setBubbles({});
      setAllStates('thinking');

      if (target?.scope === 'single') {
        setStatusMessage(`${displayName(target.professorRole)}님이 질문을 읽고 있어요.`);
      } else if (mode === 'basic' && isCasualShortInput(message)) {
        applyPhase(CASUAL_PHASE);
      } else if (mode === 'basic') {
        applyPhase(PHASE_A);
        scheduleFallbackPhases();
      } else {
        setStatusMessage('');
      }
    },
    [applyPhase, bubbleTimers, displayName, fillerTimers, scheduleFallbackPhases, setAllStates]
  );

  const applyMotion = useCallback(
    (data) => {
      if (!data) return;
      const turn = turnRef.current;
      turn.backendMotionDriven = true;
      fillerTimers.clearAll();
      const states = data.states && typeof data.states === 'object' ? data.states : data.phase ? phaseStatesFor(data.mode || turn.mode, data.phase) : null;
      if (!states) return;
      const scoped = turn.scope === 'single' ? singleScopeStates(states, turn.targetRole) : states;
      setVisualStates(normalizeMotionStates(scoped));
    },
    [fillerTimers]
  );

  const showAnswer = useCallback(
    ({ slot, data, isForTarget }) => {
      const turn = turnRef.current;
      turn.sawRealAnswer = true;
      fillerTimers.clearAll();
      const role = slot != null ? professorRoleOfSlot(slot) : null;

      if (turn.scope === 'single' && !isForTarget) {
        setSlotState(slot, 'validating');
        if (role) setBubble(role, { text: '확인 중...', kind: 'thinking', agentName: data.agentName });
        return;
      }

      setSlotState(slot, 'answering');
      if (!role) return;
      const fullText = String(data.content || data.answer || '').trim();
      setBubble(role, { text: makeBubbleText(fullText), fullText, kind: 'answer', agentName: data.agentName });
      if (turn.mode === 'basic' || turn.scope === 'single') {
        setStatusMessage(`${data.agentName || displayName(role)}님이 답변 중이에요.`);
      }
    },
    [displayName, fillerTimers, setBubble, setSlotState]
  );

  const addInteraction = useCallback((kind, data, slot) => {
    const turn = turnRef.current;
    const enriched = slot != null && data && !data.agentRole ? { ...data, agentRole: professorRoleOfSlot(slot) } : data;
    const records = deriveInteractions(turn.mode, kind, enriched, turn.requestId, turn.interactionSeq);
    turn.interactionSeq += 1;
    const fresh = (records || []).filter((record) => record?.content && record.key && !turn.seenInteractions.has(record.key));
    if (!fresh.length) return;
    fresh.forEach((record) => turn.seenInteractions.add(record.key));
    setInteractions((previous) => [...previous, ...fresh]);
  }, []);

  const holdThenClearStatus = useCallback(() => {
    bubbleTimers.schedule(() => setStatusMessage(''), COMPLETED_HOLD_MS);
  }, [bubbleTimers]);

  const completeTurn = useCallback(() => {
    const turn = turnRef.current;
    fillerTimers.clearAll();

    if (turn.scope === 'single' && turn.targetRole) {
      setVisualStates({ ...IDLE_STATES, [turn.targetRole]: 'completed' });
      setStatusMessage(`${displayName(turn.targetRole)}님의 답변이 정리됐어요.`);
      holdThenClearStatus();
      return;
    }

    setVisualStates({ theory: 'completed', book: 'completed', ai: 'completed' });
    if (turn.mode !== 'basic') return;
    setStatusMessage(COMPLETED_PHASE.message);
    if (!isCasualShortInput(turn.message)) {
      Object.entries(COMPLETED_PHASE.bubbles).forEach(([role, bubble]) => setBubble(role, bubble));
    }
    holdThenClearStatus();
  }, [displayName, fillerTimers, holdThenClearStatus, setBubble]);

  const endTurn = useCallback(
    ({ failed, cancelled }) => {
      turnRef.current.ended = true;
      fillerTimers.clearAll();
      const finalState = failed ? 'error' : cancelled ? 'idle' : 'completed';
      setVisualStates({ theory: finalState, book: finalState, ai: finalState });
      if (failed) setBubbles({});
      bubbleTimers.schedule(() => setStatusMessage(''), COMPLETED_HOLD_MS + 200);
      if (!failed && !cancelled) setTurnDoneAt(Date.now());
    },
    [bubbleTimers, fillerTimers]
  );

  const reset = useCallback(() => {
    fillerTimers.clearAll();
    bubbleTimers.clearAll();
    setVisualStates(IDLE_STATES);
    setBubbles({});
    setInteractions([]);
    setSelectedRole(null);
    setStatusMessage('');
  }, [bubbleTimers, fillerTimers]);

  const autoReset = useCallback((role) => setRoleState(role, 'idle'), [setRoleState]);

  const setTurnRequestId = useCallback((requestId) => {
    turnRef.current.requestId = requestId;
  }, []);

  return {
    visualStates,
    bubbles,
    statusMessage,
    setStatusMessage,
    selectedRole,
    setSelectedRole,
    interactions,
    turnDoneAt,
    beginTurn,
    setTurnRequestId,
    applyMotion,
    setSlotState,
    setAllStates,
    showAnswer,
    addInteraction,
    completeTurn,
    endTurn,
    reset,
    autoReset,
  };
}
