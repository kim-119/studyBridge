// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  MEDIA_LINK, MEDIA_CONNECT_TIMEOUT_MS, MEDIA_NO_DATA_MS, MEDIA_AUTO_RECONNECT_MAX,
  classifyMediaLink, createLinkClock, createMediaLinkWatcher, describeMediaIssue, getSubscribeError,
  readLinkSample, recordSubscribeResult, selectedCandidatePair, shouldAutoReconnect, summarizeLinkSample,
} from '../mediaHealth.js';

// ── getStats 보고서·RTCPeerConnection·OpenVidu Stream 모사 ──
const statsReport = (entries) => new Map(entries.map((e) => [e.id, e]));
const inbound = (o = {}) => ({ id: 'in-v', type: 'inbound-rtp', kind: 'video', bytesReceived: 0, packetsReceived: 0, packetsLost: 0, framesDecoded: 0, timestamp: 0, ...o });
const outbound = (o = {}) => ({ id: 'out-v', type: 'outbound-rtp', kind: 'video', bytesSent: 0, packetsSent: 0, framesEncoded: 0, timestamp: 0, ...o });
const relayPair = [
  { id: 'T', type: 'transport', selectedCandidatePairId: 'CP' },
  { id: 'CP', type: 'candidate-pair', state: 'succeeded', nominated: true, localCandidateId: 'L', remoteCandidateId: 'R', currentRoundTripTime: 0.042 },
  { id: 'L', type: 'local-candidate', candidateType: 'relay', protocol: 'udp', relayProtocol: 'udp' },
  { id: 'R', type: 'remote-candidate', candidateType: 'srflx', protocol: 'udp' },
];

function fakePc({ ice = 'new', conn = 'new', rtp = null } = {}) {
  const handlers = {};
  const pc = {
    iceConnectionState: ice,
    connectionState: conn,
    rtp,
    extra: [],
    addEventListener: (t, h) => { (handlers[t] ||= new Set()).add(h); },
    removeEventListener: (t, h) => { handlers[t]?.delete(h); },
    listenerCount: () => Object.values(handlers).reduce((n, s) => n + s.size, 0),
    getStats: async () => statsReport([...(pc.rtp ? [pc.rtp] : []), ...pc.extra]),
    set(next) {
      if (next.ice) pc.iceConnectionState = next.ice;
      if (next.conn) pc.connectionState = next.conn;
      handlers.iceconnectionstatechange?.forEach((h) => h());
      handlers.connectionstatechange?.forEach((h) => h());
    },
  };
  return pc;
}

/** openvidu Stream 모사: reconnect() = 새 pc 로 교체(openvidu 2.30 은 기존 pc 를 버리고 새로 협상). */
function fakeStreamManager(pc, { reconnect } = {}) {
  const stream = {
    streamId: 'str_CUS_TEST_con_X',
    connection: { connectionId: 'con_X' },
    pc,
    reconnects: 0,
    getRTCPeerConnection() {
      if (!stream.pc) throw new TypeError("Cannot read properties of undefined (reading 'pc')"); // 협상 전(webRtcPeer 없음)
      return stream.pc;
    },
    reconnect: reconnect || (async () => { stream.reconnects += 1; stream.pc = fakePc({ ice: 'checking', conn: 'connecting' }); }),
  };
  return { stream };
}

const quiet = () => {};
const flush = () => new Promise((r) => setTimeout(r, 0));
function watch(sm, direction = 'inbound', extra = {}) {
  let t = 0;
  const changes = [];
  const infos = [];
  const logs = [];
  const w = createMediaLinkWatcher(sm, {
    direction,
    now: () => t,
    onChange: (l, info) => { changes.push(l); infos.push({ link: l, ...info }); },
    log: (level, tag, data) => logs.push({ level, tag, data }),
    debug: false,
    ...extra,
  });
  return { w, changes, infos, logs, at: (ms) => { t = ms; }, get t() { return t; } };
}

