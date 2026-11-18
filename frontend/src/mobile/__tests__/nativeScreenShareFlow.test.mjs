import test from 'node:test';
import assert from 'node:assert/strict';
import { flushEffects, importMobileModule, loadRenderer, renderElement } from './support/componentHarness.mjs';

const { React, act } = await loadRenderer();
const api = await importMobileModule('../services/api.js');
const { useNativeScreenShare } = await importMobileModule('screens/groupstudy/useNativeScreenShare.js');
const { SHARE_PHASE } = await importMobileModule('screens/groupstudy/screenShareModel.js');

const mountedRenderers = [];
let latest;

// 네이티브 플러그인(android/screenshare ScreenSharePlugin) 대역: 호출 순서와 stateChange 를 흉내 낸다.
function fakeBridge({ consentGranted = true, startError = null, initialStatus = { state: 'idle' } } = {}) {
  const bridge = {
    calls: [],
    listener: null,
    isAvailable: () => true,
    getStatus: async () => initialStatus,
    onStateChange: (listener) => {
      bridge.listener = listener;
      return () => (bridge.listener = null);
    },
    requestNotificationPermission: async () => {
      bridge.calls.push('notifications');
      return { granted: true };
    },
    requestConsent: async () => {
      bridge.calls.push('consent');
      return { granted: consentGranted };
    },
    discardConsent: async () => bridge.calls.push('discard'),
    start: async (options) => {
      bridge.calls.push({ start: options });
      if (startError) throw startError;
      return { started: true };
    },
    stop: async () => {
      bridge.calls.push('stop');
      return { state: 'stopping' };
    },
    emit: (status) => act(async () => bridge.listener?.(status)),
  };
  return bridge;
}

function stubServer({ connections = { screenShareCount: 0, screenShareLimit: 2, connections: [] }, tokenError = null } = {}) {
  const server = { calls: [] };
  api.groupService.getVideoConnections = async (groupId) => {
    server.calls.push(['connections', groupId]);
    return connections;
  };
  api.groupService.getScreenShareToken = async (groupId, body) => {
    server.calls.push(['token', groupId, body]);
    if (tokenError) throw tokenError;
    return { token: 'wss://studybridge.co.kr?sessionId=group_study_51&token=tok_1', connectionId: 'con_scr', maxSendKbps: 2500 };
  };
  api.groupService.stopScreenShare = async (groupId, connectionId) => {
    server.calls.push(['stop', groupId, connectionId]);
    return { stopped: true };
  };
  return server;
}

const session = {
  getPrimaryConnectionId: () => 'con_primary',
  getIceServers: () => [{ urls: 'stun:stun.l.google.com:19302' }],
};

function Harness({ bridge }) {
  latest = useNativeScreenShare({ groupId: 51, userId: 7, displayName: '김민서', session, bridge });
  return null;
}

async function mount(bridge) {
  const renderer = await renderElement(React.createElement(Harness, { bridge }));
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

test.afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
});

test('시작 순서: 슬롯 확인 → 알림 권한 → 시스템 동의 → SCREEN 토큰(내 PRIMARY) → 네이티브 시작', async () => {
  const server = stubServer();
  const bridge = fakeBridge();
  await mount(bridge);

  await act(async () => latest.start());

  assert.deepEqual(server.calls[0], ['connections', 51]);
  const [, groupId, body] = server.calls[1];
  assert.equal(groupId, 51);
  assert.equal(body.primaryConnectionId, 'con_primary');
  assert.equal(body.deviceType, 'ANDROID');
  assert.match(body.clientInstanceId, /^[A-Za-z0-9_-]{8,64}$/);

  assert.deepEqual(bridge.calls.slice(0, 2), ['notifications', 'consent']);
  const { start } = bridge.calls[2];
  assert.equal(start.connectionId, 'con_scr');
  assert.equal(JSON.parse(start.metadata).kind, 'SCREEN');
  assert.equal(start.iceServers[0].urls, 'stun:stun.l.google.com:19302');
  assert.equal(latest.phase, SHARE_PHASE.CONNECTING);

  await bridge.emit({ state: 'publishing', connectionId: 'con_scr', streamId: 'str_1' });
  assert.equal(latest.phase, SHARE_PHASE.PUBLISHING);
  assert.equal(latest.isSharing, true);
});

test('토큰은 동의 뒤에 받는다(서버 예약 30초 만료 대비) — 동의 거부 시 토큰을 받지 않는다', async () => {
  const server = stubServer();
  const bridge = fakeBridge({ consentGranted: false });
  await mount(bridge);

  await act(async () => latest.start());

  assert.equal(server.calls.some(([name]) => name === 'token'), false);
  assert.equal(bridge.calls.some((call) => call.start), false);
  assert.equal(latest.phase, SHARE_PHASE.IDLE);
  assert.match(latest.notice, /허용하지 않아/);
});

