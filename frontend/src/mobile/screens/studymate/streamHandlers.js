import { classifyFailure, DEFAULT_AGENT_ERROR, neutralizeErrorText } from '../../../utils/studymate/errorText';
import {
  applyAgentAnswer,
  applyAgentError,
  applyAgentStart,
  applyAllComplete,
  applyDebateSection,
  applyHeartbeat,
  applyModeGuard,
  applyRouteMessage,
  applySimulationStage,
  applySocraticAnswer,
  applySocraticStep,
  applyStageComplete,
  isEventForTurnTarget,
  isModeGuardPayload,
  slotOfEvent,
} from './turnAccumulator';
import { buildWarnNotice } from './streamNotices';

const CONTENT_EVENTS = new Set([
  'agent_answer',
  'stage_complete',
  'agent_stage_complete',
  'debate_section',
  'socratic_step',
  'socratic_answer',
  'simulation_stage',
  'route_message',
  'route_pipeline',
]);

const MODE_LABELS = { socratic: '소크라테스', debate: '토론', simulation: '상황극', basic: '기본' };

function modeFailureText(data, mode) {
  return neutralizeErrorText(data.message || data.reason, `${MODE_LABELS[mode] || ''} 모드 처리에 실패했습니다. (${data.code})`);
}

function stageSlotStates(context, data) {
  const { turn, stage } = context;
  if (data.stage === 1) {
    (data.answers || []).forEach((answer, index) => {
      const event = { agentIndex: answer?.agentIndex ?? index + 1, agentId: answer?.agentId, agentName: answer?.agentName || answer?.agent_name };
      const isOffTarget = turn.target?.scope === 'single' && !isEventForTurnTarget(turn, event);
      stage.setSlotState(slotOfEvent(turn, event), isOffTarget ? 'validating' : 'answering');
    });
  }
  if (data.stage === 2) {
    stage.setSlotState(0, 'validating');
    (data.answers || []).forEach((answer) => stage.addInteraction('validation', answer, null));
  }
  if (data.stage === 3) {
    stage.setAllStates('peer_feedback');
    stage.addInteraction('peer_feedback', { feedbacks: data.feedbacks || [] }, null);
  }
}

function handleAgentAnswer(context, data) {
  const { turn, stage } = context;
  context.rearmWatchdog();
  if (!data) return;
  context.captureState(data);
  context.render(applyAgentAnswer(turn, data));
  if (turn.modeGuardShown) return;
  stage.showAnswer({ slot: slotOfEvent(turn, data), data, isForTarget: isEventForTurnTarget(turn, data) });
}

function handleAgentError(context, data) {
  if (!data) return;
  context.flags.sawError = true;
  const message = neutralizeErrorText(data.message, DEFAULT_AGENT_ERROR);
  context.render(applyAgentError(context.turn, data, message, classifyFailure(data).code));
  context.stage.setSlotState(slotOfEvent(context.turn, data), 'error');
}

function handleStreamError(context, data) {
  const { turn, stage, flags } = context;
  if (turn.completed) return;
  flags.sawError = true;

  const slot = data ? slotOfEvent(turn, data) : null;
  if (slot != null) stage.setSlotState(slot, 'error');
  else stage.setAllStates('error');

  if (data && (data.agentId != null || data.agentIndex != null)) {
    context.render(applyAgentError(turn, data, neutralizeErrorText(data.message, DEFAULT_AGENT_ERROR)));
    return;
  }
  if (!context.isActive()) return;

  if (turn.rendered) {
    if (data?.code) context.appendNotice(modeErrorNotice(context, data));
    return;
  }
  if (data?.code) {
    context.render(applyModeGuard(turn, { ...data, message: modeFailureText(data, turn.mode) }, { isError: true }));
    return;
  }
  throw new Error('stream error event');
}

function modeErrorNotice(context, data) {
  const { turn } = context;
  return {
    id: `${turn.parentId}::mode-error`,
    sender: 'AI',
    senderName: `${MODE_LABELS[turn.mode] || '학습'} 모드 안내`,
    content: modeFailureText(data, turn.mode),
    isNotice: true,
    isModeGuard: true,
    isError: true,
    createdAt: new Date().toISOString(),
    parentId: `${turn.parentId}::mode-error`,
  };
}

