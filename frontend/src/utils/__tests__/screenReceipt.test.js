// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildReceipt, parseReceipt, pickRtp, summarizeInbound, summarizeOutbound, deriveShareReceipt, healthFromPeerState,
  RECEIPT_STALE_MS, RECEIPT_WAIT_MS,
} from '../screenReceipt.js';

test('receipt 왕복: 측정한 값만 싣고, 측정 못 한 값은 0 으로 채우지 않는다', () => {
  const s = buildReceipt({ phase: 'playing', stats: { w: 1920, h: 1080, fps: 24.5, kbps: 1800, lossPct: null, dropped: 0 } });
  assert.ok(!s.includes('lossPct'));
  const r = parseReceipt(s);
  assert.equal(r.phase, 'playing');
  assert.deepEqual(r.stats, { w: 1920, h: 1080, fps: 24.5, kbps: 1800, lossPct: null, dropped: 0 });
  assert.equal(parseReceipt(buildReceipt({ phase: 'subscribed' })).stats, null);
  assert.equal(parseReceipt(buildReceipt({ phase: 'playing', hidden: true })).hidden, true);
});

test('receipt 검증: 버전·phase·크기·범위 밖 값 거부', () => {
  assert.equal(parseReceipt('{"v":2,"phase":"playing"}'), null);
  assert.equal(parseReceipt('{"v":1,"phase":"hacked"}'), null);
  assert.equal(parseReceipt('not json'), null);
  assert.equal(parseReceipt(`{"v":1,"phase":"playing","x":"${'a'.repeat(600)}"}`), null);
  assert.equal(parseReceipt(null), null);
  const r = parseReceipt('{"v":1,"phase":"playing","w":-5,"h":1080,"fps":9999,"lossPct":250}');
  assert.equal(r.stats.w, null);
  assert.equal(r.stats.fps, null);
  assert.equal(r.stats.lossPct, null);
  assert.equal(r.stats.h, 1080);
});

const inbound = (o) => ({ type: 'inbound-rtp', kind: 'video', ...o });

test('pickRtp: 오디오·다른 타입은 무시하고 가장 큰 영상 프레임', () => {
  const m = new Map([
    ['a', { type: 'inbound-rtp', kind: 'audio', bytesReceived: 9 }],
    ['v1', inbound({ frameWidth: 320 })],
    ['v2', inbound({ frameWidth: 1920 })],
    ['o', { type: 'outbound-rtp', kind: 'video', frameWidth: 4000 }],
  ]);
  assert.equal(pickRtp(m, 'inbound-rtp').frameWidth, 1920);
  assert.equal(pickRtp(new Map(), 'inbound-rtp'), null);
});

test('summarizeInbound: 구간 비트레이트·손실률·드롭, 첫 표본은 누적 항목 미측정(null)', () => {
  const a = inbound({ timestamp: 1000, frameWidth: 1920, frameHeight: 1080, bytesReceived: 0, packetsLost: 0, packetsReceived: 0, framesDropped: 0, framesDecoded: 0 });
  const first = summarizeInbound(null, a);
  assert.equal(first.w, 1920);
  assert.equal(first.kbps, null);
  assert.equal(first.lossPct, null);
  const b = inbound({ timestamp: 6000, frameWidth: 1920, frameHeight: 1080, bytesReceived: 1_250_000, packetsLost: 10, packetsReceived: 990, framesDropped: 3, framesDecoded: 120, framesPerSecond: 24 });
  const s = summarizeInbound(a, b);
  assert.equal(s.kbps, 2000);
  assert.equal(s.lossPct, 1);
  assert.equal(s.dropped, 3);
  assert.equal(s.fps, 24);
  // framesPerSecond 가 없는 브라우저 → framesDecoded 차분
  const c = summarizeInbound(a, { ...b, framesPerSecond: undefined });
  assert.equal(c.fps, 24);
  // 패킷이 하나도 없던 구간은 손실률을 0% 로 단정하지 않는다
  assert.equal(summarizeInbound(b, { ...b, timestamp: 11000 }).lossPct, null);
});

test('summarizeOutbound: 송출 kbps·제한 사유', () => {
  const o = (x) => ({ type: 'outbound-rtp', kind: 'video', ...x });
  const s = summarizeOutbound(o({ timestamp: 0, bytesSent: 0 }), o({ timestamp: 4000, bytesSent: 500_000, frameWidth: 1440, frameHeight: 810, framesPerSecond: 5, qualityLimitationReason: 'cpu' }));
  assert.deepEqual(s, { w: 1440, h: 810, fps: 5, kbps: 1000, limitation: 'cpu', targetKbps: null });
});

test('summarizeOutbound: 허용 대역(targetBitrate)은 실제 송출량과 따로 보고한다', () => {
  const o = (x) => ({ type: 'outbound-rtp', kind: 'video', ...x });
  const s = summarizeOutbound(o({ timestamp: 0, bytesSent: 0 }), o({ timestamp: 5000, bytesSent: 50_000, targetBitrate: 2_083_000 }));
  assert.equal(s.kbps, 80);
  assert.equal(s.targetKbps, 2083);
  assert.equal(summarizeOutbound(null, o({ timestamp: 1, targetBitrate: 0 })).targetKbps, null);
});

const LIVE = { status: 'live', health: 'ok', liveSince: 0 };
const viewer = (userKey, cids, since = 0) => ({ userKey, name: `u${userKey}`, deviceType: 'WEB', connectionIds: cids, since });

