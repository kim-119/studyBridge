import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { createGroupSocketController } from '../screens/groupstudy/groupSocketController.js';
import {
  RECONNECT_POLICY,
  SOCKET_STATE,
  STALE_CONNECTION_MS,
  canRetryManually,
  describeSocketStatus,
  isConnectionStale,
  isTokenExpiring,
  planReconnect,
  readTokenExpiryMs,
  reconnectDelayMs,
} from '../screens/groupstudy/socketConnectionModel.js';

function tokenExpiringAt(expiresAtMs) {
  const payload = Buffer.from(JSON.stringify({ exp: Math.floor(expiresAtMs / 1000) })).toString('base64url');
  return `header.${payload}.signature`;
}

test('재연결 대기 시간은 지수적으로 늘어나고 상한에서 멈춘다', () => {
  assert.deepEqual(
    [0, 1, 2, 3, 4, 5, 6].map((attempt) => reconnectDelayMs(attempt)),
    [1000, 2000, 4000, 8000, 16000, 30000, 30000]
  );
});

test('최대 시도 횟수를 넘기면 자동 재연결을 포기한다', () => {
  assert.deepEqual(planReconnect(0), { kind: 'retry', delayMs: 1000, nextAttempt: 1 });
  assert.equal(planReconnect(RECONNECT_POLICY.maxAttempts - 1).kind, 'retry');
  assert.deepEqual(planReconnect(RECONNECT_POLICY.maxAttempts), { kind: 'give-up' });
});

test('SockJS 하트비트가 끊긴 연결은 오래된 연결로 판단한다', () => {
  assert.equal(isConnectionStale(0, 1_000_000), false);
  assert.equal(isConnectionStale(1000, 1000 + STALE_CONNECTION_MS), false);
  assert.equal(isConnectionStale(1000, 1001 + STALE_CONNECTION_MS), true);
});

test('만료가 임박한 토큰만 재연결 전에 갱신한다', () => {
  const now = Date.UTC(2026, 8, 26, 12, 0, 0);
  assert.equal(readTokenExpiryMs(tokenExpiringAt(now + 3_600_000)), now + 3_600_000);
  assert.equal(isTokenExpiring(tokenExpiringAt(now + 3_600_000), now), false);
  assert.equal(isTokenExpiring(tokenExpiringAt(now + 30_000), now), true);
  assert.equal(isTokenExpiring(tokenExpiringAt(now - 1000), now), true);
  assert.equal(isTokenExpiring('not-a-jwt', now), false);
  assert.equal(isTokenExpiring(null, now), false);
});

test('연결 상태 문구와 수동 재연결 가능 여부', () => {
  assert.match(describeSocketStatus(SOCKET_STATE.RECONNECTING, 2), /2\/8/);
  assert.equal(canRetryManually(SOCKET_STATE.FAILED), true);
  assert.equal(canRetryManually(SOCKET_STATE.CONNECTED), false);
});

function createFakeStomp() {
  const clients = [];

  class FakeClient {
    constructor(config) {
      this.config = config;
      this.connected = false;
      this.subscriptions = [];
      this.published = [];
      this.isDeactivated = false;
      clients.push(this);
    }

    activate() {}

    deactivate() {
      this.isDeactivated = true;
      this.connected = false;
      return Promise.resolve();
    }

    subscribe(destination, handler) {
      this.subscriptions.push({ destination, handler });
    }

    publish(frame) {
      this.published.push(frame);
    }

    simulateConnect() {
      this.connected = true;
      this.config.onConnect();
    }

    simulateClose() {
      this.connected = false;
      this.config.onWebSocketClose();
    }
  }

  return { clients, libraries: { Client: FakeClient, SockJS: class {} } };
}

async function flushAsyncWork() {
  await new Promise((resolve) => setImmediate(resolve));
}

function createHarness() {
  const stomp = createFakeStomp();
  const statuses = [];
  const received = [];
  let reconnectedCount = 0;

  const controller = createGroupSocketController({
    groupId: 31,
    endpointUrl: 'https://example.test/ws-group',
    getHandlers: () => ({ chat: (payload) => received.push(payload), members: () => {} }),
    onStatusChange: (status) => statuses.push(status),
    onReconnected: () => {
      reconnectedCount += 1;
    },
    loadLibraries: async () => stomp.libraries,
    getToken: async () => 'token',
  });

  return {
    controller,
    clients: stomp.clients,
    statuses,
    received,
    reconnectedCount: () => reconnectedCount,
    lastState: () => statuses[statuses.length - 1]?.state,
  };
}