test('그룹 화면공유가 가득 차면 동의창도 띄우지 않는다', async () => {
  stubServer({ connections: { screenShareCount: 2, screenShareLimit: 2, connections: [] } });
  const bridge = fakeBridge();
  await mount(bridge);

  await act(async () => latest.start());

  assert.equal(bridge.calls.includes('consent'), false);
  assert.match(latest.notice, /최대 2명/);
});

test('서버가 한도로 거절하면 받아 둔 동의를 버린다', async () => {
  stubServer({
    tokenError: { response: { status: 409, data: { code: 'SCREEN_SHARE_LIMIT_REACHED', message: '현재 화면공유 가능 인원(최대 2명)이 모두 사용 중입니다.' } } },
  });
  const bridge = fakeBridge();
  await mount(bridge);

  await act(async () => latest.start());

  assert.equal(bridge.calls.includes('discard'), true);
  assert.equal(bridge.calls.some((call) => call.start), false);
  assert.match(latest.notice, /최대 2명/);
});

test('네이티브 시작이 실패하면 발급받은 슬롯을 서버에서 바로 돌려준다', async () => {
  const server = stubServer();
  const bridge = fakeBridge({ startError: Object.assign(new Error('x'), { code: 'SERVICE_START_FAILED' }) });
  await mount(bridge);

  await act(async () => latest.start());

  assert.deepEqual(server.calls.at(-1), ['stop', 51, 'con_scr']);
  assert.equal(latest.phase, SHARE_PHASE.IDLE);
  assert.match(latest.notice, /서비스를 시작하지 못했습니다/);
});

test('송출이 끊기면(네트워크·시스템 중지) 슬롯을 반환하고 사유를 안내한다 — 중복 종료 이벤트에도 한 번만', async () => {
  const server = stubServer();
  const bridge = fakeBridge();
  await mount(bridge);
  await act(async () => latest.start());
  await bridge.emit({ state: 'publishing', connectionId: 'con_scr' });

  await bridge.emit({ state: 'idle', reason: 'network-lost', message: '네트워크 연결이 끊겨 화면공유를 종료했습니다.', connectionId: 'con_scr' });
  await bridge.emit({ state: 'idle', reason: 'network-lost', message: '네트워크 연결이 끊겨 화면공유를 종료했습니다.' });

  const stops = server.calls.filter(([name]) => name === 'stop');
  assert.equal(stops.length, 1);
  assert.equal(latest.phase, SHARE_PHASE.IDLE);
  assert.match(latest.notice, /네트워크/);
});

test('빠른 실패(시작 직후 idle)도 IDLE 로 돌아온다', async () => {
  stubServer();
  const bridge = fakeBridge();
  bridge.start = async (options) => {
    bridge.calls.push({ start: options });
    bridge.listener?.({ state: 'idle', reason: 'connection-failed', message: '화면공유 서버에 연결하지 못했습니다.' });
    return { started: true };
  };
  await mount(bridge);

  await act(async () => latest.start());
  await flushEffects();

  assert.equal(latest.phase, SHARE_PHASE.IDLE);
  assert.match(latest.notice, /연결하지 못했습니다/);
});

test('사용자 중지는 네이티브 stop 을 부르고 안내 없이 끝난다', async () => {
  stubServer();
  const bridge = fakeBridge();
  await mount(bridge);
  await act(async () => latest.start());
  await bridge.emit({ state: 'publishing', connectionId: 'con_scr' });

  await act(async () => latest.stop());
  assert.equal(bridge.calls.at(-1), 'stop');
  await bridge.emit({ state: 'idle', reason: 'user-stopped', message: '화면공유를 종료했습니다.' });
  assert.equal(latest.phase, SHARE_PHASE.IDLE);
  assert.equal(latest.notice, null);
});

test('앱 재실행·WebView 재로딩 뒤에도 송출 중이면 상태를 이어서 보여준다', async () => {
  stubServer();
  const bridge = fakeBridge({ initialStatus: { state: 'publishing', connectionId: 'con_scr' } });
  await mount(bridge);
  assert.equal(latest.phase, SHARE_PHASE.PUBLISHING);
});

test('그룹스터디를 나가면(화면 이탈) 송출을 끝낸다', async () => {
  stubServer();
  const bridge = fakeBridge();
  await mount(bridge);
  await act(async () => latest.start());
  await bridge.emit({ state: 'publishing', connectionId: 'con_scr' });

  const renderer = mountedRenderers.pop();
  await act(async () => renderer.unmount());
  assert.equal(bridge.calls.at(-1), 'stop');
});

test('화상 연결 전에는 시작하지 않는다', async () => {
  const server = stubServer();
  const bridge = fakeBridge();
  const renderer = await renderElement(
    React.createElement(() => {
      latest = useNativeScreenShare({ groupId: 51, userId: 7, displayName: '김민서', session: {}, bridge });
      return null;
    })
  );
  mountedRenderers.push(renderer);
  await flushEffects();

  await act(async () => latest.start());
  assert.equal(server.calls.length, 0);
  assert.match(latest.notice, /화상 연결이 준비된 뒤/);
});
