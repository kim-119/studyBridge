import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import { createGroupSocketController } from '../screens/groupstudy/groupSocketController.js';
import {
  MAX_UNAUTHORIZED_RECONNECTS,
  RECONNECT_POLICY,
  SOCKET_FAILURE_REASON,
  SOCKET_STATE,
  canRetryManually,
  classifyStompError,
  describeSocketStatus,
  reconnectDelayMs,
} from '../screens/groupstudy/socketConnectionModel.js';
import { applySubmittedPayload } from '../screens/groupstudy/quizSessionModel.js';

// 서버 STOMP 인증 계약: ERROR message 헤더 UNAUTHORIZED / FORBIDDEN (+ sb-reason)
const errorFrame = (message, reason) => ({ headers: { message, ...(reason ? { 'sb-reason': reason } : {}) } });

function createHarness() {
  const clients = [];
  class FakeClient {
    constructor(config) {
      this.config = config;
      this.connected = false;
      this.subscriptions = [];
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
    publish() {}
    simulateConnect() {
      this.connected = true;
      this.config.onConnect();
    }
    simulateStompError(frame) {
      this.config.onStompError(frame);
      // 서버는 ERROR 뒤 소켓을 닫는다.
      this.connected = false;
      this.config.onWebSocketClose();
    }
  }

  const statuses = [];
  const tokenRequests = [];
  const controller = createGroupSocketController({
    groupId: 31,
    endpointUrl: 'https://example.test/ws-group',
    getHandlers: () => ({ chat: () => {}, members: () => {} }),
    onStatusChange: (status) => statuses.push(status),
    onReconnected: () => {},
    loadLibraries: async () => ({ Client: FakeClient }),
    getToken: async (options) => {
      tokenRequests.push(options);
      return 'token';
    },
  });
  return { controller, clients, statuses, tokenRequests, last: () => statuses[statuses.length - 1] };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test('ERROR 분류: 서버 message 헤더 계약', () => {
  assert.equal(classifyStompError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID')), SOCKET_FAILURE_REASON.UNAUTHORIZED);
  assert.equal(classifyStompError(errorFrame('FORBIDDEN', 'MEMBERSHIP_REVOKED')), SOCKET_FAILURE_REASON.FORBIDDEN);
  assert.equal(classifyStompError(errorFrame('BAD_REQUEST')), null);
  assert.equal(classifyStompError(undefined), null);
});

test('FORBIDDEN(강퇴·탈퇴·비멤버)이면 재연결하지 않고 실패 상태로 멈춘다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const h = createHarness();
    h.controller.start();
    await flush();
    h.clients[0].simulateConnect();
    h.clients[0].simulateStompError(errorFrame('FORBIDDEN', 'MEMBERSHIP_REVOKED'));

    assert.equal(h.last().state, SOCKET_STATE.FAILED);
    assert.equal(h.last().reason, SOCKET_FAILURE_REASON.FORBIDDEN);
    assert.equal(h.clients[0].isDeactivated, true);

    mock.timers.tick(RECONNECT_POLICY.maxDelayMs * 4);
    await flush();
    assert.equal(h.clients.length, 1, '자동 재연결 없음(이전에는 CONNECTED 마다 시도 횟수가 0 으로 돌아가 1초 간격 무한 재연결)');

    h.controller.handleResume();
    await flush();
    assert.equal(h.clients.length, 1, '앱 복귀로도 다시 붙지 않는다');

    h.controller.reconnectNow();
    await flush();
    assert.equal(h.clients.length, 2, '사용자가 명시적으로 재연결하면 다시 시도한다');
    assert.equal(h.last().reason, null);
    h.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('UNAUTHORIZED 이면 다음 연결 전에 토큰을 강제 갱신하고, 연속 한도를 넘으면 멈춘다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const h = createHarness();
    h.controller.start();
    await flush();
    assert.deepEqual(h.tokenRequests[0], { forceRefresh: false });

    for (let i = 0; i < MAX_UNAUTHORIZED_RECONNECTS; i += 1) {
      h.clients[h.clients.length - 1].simulateStompError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID'));
      assert.equal(h.last().state, SOCKET_STATE.RECONNECTING);
      mock.timers.tick(reconnectDelayMs(i));
      await flush();
      assert.deepEqual(h.tokenRequests[h.tokenRequests.length - 1], { forceRefresh: true });
    }
    const clientsBefore = h.clients.length;
    h.clients[h.clients.length - 1].simulateStompError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID'));
    assert.equal(h.last().state, SOCKET_STATE.FAILED);
    assert.equal(h.last().reason, SOCKET_FAILURE_REASON.UNAUTHORIZED);
    mock.timers.tick(RECONNECT_POLICY.maxDelayMs * 4);
    await flush();
    assert.equal(h.clients.length, clientsBefore);
    h.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('UNAUTHORIZED 뒤 갱신 토큰으로 연결되면 한도가 초기화된다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const h = createHarness();
    h.controller.start();
    await flush();
    h.clients[0].simulateStompError(errorFrame('UNAUTHORIZED', 'TOKEN_INVALID'));
    mock.timers.tick(reconnectDelayMs(0));
    await flush();
    h.clients[1].simulateConnect();
    assert.equal(h.last().state, SOCKET_STATE.CONNECTED);
    assert.equal(h.last().reason, null);

    for (let i = 0; i < MAX_UNAUTHORIZED_RECONNECTS; i += 1) {
      h.clients[h.clients.length - 1].simulateStompError(errorFrame('UNAUTHORIZED'));
      assert.equal(h.last().state, SOCKET_STATE.RECONNECTING);
      mock.timers.tick(reconnectDelayMs(i));
      await flush();
    }
    h.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('인증과 무관한 ERROR 는 기존처럼 백오프 재연결한다', async () => {
  mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  try {
    const h = createHarness();
    h.controller.start();
    await flush();
    h.clients[0].simulateStompError(errorFrame('BAD_REQUEST'));
    assert.equal(h.last().state, SOCKET_STATE.RECONNECTING);
    mock.timers.tick(reconnectDelayMs(0));
    await flush();
    assert.equal(h.clients.length, 2);
    assert.deepEqual(h.tokenRequests[1], { forceRefresh: false });
    h.controller.stop();
  } finally {
    mock.timers.reset();
  }
});

test('실패 사유별 안내 문구와 수동 재연결 가능 여부', () => {
  assert.match(describeSocketStatus(SOCKET_STATE.FAILED, 0, SOCKET_FAILURE_REASON.FORBIDDEN), /권한/);
  assert.match(describeSocketStatus(SOCKET_STATE.FAILED, 0, SOCKET_FAILURE_REASON.UNAUTHORIZED), /로그인/);
  assert.equal(describeSocketStatus(SOCKET_STATE.FAILED), '실시간 연결에 실패했습니다');
  assert.equal(canRetryManually(SOCKET_STATE.FAILED, SOCKET_FAILURE_REASON.FORBIDDEN), false);
  assert.equal(canRetryManually(SOCKET_STATE.FAILED, SOCKET_FAILURE_REASON.UNAUTHORIZED), true);
  assert.equal(canRetryManually(SOCKET_STATE.FAILED), true);
});

test('퀴즈 ack: 다른 참여자의 제출은 내 답안 상태를 바꾸지 않는다', () => {
  const state = {
    sessionId: 11,
    question: { questionId: 101 },
    hasSubmitted: false,
    selectedAnswer: 2,
    submissionAck: null,
  };
  const others = applySubmittedPayload(state, { sessionId: 11, questionId: 101, userId: 99, accepted: true }, 7);
  assert.equal(others, state, '다른 사람 ack 는 무시');
  const othersRejected = applySubmittedPayload(state, { sessionId: 11, questionId: 101, userId: 99, accepted: false }, 7);
  assert.equal(othersRejected.selectedAnswer, 2, '다른 사람 거절 ack 가 내 선택을 지우지 않는다');

  const mine = applySubmittedPayload(state, { sessionId: 11, questionId: 101, userId: '7', accepted: true }, 7);
  assert.equal(mine.hasSubmitted, true);
  const legacy = applySubmittedPayload(state, { sessionId: 11, questionId: 101, accepted: true }, 7);
  assert.equal(legacy.hasSubmitted, true, 'userId 없는 ack 는 이전 서버 호환으로 반영');
  const noUser = applySubmittedPayload(state, { sessionId: 11, questionId: 101, userId: 99, accepted: true });
  assert.equal(noUser.hasSubmitted, true, 'userId 를 넘기지 않는 기존 호출은 동작 그대로');
});