test('판정: pc 없음·닫힘 = 협상 중, ICE 확인 중 → 시간 초과 시 STUCK(지연), 실패·끊김·재연결 중', () => {
  assert.equal(classifyMediaLink({ sample: null }), MEDIA_LINK.NEGOTIATING);
  assert.equal(classifyMediaLink({ sample: { ice: 'closed', conn: 'closed' } }), MEDIA_LINK.NEGOTIATING);
  const checking = { ice: 'checking', conn: 'connecting' };
  assert.equal(classifyMediaLink({ sample: checking, clock: { startedAt: 0 }, now: MEDIA_CONNECT_TIMEOUT_MS }), MEDIA_LINK.CONNECTING);
  assert.equal(classifyMediaLink({ sample: checking, clock: { startedAt: 0 }, now: MEDIA_CONNECT_TIMEOUT_MS + 1 }), MEDIA_LINK.STUCK);
  assert.equal(classifyMediaLink({ sample: { ice: 'failed', conn: 'failed' } }), MEDIA_LINK.FAILED);
  assert.equal(classifyMediaLink({ sample: { ice: 'checking', conn: 'failed' } }), MEDIA_LINK.FAILED);
  assert.equal(classifyMediaLink({ sample: { ice: 'disconnected', conn: 'disconnected' } }), MEDIA_LINK.RECOVERING);
  assert.equal(classifyMediaLink({ sample: { ice: 'failed' }, reconnecting: true }), MEDIA_LINK.RECOVERING);
  // 구독 협상 실패는 pc 상태와 무관하게 실패
  assert.equal(classifyMediaLink({ sample: { ice: 'connected' }, subscribeFailed: true }), MEDIA_LINK.FAILED);
});

test('판정: 연결 뒤 영상 바이트가 안 늘면 NO_MEDIA(상대 송출 문제), 바이트는 오는데 디코딩이 없으면 NO_DECODE, 둘 다 늘면 FLOWING', () => {
  const connected = { ice: 'connected', conn: 'connected' };
  const base = { startedAt: 0, connectedAt: 1000 };
  // 2026-10-26 재현: 시청자 구독 ICE 는 연결됐지만 송출자 ICE 가 KMS 에서 실패 → 패킷 0
  assert.equal(classifyMediaLink({ sample: connected, clock: { ...base }, now: 1000 + MEDIA_NO_DATA_MS }), MEDIA_LINK.FLOWING, '유예 안');
  assert.equal(classifyMediaLink({ sample: connected, clock: { ...base }, now: 1000 + MEDIA_NO_DATA_MS + 1 }), MEDIA_LINK.NO_MEDIA);
  const t = 20000;
  assert.equal(classifyMediaLink({ sample: connected, clock: { ...base, bytesAt: t - 100 }, now: t }), MEDIA_LINK.NO_DECODE);
  assert.equal(classifyMediaLink({ sample: connected, clock: { ...base, bytesAt: t - 100, framesAt: t - 100 }, now: t }), MEDIA_LINK.FLOWING);
  // 송출은 디코딩 개념이 없다 — 보낸 바이트만 본다
  assert.equal(classifyMediaLink({ direction: 'outbound', sample: connected, clock: { ...base, bytesAt: t - 100 }, now: t }), MEDIA_LINK.FLOWING);
  assert.equal(classifyMediaLink({ direction: 'outbound', sample: connected, clock: { ...base, bytesAt: 2000 }, now: 2000 + MEDIA_NO_DATA_MS + 1 }), MEDIA_LINK.NO_MEDIA);
  // ICE 상태가 오래된 브라우저(connectionState 없음)도 iceConnectionState 로 판정
  assert.equal(classifyMediaLink({ sample: { ice: 'completed', conn: null }, clock: { ...base, bytesAt: t, framesAt: t }, now: t }), MEDIA_LINK.FLOWING);
});

