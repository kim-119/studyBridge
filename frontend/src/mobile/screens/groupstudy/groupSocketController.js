import { SOCKET_STATE, isConnectionStale, planReconnect } from './socketConnectionModel.js';
import { SockJsWebSocket, sockJsWebSocketUrl } from './sockJsWebSocket.js';

export const STOMP_HEARTBEAT_MS = 10000;
export const LIVENESS_CHECK_INTERVAL_MS = 10000;

function parseMessageBody(body) {
  try {
    return JSON.parse(body);
  } catch {
    return body;
  }
}

export function createGroupSocketController({
  groupId,
  endpointUrl,
  getHandlers,
  onStatusChange,
  onReconnected,
  loadLibraries,
  getToken,
  now = () => Date.now(),
}) {
  let client = null;
  let generation = 0;
  let attempt = 0;
  let retryTimer = null;
  let livenessTimer = null;
  let lastActivityAt = 0;
  let hasConnectedBefore = false;
  let isStopped = false;
  let isOffline = false;

  const report = (state) => {
    if (!isStopped) onStatusChange({ state, reconnectAttempt: attempt });
  };

  const markActivity = () => {
    lastActivityAt = now();
  };

  const clearRetry = () => {
    clearTimeout(retryTimer);
    retryTimer = null;
  };

  const discardClient = () => {
    const previous = client;
    client = null;
    generation += 1;
    if (previous) Promise.resolve(previous.deactivate()).catch(() => {});
  };

  const subscribeRoomTopics = (activeClient) => {
    Object.keys(getHandlers()).forEach((topic) => {
      activeClient.subscribe(`/topic/group/${groupId}/${topic}`, (message) => {
        markActivity();
        getHandlers()[topic]?.(parseMessageBody(message.body));
      });
    });
  };

  const scheduleReconnect = () => {
    if (isStopped || isOffline || retryTimer) return;

    const plan = planReconnect(attempt);
    if (plan.kind === 'give-up') {
      report(SOCKET_STATE.FAILED);
      return;
    }

    attempt = plan.nextAttempt;
    report(SOCKET_STATE.RECONNECTING);
    retryTimer = setTimeout(() => {
      retryTimer = null;
      connect();
    }, plan.delayMs);
  };

  const handleConnectionLost = (connectionGeneration) => {
    if (isStopped || connectionGeneration !== generation) return;
    discardClient();
    scheduleReconnect();
  };

  const handleConnected = (connectionGeneration, activeClient) => {
    if (isStopped || connectionGeneration !== generation) return;

    markActivity();
    subscribeRoomTopics(activeClient);
    const isRecovery = hasConnectedBefore;
    hasConnectedBefore = true;
    attempt = 0;
    report(SOCKET_STATE.CONNECTED);
    if (isRecovery) onReconnected();
  };

  const createClient = ({ Client }, token, connectionGeneration) => {
    const nextClient = new Client({
      webSocketFactory: () => new SockJsWebSocket(sockJsWebSocketUrl(endpointUrl), { onActivity: markActivity }),
      connectHeaders: { Authorization: token ? `Bearer ${token}` : '' },
      reconnectDelay: 0,
      heartbeatIncoming: STOMP_HEARTBEAT_MS,
      heartbeatOutgoing: STOMP_HEARTBEAT_MS,
      onConnect: () => handleConnected(connectionGeneration, nextClient),
      onWebSocketClose: () => handleConnectionLost(connectionGeneration),
      onStompError: (frame) => {
        console.warn('그룹 소켓 STOMP 오류', frame?.headers?.message);
        handleConnectionLost(connectionGeneration);
      },
    });
    return nextClient;
  };

  async function connect() {
    if (isStopped || isOffline) return;

    clearRetry();
    discardClient();
    const connectionGeneration = generation;
    report(attempt > 0 ? SOCKET_STATE.RECONNECTING : SOCKET_STATE.CONNECTING);

    try {
      const [libraries, token] = await Promise.all([loadLibraries(), getToken()]);
      if (isStopped || connectionGeneration !== generation) return;

      client = createClient(libraries, token, connectionGeneration);
      client.activate();
    } catch (error) {
      console.warn('그룹 소켓 연결을 시작하지 못했습니다.', error);
      if (connectionGeneration === generation) scheduleReconnect();
    }
  }

  const checkLiveness = () => {
    if (!client?.connected) return;
    if (!isConnectionStale(lastActivityAt, now())) return;

    console.warn('그룹 소켓이 응답하지 않아 다시 연결합니다.');
    handleConnectionLost(generation);
  };

  const reconnectNow = () => {
    if (isStopped || isOffline) return;
    attempt = 0;
    connect();
  };

  return {
    start() {
      livenessTimer = setInterval(checkLiveness, LIVENESS_CHECK_INTERVAL_MS);
      connect();
    },

    stop() {
      isStopped = true;
      clearRetry();
      clearInterval(livenessTimer);
      discardClient();
    },

    reconnectNow,

    handleResume() {
      if (isStopped || isOffline) return;
      const isHealthy = client?.connected && !isConnectionStale(lastActivityAt, now());
      if (!isHealthy) reconnectNow();
    },

    handleNetworkChange(isConnected) {
      if (isStopped) return;

      if (!isConnected) {
        isOffline = true;
        clearRetry();
        discardClient();
        report(SOCKET_STATE.OFFLINE);
        return;
      }

      if (isOffline) {
        isOffline = false;
        reconnectNow();
      }
    },

    publish(destination, body) {
      if (!client?.connected) return false;
      client.publish({ destination: `/pub/group/${groupId}/${destination}`, body: JSON.stringify(body) });
      return true;
    },
  };
}
