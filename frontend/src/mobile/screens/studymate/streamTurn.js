import { agentService } from '../../../services/api';
import { createStreamStateMachine } from '../../../utils/studymate/streamStateMachine';
import { createStreamHandlers } from './streamHandlers';
import {
  GATEWAY_RETRY_DELAYS_MS,
  INTERRUPTED_TEXT,
  PARTIAL_TEXT,
  SLOW_STREAM_TEXT,
  USER_STOP_TEXT,
  WATCHDOG_FAIL_MS,
  WATCHDOG_WARN_MS,
  buildGatewayRetryMessage,
  buildStreamNotice,
  describeStreamFailure,
} from './streamNotices';
import { markPendingAnswers } from './turnAccumulator';

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function createWatchdog({ onWarn, onTimeout }) {
  let warnTimer = null;
  let failTimer = null;
  let stopped = false;

  const clear = () => {
    clearTimeout(warnTimer);
    clearTimeout(failTimer);
  };

  return {
    arm() {
      clear();
      if (stopped) return;
      warnTimer = setTimeout(onWarn, WATCHDOG_WARN_MS);
      failTimer = setTimeout(onTimeout, WATCHDOG_FAIL_MS);
    },
    stop() {
      stopped = true;
      clear();
    },
  };
}

function createTurnContext(options, controller, machine) {
  const { turn, turnToken, stage, render, appendNotice, setFollowUps, captureState } = options;
  const flags = {
    sawError: false,
    anyAnswerReceived: false,
    finalReceived: false,
    watchdogTimedOut: false,
    cancelledReason: null,
    eventSeen: false,
  };

  const renderIfActive = (messages) => {
    if (messages && turnToken.isActive()) render(messages);
  };

  const watchdog = createWatchdog({
    onWarn: () => renderIfActive(markPendingAnswers(turn, SLOW_STREAM_TEXT)),
    onTimeout: () => {
      flags.watchdogTimedOut = true;
      controller.abort('watchdog');
    },
  });

  return {
    turn,
    turnToken,
    stage,
    machine,
    flags,
    watchdog,
    captureState,
    setFollowUps,
    appendNotice,
    render: renderIfActive,
    isActive: () => turnToken.isActive(),
    markAlive: () => {
      flags.eventSeen = true;
      if (!flags.finalReceived) watchdog.arm();
    },
    rearmWatchdog: () => {
      if (!flags.finalReceived) watchdog.arm();
    },
    finalize: () => {
      flags.finalReceived = true;
      watchdog.stop();
    },
  };
}

function listenForCancel(controller, context) {
  controller.signal.addEventListener(
    'abort',
    () => {
      if (context.flags.watchdogTimedOut) return;
      context.flags.cancelledReason = String(controller.signal.reason || 'cancel');
      context.machine.cancel(context.flags.cancelledReason);
    },
    { once: true }
  );
}

function canRetryGateway(error, context, attempt) {
  const { flags, turn, turnToken } = context;
  return (
    Boolean(error?.retryable) &&
    !flags.eventSeen &&
    !flags.anyAnswerReceived &&
    !turn.rendered &&
    !flags.watchdogTimedOut &&
    turnToken.isActive() &&
    attempt < GATEWAY_RETRY_DELAYS_MS.length
  );
}

async function streamWithGatewayRetry({ roomId, payload, handlers, controller, context }) {
  for (let attempt = 0; ; attempt += 1) {
    try {
      context.machine.open();
      await agentService.streamMessage(null, roomId, payload, handlers, {
        signal: controller.signal,
        requestId: context.turnToken.requestId,
      });
      return;
    } catch (error) {
      if (!canRetryGateway(error, context, attempt)) throw error;

      const waitMs = GATEWAY_RETRY_DELAYS_MS[attempt];
      context.render([buildGatewayRetryMessage({ parentId: context.turn.parentId, attempt: attempt + 1, waitMs })]);
      await wait(waitMs);
      if (!context.turnToken.isActive() || context.flags.watchdogTimedOut) throw error;
      context.rearmWatchdog();
    }
  }
}

function noticeFor(context, text, retryMessage, isError = true) {
  if (isError) context.flags.sawError = true;
  context.appendNotice(buildStreamNotice({ parentId: context.turn.parentId, text, retryMessage, isError }));
}

function concludeCancelled(context, { closePending, retryMessage }) {
  const { flags, turn, turnToken } = context;
  closePending(turn.parentId);
  if (!turn.rendered && turnToken.isActive() && flags.cancelledReason === 'user_stop') {
    noticeFor(context, USER_STOP_TEXT, retryMessage, false);
  }
  return { cancelled: true };
}

function concludeTurn(context, streamError, { closePending, retryMessage }) {
  const { flags, turn, turnToken } = context;

  if (flags.cancelledReason) return concludeCancelled(context, { closePending, retryMessage });
  if (!turnToken.isActive()) return { stale: true };

  if (flags.finalReceived) {
    if (turn.rendered || turn.completed) return { succeeded: !flags.sawError, failed: flags.sawError };
    noticeFor(context, flags.anyAnswerReceived ? PARTIAL_TEXT : INTERRUPTED_TEXT, retryMessage);
    return { failed: true };
  }

  const text =
    flags.anyAnswerReceived || turn.rendered
      ? PARTIAL_TEXT
      : describeStreamFailure(streamError, { watchdogTimedOut: flags.watchdogTimedOut });
  noticeFor(context, text, retryMessage);
  return { failed: true, error: streamError };
}

export async function runStreamTurn(options) {
  const { roomId, payload, turnToken, cancelRegistry, onPhase, closePending, retryMessage } = options;
  const controller = new AbortController();
  const machine = createStreamStateMachine((phase) => {
    if (turnToken.isActive()) onPhase(phase);
  });
  const context = createTurnContext(options, controller, machine);
  const handlers = createStreamHandlers(context);

  listenForCancel(controller, context);
  cancelRegistry.register(roomId, controller, turnToken.requestId);
  context.watchdog.arm();

  let streamError = null;
  try {
    await streamWithGatewayRetry({ roomId, payload, handlers, controller, context });
  } catch (error) {
    streamError = error;
  } finally {
    context.watchdog.stop();
    machine.close();
    cancelRegistry.release(roomId, turnToken.requestId);
  }

  return concludeTurn(context, streamError, { closePending, retryMessage });
}