test('진행 시계: 바이트·프레임이 늘어난 시각만 기록, 첫 표본 0 은 진행 아님, 끊기면 연결 시각 초기화, reset = 새 pc', () => {
  const c = createLinkClock();
  c.reset(0);
  const s = (ice, rtp) => ({ ice, conn: null, rtp });
  c.update(s('checking', null), 'inbound', 100);
  assert.equal(c.view.connectedAt, null);
  c.update(s('connected', inbound({ bytesReceived: 0, framesDecoded: 0 })), 'inbound', 500);
  assert.deepEqual([c.view.connectedAt, c.view.bytesAt, c.view.framesAt], [500, null, null]);
  c.update(s('connected', inbound({ bytesReceived: 1200, framesDecoded: 0 })), 'inbound', 2500);
  assert.deepEqual([c.view.bytesAt, c.view.framesAt], [2500, null]);
  c.update(s('connected', inbound({ bytesReceived: 1200, framesDecoded: 3 })), 'inbound', 4500);
  assert.deepEqual([c.view.bytesAt, c.view.framesAt], [2500, 4500]);
  c.update(s('disconnected', inbound({ bytesReceived: 1200, framesDecoded: 3 })), 'inbound', 5000);
  assert.equal(c.view.connectedAt, null);
  c.update(s('connected', null), 'inbound', 6000);
  assert.equal(c.view.connectedAt, 6000);
  assert.equal(c.view.bytesStartAt, 2500);
  c.reset(7000);
  assert.deepEqual(c.view, { startedAt: 7000, connectedAt: null, bytes: null, bytesAt: null, bytesStartAt: null, frames: null, framesAt: null });
  // 송출: bytesSent·framesEncoded
  c.update(s('connected', outbound({ bytesSent: 900, framesEncoded: 2 })), 'outbound', 7100);
  assert.deepEqual([c.view.bytesAt, c.view.framesAt], [7100, 7100]);
});

test('디코딩 유예는 패킷이 흐르기 시작한 때부터: 늦게 온 첫 패킷·끊겼다 다시 온 패킷을 곧바로 NO_DECODE 로 보지 않음', () => {
  const c = createLinkClock();
  c.reset(0);
  const s = (rtp) => ({ ice: 'connected', conn: 'connected', rtp });
  const judge = (now) => classifyMediaLink({ sample: s(null), clock: c.view, now });
  c.update(s(inbound()), 'inbound', 0);
  assert.equal(judge(MEDIA_NO_DATA_MS + 1), MEDIA_LINK.NO_MEDIA);
  // 송출자가 늦게 복구돼 첫 패킷이 12초에 도착 — 디코딩은 아직 0
  c.update(s(inbound({ bytesReceived: 800 })), 'inbound', 12000);
  assert.equal(judge(12000), MEDIA_LINK.FLOWING);
  c.update(s(inbound({ bytesReceived: 1500 })), 'inbound', 19000);
  assert.equal(judge(12000 + MEDIA_NO_DATA_MS + 1), MEDIA_LINK.NO_DECODE, '패킷은 계속 오는데 디코딩이 없으면');
  c.update(s(inbound({ bytesReceived: 2200, framesDecoded: 5 })), 'inbound', 21000);
  assert.equal(judge(21000), MEDIA_LINK.FLOWING);
  // 30초 동안 끊겼다가(상대 백그라운드 등) 패킷이 다시 오기 시작 → 디코딩 유예도 다시 시작
  c.update(s(inbound({ bytesReceived: 2900, framesDecoded: 5 })), 'inbound', 51000);
  assert.equal(c.view.bytesStartAt, 51000);
  assert.equal(judge(51000), MEDIA_LINK.FLOWING);
  assert.equal(judge(51000 + MEDIA_NO_DATA_MS - 1), MEDIA_LINK.FLOWING);
});