test('재연결 후에는 새 클라이언트 하나만 남고 토픽을 정확히 한 번 다시 구독한다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const harness = createHarness();
    harness.controller.start();
    await flushAsyncWork();

    harness.clients[0].simulateConnect();
    assert.equal(harness.lastState(), SOCKET_STATE.CONNECTED);
    assert.deepEqual(
      harness.clients[0].subscriptions.map((subscription) => subscription.destination),
      ['/topic/group/31/chat', '/topic/group/31/members']
    );

    harness.clients[0].simulateClose();
    assert.equal(harness.lastState(), SOCKET_STATE.RECONNECTING);
    assert.equal(harness.clients[0].isDeactivated, true);

    mock.timers.tick(reconnectDelayMs(0));
    await flushAsyncWork();
    assert.equal(harness.clients.length, 2);

    harness.clients[1].simulateConnect();
    assert.equal(harness.clients[1].subscriptions.length, 2);
    assert.equal(harness.reconnectedCount(), 1);

    harness.clients[1].subscriptions[0].handler({ body: JSON.stringify({ id: 9, content: '안녕' }) });
    assert.deepEqual(harness.received, [{ id: 9, content: '안녕' }]);

    harness.clients[0].config.onWebSocketClose();
    assert.equal(harness.clients.length, 2);
    assert.equal(harness.lastState(), SOCKET_STATE.CONNECTED);

    harness.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('최대 재시도 후에는 실패 상태로 멈추고 수동 재연결로 다시 시작한다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const harness = createHarness();
    harness.controller.start();
    await flushAsyncWork();

    for (let attempt = 0; attempt < RECONNECT_POLICY.maxAttempts; attempt += 1) {
      harness.clients[harness.clients.length - 1].simulateClose();
      mock.timers.tick(reconnectDelayMs(attempt));
      await flushAsyncWork();
    }

    const clientCountBeforeGiveUp = harness.clients.length;
    harness.clients[harness.clients.length - 1].simulateClose();
    assert.equal(harness.lastState(), SOCKET_STATE.FAILED);

    mock.timers.tick(RECONNECT_POLICY.maxDelayMs * 4);
    await flushAsyncWork();
    assert.equal(harness.clients.length, clientCountBeforeGiveUp);

    harness.controller.reconnectNow();
    await flushAsyncWork();
    assert.equal(harness.clients.length, clientCountBeforeGiveUp + 1);
    assert.equal(harness.lastState(), SOCKET_STATE.CONNECTING);

    harness.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('네트워크가 끊기면 재시도를 멈추고, 복구되면 즉시 다시 연결한다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const harness = createHarness();
    harness.controller.start();
    await flushAsyncWork();
    harness.clients[0].simulateConnect();

    harness.controller.handleNetworkChange(false);
    assert.equal(harness.lastState(), SOCKET_STATE.OFFLINE);
    mock.timers.tick(RECONNECT_POLICY.maxDelayMs);
    await flushAsyncWork();
    assert.equal(harness.clients.length, 1);

    harness.controller.handleNetworkChange(true);
    await flushAsyncWork();
    assert.equal(harness.clients.length, 2);
    harness.clients[1].simulateConnect();
    assert.equal(harness.reconnectedCount(), 1);

    harness.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('연결이 끊긴 상태에서는 메시지를 보내지 않고 false를 돌려준다', async () => {
  const harness = createHarness();
  harness.controller.start();
  await flushAsyncWork();

  assert.equal(harness.controller.publish('chat', { content: '보류' }), false);
  harness.clients[0].simulateConnect();
  assert.equal(harness.controller.publish('chat', { content: '전송' }), true);
  assert.deepEqual(harness.clients[0].published, [
    { destination: '/pub/group/31/chat', body: JSON.stringify({ content: '전송' }) },
  ]);

  harness.controller.stop();
});