test('혼자 공유: Publisher 가 살아 있어도 "수신 확인됨"이 아니다 → 송출 중(시청자 없음)', () => {
  const r = deriveShareReceipt({ share: LIVE, viewers: [], receipts: {}, now: 60_000 });
  assert.equal(r.phase, 'sending');
  assert.equal(r.expected, 0);
  assert.equal(r.playing, 0);
});

test('시청자 보고 전 대기 → 시간이 지나도 보고가 없으면 수신 확인 불가', () => {
  const v = [viewer('2', ['c2'], 0)];
  assert.equal(deriveShareReceipt({ share: LIVE, viewers: v, now: RECEIPT_WAIT_MS - 1 }).phase, 'sending');
  const late = deriveShareReceipt({ share: LIVE, viewers: v, now: RECEIPT_WAIT_MS + 1 });
  assert.equal(late.phase, 'unverified');
  assert.equal(late.viewers[0].state, 'no-response');
});

test('playing 보고 → 수신 확인됨, 오래되면 응답 끊김, subscribed 만으로는 확인되지 않음', () => {
  const v = [viewer('2', ['c2']), viewer('3', ['c3'])];
  const stats = { w: 1920, h: 1080, fps: 20, kbps: 1500, lossPct: 0, dropped: 0 };
  const receipts = { c2: { userKey: '2', phase: 'playing', stats, at: 50_000 }, c3: { userKey: '3', phase: 'subscribed', at: 50_000 } };
  const r = deriveShareReceipt({ share: LIVE, viewers: v, receipts, now: 52_000 });
  assert.equal(r.phase, 'received');
  assert.equal(r.playing, 1);
  assert.equal(r.measured, 1);
  assert.equal(r.viewers.find(x => x.userKey === '3').state, 'subscribed');
  const stale = deriveShareReceipt({ share: LIVE, viewers: v, receipts, now: 50_000 + RECEIPT_STALE_MS + 1 });
  assert.equal(stale.viewers.find(x => x.userKey === '2').state, 'stale');
  assert.equal(stale.phase, 'unverified');
});

test('응답은 했지만 지금 보지 않는 시청자만 있으면 "확인 불가"가 아니라 송출 중(보는 사람 없음)', () => {
  const v = [viewer('2', ['c2'])];
  const stopped = deriveShareReceipt({ share: LIVE, viewers: v, receipts: { c2: { userKey: '2', phase: 'stopped', at: 1000 } }, now: 60_000 });
  assert.equal(stopped.phase, 'sending');
  assert.equal(stopped.notWatching, 1);
  // 방금 구독만 알림 → 곧 재생 보고가 올 수 있으니 대기
  const fresh = deriveShareReceipt({ share: LIVE, viewers: v, receipts: { c2: { userKey: '2', phase: 'subscribed', at: 59_000 } }, now: 60_000 });
  assert.equal(fresh.phase, 'sending');
  assert.equal(fresh.waiting, 1);
  // 보지 않는 시청자 + 응답 없는 시청자 → 확인 불가(응답 없는 쪽을 확인할 수 없음)
  const mixed = deriveShareReceipt({ share: LIVE, viewers: [viewer('2', ['c2']), viewer('3', ['c3'])], receipts: { c2: { userKey: '2', phase: 'stopped', at: 1000 } }, now: 60_000 });
  assert.equal(mixed.phase, 'unverified');
});

test('다른 사용자 이름으로 보낸 receipt 는 그 시청자에게 매핑되지 않는다(userKey 불일치)', () => {
  const r = deriveShareReceipt({ share: LIVE, viewers: [viewer('2', ['c2'])], receipts: { c2: { userKey: '9', phase: 'playing', at: 1000 } }, now: 2000 });
  assert.equal(r.playing, 0);
});

test('같은 사용자의 기기 두 개: 하나라도 재생 중이면 재생 중(인원은 1명)', () => {
  const r = deriveShareReceipt({ share: LIVE, viewers: [viewer('2', ['pc', 'phone'])], receipts: { pc: { userKey: '2', phase: 'stopped', at: 1 }, phone: { userKey: '2', phase: 'playing', at: 1000 } }, now: 2000 });
  assert.equal(r.expected, 1);
  assert.equal(r.viewers[0].state, 'playing');
});

test('준비·장애 단계: 캡처 → 연결 → (PeerConnection 상태) → 장애', () => {
  assert.equal(deriveShareReceipt({ share: { status: 'starting', step: 'capture' } }).phase, 'capturing');
  assert.equal(deriveShareReceipt({ share: { status: 'starting', step: 'connect' } }).phase, 'connecting');
  assert.equal(deriveShareReceipt({ share: { ...LIVE, health: 'connecting' } }).phase, 'connecting');
  const receipts = { c2: { userKey: '2', phase: 'playing', at: 1000 } };
  assert.equal(deriveShareReceipt({ share: { ...LIVE, health: 'reconnecting' }, viewers: [viewer('2', ['c2'])], receipts, now: 2000 }).phase, 'failed');
  assert.equal(healthFromPeerState('connected'), 'ok');
  assert.equal(healthFromPeerState('disconnected'), 'unstable');
  assert.equal(healthFromPeerState('failed'), 'failed');
  assert.equal(healthFromPeerState('new'), 'connecting');
});