test('선택 후보 쌍·relay 후보 수: transport.selectedCandidatePairId 우선, 없으면 nominated+succeeded, relay 0 = TURN 할당 실패 신호', async () => {
  const p = selectedCandidatePair(statsReport(relayPair));
  assert.deepEqual(p, { state: 'succeeded', local: 'relay', remote: 'srflx', protocol: 'udp', relayProtocol: 'udp', rttMs: 42, relayCandidates: 1 });
  const fb = selectedCandidatePair(statsReport(relayPair.filter((r) => r.type !== 'transport')));
  assert.equal(fb.local, 'relay');
  // relay 포트 고갈 때 브라우저 후보 = host·srflx 뿐
  const noRelay = selectedCandidatePair(statsReport([
    { id: 'L1', type: 'local-candidate', candidateType: 'host' },
    { id: 'L2', type: 'local-candidate', candidateType: 'srflx' },
  ]));
  assert.deepEqual([noRelay.local, noRelay.relayCandidates], [null, 0]);
  assert.equal(selectedCandidatePair(null), null);

  const pc = fakePc({ ice: 'connected', conn: 'connected', rtp: inbound({ bytesReceived: 5000, framesDecoded: 10, frameWidth: 640, frameHeight: 480 }) });
  pc.extra = relayPair;
  const sample = await readLinkSample(pc, 'inbound');
  assert.equal(sample.rtp.bytesReceived, 5000);
  assert.deepEqual(summarizeLinkSample(sample, 'inbound'), { ice: 'connected', conn: 'connected', pair: 'relay->srflx/udp', relayCandidates: 1, rttMs: 42, bytes: 5000, packets: 0, packetsLost: 0, frames: 10, w: 640, h: 480, fps: null, limitation: null });
  assert.equal(await readLinkSample(null), null);
  // getStats 실패 → 상태만으로 판정
  const broken = fakePc({ ice: 'checking' });
  broken.getStats = async () => { throw new Error('closed'); };
  assert.deepEqual(await readLinkSample(broken), { ice: 'checking', conn: 'new', rtp: null, pair: null });
});

test('문구: 원인별 안내 + 재연결 버튼, 복구 중엔 버튼 없음, 정상·연결 중은 null(기본 문구), 내 송출과 원격 구분', () => {
  for (const l of [MEDIA_LINK.NEGOTIATING, MEDIA_LINK.CONNECTING, MEDIA_LINK.FLOWING, null]) assert.equal(describeMediaIssue(l), null);
  assert.equal(describeMediaIssue(MEDIA_LINK.RECOVERING).action, null);
  for (const l of [MEDIA_LINK.STUCK, MEDIA_LINK.FAILED, MEDIA_LINK.NO_MEDIA, MEDIA_LINK.NO_DECODE]) assert.equal(describeMediaIssue(l).action, 'reconnect');
  assert.match(describeMediaIssue(MEDIA_LINK.NO_MEDIA).text, /상대방 영상이 서버에 도착하지 않고/);
  assert.match(describeMediaIssue(MEDIA_LINK.NO_MEDIA, { isLocal: true }).text, /내 영상이/);
  assert.match(describeMediaIssue(MEDIA_LINK.STUCK, { isLocal: true }).text, /내 영상 송출/);
  assert.equal(describeMediaIssue(MEDIA_LINK.NO_DECODE, { isLocal: true }), null);
  // 자동 재연결 뒤 새 연결을 기다리는 동안: '연결 중' 으로 되돌아가지 않고 지연 안내 + 진행 표시(재연결 중엔 버튼 없음)
  const retry = describeMediaIssue(MEDIA_LINK.CONNECTING, { autoAttempts: 1 });
  assert.match(retry.text, /영상 연결이 지연되고 있어요/);
  assert.match(retry.hint, /자동으로 다시 연결하는 중… \(1\/2\)/);
  assert.equal(retry.action, 'reconnect');
  assert.equal(describeMediaIssue(MEDIA_LINK.RECOVERING, { autoAttempts: 2 }).action, null);
  assert.match(describeMediaIssue(MEDIA_LINK.NEGOTIATING, { isLocal: true, autoAttempts: 1 }).text, /내 영상 송출 연결이 지연/);
  assert.equal(describeMediaIssue(MEDIA_LINK.FLOWING, { autoAttempts: 1 }), null);
  // 모바일 3열 썸네일(≈117×66px)용 축약 문구는 모든 경우에 있고 짧다(10자 = 117px 한 줄 실측)
  for (const l of Object.values(MEDIA_LINK)) {
    for (const isLocal of [false, true]) {
      for (const autoAttempts of [0, 1]) {
        const d = describeMediaIssue(l, { isLocal, autoAttempts });
        if (!d) continue;
        assert.ok(d.short && [...d.short].length <= 10, `${l}/${isLocal}/${autoAttempts}: '${d.short}'`);
      }
    }
  }
  assert.equal(shouldAutoReconnect(MEDIA_LINK.STUCK, 0), true);
  assert.equal(shouldAutoReconnect(MEDIA_LINK.STUCK, MEDIA_AUTO_RECONNECT_MAX), false);
  for (const l of [MEDIA_LINK.FAILED, MEDIA_LINK.NO_MEDIA, MEDIA_LINK.RECOVERING]) assert.equal(shouldAutoReconnect(l, 0), false);
});

