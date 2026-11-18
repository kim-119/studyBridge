import test, { mock } from 'node:test';
import assert from 'node:assert/strict';
import {
  findButtonByText,
  flushEffects,
  importMobileModule,
  loadRenderer,
  press,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

const { React, act } = await loadRenderer();
const api = await importMobileModule('../services/api.js');
const { useAsync } = await importMobileModule('data/useAsync.js');
const { default: StudyTimerPanel } = await importMobileModule('screens/report/StudyTimerPanel.jsx');
const { STUDY_HEARTBEAT_INTERVAL_MS } = await importMobileModule('screens/report/studySessionModel.js');

const mountedRenderers = [];

// 서버 timers 계약의 최소 모형: 사용자당 활성 세션 1개, start 는 같은 컨텍스트면 멱등, heartbeat/end 는 활성 세션 없으면 204.
function stubTimerServer({ active = null } = {}) {
  const server = { active, calls: [], nextId: 100 };
  Object.assign(api.timerService, {
    getCurrentSession: async () => {
      server.calls.push('current');
      return server.active;
    },
    startTimer: async (userId, startTime, options) => {
      server.calls.push({ name: 'start', options });
      if (!server.active || server.active.groupStudyId != null) {
        server.active = {
          id: server.nextId++,
          startTime: '2026-10-28T12:00:00',
          lastHeartbeatAt: '2026-10-28T12:00:00',
          groupStudyId: null,
        };
      }
      return server.active;
    },
    heartbeat: async () => {
      server.calls.push('heartbeat');
      return server.active;
    },
    endTimer: async (userId, endTime, durationSeconds, reason) => {
      server.calls.push({ name: 'end', reason });
      const ended = server.active ? { ...server.active, endTime: '2026-10-28T12:30:00' } : null;
      server.active = null;
      return ended;
    },
  });
  return server;
}

function TimerHarness({ onFinished }) {
  const currentSession = useAsync(() => api.timerService.getCurrentSession(1), []);
  return React.createElement(StudyTimerPanel, {
    userId: 1,
    currentSession,
    onSessionFinished: async () => {
      onFinished?.();
      await currentSession.reload();
    },
  });
}

async function mountPanel(props = {}) {
  const renderer = await renderElement(React.createElement(TimerHarness, props));
  mountedRenderers.push(renderer);
  await flushEffects();
  return renderer;
}

function startButton(renderer) {
  return findButtonByText(renderer, '시작') || findButtonByText(renderer, '진행중');
}

function heartbeatCount(server) {
  return server.calls.filter((call) => call === 'heartbeat').length;
}

async function advance(milliseconds) {
  await act(async () => {
    mock.timers.tick(milliseconds);
  });
  await flushEffects();
}

test.beforeEach(() => {
  mock.timers.enable({ apis: ['setInterval'] });
});

test.afterEach(async () => {
  while (mountedRenderers.length > 0) {
    const renderer = mountedRenderers.pop();
    await act(async () => renderer.unmount());
  }
  mock.timers.reset();
});

test('앱 시작 시 서버 활성 세션이 없으면 타이머를 실행하지 않고 아무것도 만들지 않는다', async () => {
  const server = stubTimerServer();
  const renderer = await mountPanel();

  assert.equal(startButton(renderer).props.disabled, false);
  assert.equal(findButtonByText(renderer, '종료').props.disabled, true);
  assert.match(textOf(renderer.toJSON()), /0초/);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS * 3);
  assert.deepEqual(server.calls, ['current'], '조회만 하고 start·heartbeat 하지 않는다');
});

test('명시적 시작은 heartbeat 지원으로 시작하고 30초마다 heartbeat 를 보낸다', async () => {
  const server = stubTimerServer();
  const renderer = await mountPanel();

  await press(startButton(renderer));
  await flushEffects();

  const start = server.calls.find((call) => call.name === 'start');
  assert.deepEqual(start.options, { supportsHeartbeat: true });
  assert.equal(startButton(renderer).props.disabled, true);
  assert.match(textOf(startButton(renderer).children), /진행중/);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS);
  assert.equal(heartbeatCount(server), 1);
  await advance(STUDY_HEARTBEAT_INTERVAL_MS);
  assert.equal(heartbeatCount(server), 2);
});