function handleAllComplete(context, data) {
  const { turn, stage, machine } = context;
  if (turn.completed) return;
  machine.allComplete();
  context.finalize();
  stage.completeTurn();
  context.captureState(data);
  context.render(applyAllComplete(turn, data));
}

function handleDone(context, data) {
  const { turn, stage, machine, flags } = context;
  machine.done();
  context.finalize();
  if (turn.completed) return;
  const failed = String(data?.status || '').toLowerCase() === 'error';
  if (failed && !turn.rendered && !flags.anyAnswerReceived) {
    flags.sawError = true;
    stage.setAllStates('error');
  }
}

function acceptEvent(context, event, data) {
  const verdict = context.turnToken.accept(data);
  if (!verdict.ok) return false;
  context.markAlive();
  context.machine.event(event);
  if (CONTENT_EVENTS.has(event)) context.flags.anyAnswerReceived = true;
  return true;
}

function structuredHandler(context, { applyEvent, interactionKind, stateOf, capturesState }) {
  return (data) => {
    const { turn, stage } = context;
    if (capturesState) context.captureState(data);
    const rendered = applyEvent(turn, data);
    if (!rendered) return;
    context.render(rendered);
    stage.addInteraction(interactionKind, data, slotOfEvent(turn, data));
    stage.setSlotState(slotOfEvent(turn, data), stateOf(data));
  };
}

export function createStreamHandlers(context) {
  const { turn, stage } = context;

  return {
    onAnyEvent: (event, data) => acceptEvent(context, event, data),
    onComment: () => context.markAlive(),
    onControlEvent: () => {},
    onTurnStart: (data) => {
      context.captureState(data);
      if (isModeGuardPayload(data)) context.render(applyModeGuard(turn, data));
    },
    onHeartbeat: (data) => context.render(applyHeartbeat(turn, data)),
    onProfessorMotion: (data) => stage.applyMotion(data),
    onInteractionEvent: (data) => data && stage.addInteraction('interaction_event', data, slotOfEvent(turn, data)),
    onSynthesisDiff: (data) => data && stage.addInteraction('synthesis_diff', data, slotOfEvent(turn, data)),
    onAgentStart: (data) => {
      if (!data) return;
      context.render(applyAgentStart(turn, data));
      stage.setSlotState(slotOfEvent(turn, data), 'walking_to_question');
    },
    onAgentAnswer: (data) => handleAgentAnswer(context, data),
    onAgentError: (data) => handleAgentError(context, data),
    onFollowUpSuggestions: (data) => context.setFollowUps(Array.isArray(data?.suggestions) ? data.suggestions : []),
    onStageComplete: (data) => {
      context.rearmWatchdog();
      const rendered = applyStageComplete(turn, data);
      if (!rendered) return;
      context.render(rendered);
      stageSlotStates(context, data);
    },
    onDebateSection: structuredHandler(context, {
      applyEvent: applyDebateSection,
      interactionKind: 'debate',
      stateOf: (data) => (String(data?.stageType || '').includes('REBUTTAL') ? 'peer_feedback' : 'answering'),
      capturesState: true,
    }),
    onSocraticStep: structuredHandler(context, {
      applyEvent: applySocraticStep,
      interactionKind: 'socratic',
      stateOf: () => 'answering',
      capturesState: false,
    }),
    onSimulationStage: structuredHandler(context, {
      applyEvent: applySimulationStage,
      interactionKind: 'simulation',
      stateOf: () => 'answering',
      capturesState: true,
    }),
    onSocraticAnswer: (data) => context.render(applySocraticAnswer(turn, data)),
    onRouteMessage: (data) => context.render(applyRouteMessage(turn, data)),
    onRoutePipeline: (data) => context.render(applyRouteMessage(turn, data, { isPipeline: true })),
    onRouteNotice: (data) => {
      if (!data?.message || !context.isActive()) return;
      context.appendNotice(buildWarnNotice({ parentId: turn.parentId, text: data.message, senderName: turn.fallbackAgentName }));
    },
    onAllComplete: (data) => handleAllComplete(context, data),
    onDone: (data) => handleDone(context, data),
    onError: (data) => handleStreamError(context, data),
  };
}