// iOS Safari 송출자(운영 10-18·10-26): ICE 가 연결되지 않는데 브라우저가 'failed' 를 선언하지 않아 openvidu 재연결이 0회였다.
test('감시기: 연결되지 않은 채 멈춘 송출 → 자동 재연결(stream.reconnect) 최대 2회, 그 뒤엔 수동 버튼만', async () => {
  const sm = fakeStreamManager(fakePc({ ice: 'checking', conn: 'connecting' }));
  const h = watch(sm, 'outbound');
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.CONNECTING);
  h.at(MEDIA_CONNECT_TIMEOUT_MS + 1);
  await h.w.tick();
  await flush();
  assert.equal(sm.stream.reconnects, 1, '1차 자동 재연결');
  assert.ok(h.changes.includes(MEDIA_LINK.STUCK) && h.changes.includes(MEDIA_LINK.RECOVERING));
  // 새 pc 기준으로 다시 센다 → 곧바로 STUCK 이 아니다
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.CONNECTING);
  h.at(2 * MEDIA_CONNECT_TIMEOUT_MS + 10);
  await h.w.tick();
  await flush();
  assert.equal(sm.stream.reconnects, 2, '2차 자동 재연결');
  h.at(3 * MEDIA_CONNECT_TIMEOUT_MS + 20);
  await h.w.tick();
  await flush();
  assert.equal(sm.stream.reconnects, 2, '자동은 최대 2회');
  assert.equal(h.w.link, MEDIA_LINK.STUCK);
  assert.equal(h.w.autoAttempts, 2);
  assert.deepEqual(h.infos.at(-1), { link: MEDIA_LINK.STUCK, autoAttempts: 2 }, '화면에 자동 재연결 횟수 전달');
  // 사용자 '다시 연결' — 연결되면 FLOWING
  assert.equal(await h.w.reconnect('user'), true);
  assert.equal(sm.stream.reconnects, 3);
  sm.stream.pc.set({ ice: 'connected', conn: 'connected' });
  sm.stream.pc.rtp = outbound({ bytesSent: 4000, framesEncoded: 30 });
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.FLOWING);
  assert.equal(h.w.autoAttempts, 0, '복구되면 다음 장애에 다시 자동 복구 기회');
  assert.ok(h.logs.some((l) => l.tag === 'media:reconnect:start' && l.data.reason === 'auto-stuck'));
  assert.ok(h.logs.some((l) => l.tag === 'media:reconnect:ok' && l.data.reason === 'user'));
  h.w.dispose();
});

test('감시기: 브라우저가 실패를 선언하면 FAILED(openvidu 가 스스로 재연결하므로 겹쳐 부르지 않음) → 새 pc 로 교체되면 다시 판정', async () => {
  const sm = fakeStreamManager(fakePc({ ice: 'checking', conn: 'connecting' }));
  const h = watch(sm);
  await h.w.tick();
  sm.stream.pc.set({ ice: 'failed', conn: 'failed' }); // pc 이벤트만으로 즉시 반영(폴링 기다리지 않음)
  assert.equal(h.w.link, MEDIA_LINK.FAILED);
  h.at(60000);
  await h.w.tick();
  assert.equal(sm.stream.reconnects, 0);
  // openvidu-browser 의 reconnectStream 이 pc 를 새로 만들었다
  sm.stream.pc = fakePc({ ice: 'checking', conn: 'connecting' });
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.CONNECTING);
  assert.ok(h.logs.some((l) => l.tag === 'media:pc' && l.data.replaced));
  h.w.dispose();
});