test('실행 중 다시 시작을 눌러도 세션을 중복으로 만들지 않는다', async () => {
  const server = stubTimerServer();
  const renderer = await mountPanel();
  const button = startButton(renderer);

  await act(async () => {
    button.props.onClick({});
    button.props.onClick({});
  });
  await flushEffects();

  assert.equal(server.calls.filter((call) => call.name === 'start').length, 1);
});

test('앱 재실행 시 서버의 활성 개인 세션을 복원해 이어서 heartbeat 한다', async () => {
  const server = stubTimerServer({
    active: { id: 7, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:30:00', groupStudyId: null },
  });
  const renderer = await mountPanel();

  assert.equal(startButton(renderer).props.disabled, true);
  assert.equal(findButtonByText(renderer, '종료').props.disabled, false);
  assert.match(textOf(renderer.toJSON()), /30분/);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS);
  assert.equal(heartbeatCount(server), 1);
});

test('서버가 세션을 자동 종료하면(heartbeat 204) 화면도 실행 중 표시를 멈춘다', async () => {
  const server = stubTimerServer({
    active: { id: 7, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:30:00', groupStudyId: null },
  });
  const renderer = await mountPanel();

  server.active = null;
  await advance(STUDY_HEARTBEAT_INTERVAL_MS);
  await flushEffects();

  assert.equal(startButton(renderer).props.disabled, false);
  assert.equal(findButtonByText(renderer, '종료').props.disabled, true);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS * 2);
  assert.equal(heartbeatCount(server), 1, '멈춘 뒤에는 heartbeat 하지 않는다');
});

test('백그라운드에서 돌아오면 서버 상태를 다시 읽어 복원한다', async () => {
  const server = stubTimerServer();
  const renderer = await mountPanel();

  server.active = { id: 9, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:10:00' };
  await act(async () => {
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await flushEffects();

  assert.equal(server.calls.filter((call) => call === 'current').length, 2);
  assert.equal(findButtonByText(renderer, '종료').props.disabled, false);
});

test('그룹 세션은 개인 타이머로 표시하지 않고 heartbeat 하지 않는다', async () => {
  const server = stubTimerServer({
    active: { id: 3, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:20:00', groupStudyId: 51 },
  });
  const renderer = await mountPanel();

  assert.match(textOf(renderer.toJSON()), /그룹 스터디룸에서 진행 중/);
  assert.equal(findButtonByText(renderer, '종료').props.disabled, true);
  assert.equal(startButton(renderer).props.disabled, false);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS);
  assert.equal(heartbeatCount(server), 0);
  assert.equal(server.calls.filter((call) => call === 'current').length, 2, '조회로만 상태를 확인한다');
});

test('명시적 종료는 USER_STOP 으로 한 번만 종료하고 이후 heartbeat 하지 않는다', async () => {
  let finished = 0;
  const server = stubTimerServer({
    active: { id: 7, startTime: '2026-10-28T11:00:00', lastHeartbeatAt: '2026-10-28T11:30:00', groupStudyId: null },
  });
  const renderer = await mountPanel({ onFinished: () => finished++ });

  await press(findButtonByText(renderer, '종료'));
  await flushEffects();

  assert.deepEqual(
    server.calls.filter((call) => call.name === 'end'),
    [{ name: 'end', reason: 'USER_STOP' }]
  );
  assert.equal(finished, 1);
  assert.equal(startButton(renderer).props.disabled, false);

  await advance(STUDY_HEARTBEAT_INTERVAL_MS * 2);
  assert.equal(heartbeatCount(server), 0);
});