test('감시기: 구독 ICE 는 연결됐는데 패킷이 없으면 NO_MEDIA(자동 재연결 안 함), 패킷이 오고 디코딩되면 FLOWING, 일시 끊김은 RECOVERING', async () => {
  const pc = fakePc({ ice: 'connected', conn: 'connected', rtp: null });
  const sm = fakeStreamManager(pc);
  const h = watch(sm);
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.FLOWING, '연결 직후 유예');
  h.at(MEDIA_NO_DATA_MS + 1);
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.NO_MEDIA);
  assert.equal(sm.stream.reconnects, 0);
  const warn = h.logs.find((l) => l.tag === 'media:link' && l.data.to === MEDIA_LINK.NO_MEDIA);
  assert.equal(warn.level, 'warn');
  assert.equal(warn.data.streamId, 'str_CUS_TEST_con_X');
  // 송출자가 복구돼 패킷이 흐른다(바이트만 → NO_DECODE 유예 → 프레임까지 FLOWING)
  pc.rtp = inbound({ bytesReceived: 3000, framesDecoded: 0 });
  h.at(MEDIA_NO_DATA_MS + 2000);
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.FLOWING);
  pc.rtp = inbound({ bytesReceived: 6000, framesDecoded: 15 });
  h.at(MEDIA_NO_DATA_MS + 4000);
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.FLOWING);
  pc.set({ ice: 'disconnected', conn: 'disconnected' });
  assert.equal(h.w.link, MEDIA_LINK.RECOVERING);
  h.w.dispose();
  assert.equal(pc.listenerCount(), 0, 'dispose 후 pc 리스너 해제');
  const before = h.changes.length;
  pc.set({ ice: 'connected', conn: 'connected' });
  assert.equal(h.changes.length, before, 'dispose 후 알림 없음');
});

test('감시기: 구독 협상 실패 기록 → FAILED, 재연결 성공 시 기록 해제', async () => {
  const pc = fakePc({ ice: 'new', conn: 'new' });
  const sm = fakeStreamManager(pc);
  const h = watch(sm);
  recordSubscribeResult(sm, Object.assign(new Error('Error on receiveVideoFrom : {"code":303}'), { name: 'Error' }));
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.FAILED);
  assert.match(getSubscribeError(sm).message, /receiveVideoFrom/);
  assert.equal(await h.w.reconnect('user'), true);
  assert.equal(getSubscribeError(sm), null);
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.CONNECTING);
  recordSubscribeResult(sm, null);
  h.w.dispose();
});

test('감시기: 재연결 실패·협상 전 pc 없음·reconnect 없는 객체·중복 호출', async () => {
  const busy = [];
  const sm = fakeStreamManager(null, { reconnect: () => Promise.reject(new Error("websocket wasn't opened")) });
  const h = watch(sm, 'inbound', { onBusy: (b) => busy.push(b) });
  await h.w.tick();
  assert.equal(h.w.link, MEDIA_LINK.NEGOTIATING, 'webRtcPeer 없음 = 협상 전(예외를 삼킨다)');
  const a = h.w.reconnect('user');
  const b = h.w.reconnect('user');
  assert.equal(await b, false, '진행 중 중복 호출 무시');
  assert.equal(await a, false);
  assert.deepEqual(busy, [true, false]);
  assert.ok(h.logs.some((l) => l.tag === 'media:reconnect:failed'));
  h.w.dispose();
  const plain = createMediaLinkWatcher({ stream: { getRTCPeerConnection: () => null } }, { log: quiet, now: () => 0 });
  assert.equal(await plain.reconnect(), false);
  plain.dispose();
});

test('소스 가드: 구독 결과 기록·타일 감시 배선·재연결은 스트림 단위(세션 재생성·음소거 우회 없음)', () => {
  const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const studyRoom = fs.readFileSync(path.join(src, 'components/StudyRoom.jsx'), 'utf8');
  const hook = fs.readFileSync(path.join(src, 'hooks/useMediaLinkHealth.js'), 'utf8');
  const util = fs.readFileSync(path.join(src, 'utils/mediaHealth.js'), 'utf8');
  assert.match(studyRoom, /recordSubscribeResult\(subscriber, err \|\| null\)/);
  assert.match(studyRoom, /useMediaLinkHealth\(hasOpenViduManager \? streamManager : null, \{ enabled: linkWatch, direction: isLocal \? 'outbound' : 'inbound' \}\)/);
  assert.match(studyRoom, /data-testid="video-feed-send-badge"/);
  assert.match(util, /stream\.reconnect\(\)/);
  for (const code of [hook, util]) {
    assert.doesNotMatch(code, /\.muted = true|initSession\(|session\.disconnect|\.unpublish\(/);
  }
});
