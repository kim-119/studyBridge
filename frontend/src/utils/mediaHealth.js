// 영상 "전송 경로" 진단 — <video> 재생 판정(utils/videoPlayback)이 WAITING 일 때, 왜 프레임이 없는지를 RTCPeerConnection 으로 가른다.
//
// 배경(2026-10-26 운영 로그, group_study_273): coturn relay 포트(49160–49200, 41개)가 고갈되면 새 연결에 relay 후보가 붙지 않아
// 모바일 송출자의 ICE 가 KMS 에서 FAILED → 서버에 영상이 도착하지 않는다. 그런데 시청자 타일은 구독 ICE 가 연결된 채 패킷만 없어서
// '카메라 연결 중…' 이 원인·끝 없이 남았고, iOS Safari 송출자는 브라우저 ICE 가 'failed' 로 가지 않아 openvidu-browser 의
// 자동 재연결(reconnectStream)이 한 번도 돌지 않았다(10-18 iOS 송출 5건·10-26 1건 모두 재연결 0회).
//  → 단계별로 판정한다: 협상 중 / ICE 확인 중 / 지연(STUCK) / 실패 / 복구 중 / 연결됐지만 패킷 없음 / 패킷은 오지만 디코딩 없음 / 정상.
//  · 재연결은 OpenVidu 2.30 공개 API stream.reconnect() 로 그 스트림의 PeerConnection 만 다시 협상한다(세션·다른 구독은 그대로).
//  · 자동 재연결은 'ICE 가 끝내 연결되지 않는데 브라우저가 실패를 선언하지 않는' STUCK 에만 쓴다. 'failed'/'disconnected' 는
//    openvidu-browser 가 스스로 재연결하므로 겹쳐 부르지 않는다. 패킷 없음(NO_MEDIA)은 보통 상대 송출 문제라 재연결해도 소용없어
//    원인 안내와 수동 버튼만 둔다.

import { pickRtp } from './screenReceipt.js';

export const MEDIA_LINK = Object.freeze({
  NEGOTIATING: 'negotiating', // RTCPeerConnection 이 아직 없음(구독·송출 협상 전)
  CONNECTING: 'connecting', // ICE 확인 중(정상 범위)
  STUCK: 'stuck', // ICE 가 MEDIA_CONNECT_TIMEOUT_MS 넘게 연결되지 않았는데 브라우저는 실패를 선언하지 않음
  FAILED: 'failed', // ICE·연결 실패(브라우저 선언) 또는 구독 협상(receiveVideoFrom) 실패
  RECOVERING: 'recovering', // ICE 일시 끊김(disconnected) 또는 재연결 진행 중
  NO_MEDIA: 'no-media', // 연결은 됐지만 영상 패킷이 흐르지 않음(수신: 상대 송출이 서버에 없음 / 송출: 내 영상이 안 나감)
  NO_DECODE: 'no-decode', // 패킷은 오지만 디코딩된 프레임이 없음(수신 전용 — 키프레임 대기·디코더 문제)
  FLOWING: 'flowing', // 영상 패킷이 흐르고 있음(수신은 디코딩까지)
});

export const MEDIA_CONNECT_TIMEOUT_MS = 15000; // TURN 경유도 보통 1~5초면 연결된다. 이보다 길면 '지연'으로 알린다.
export const MEDIA_NO_DATA_MS = 8000; // 연결 뒤 이 시간 동안 영상 바이트·프레임이 늘지 않으면 '안 옴'
export const MEDIA_POLL_MS = 2000; // getStats 측정 주기(이 감시는 재생 전·멈춤 동안, 그리고 내 송출에만 돈다)
export const MEDIA_AUTO_RECONNECT_MAX = 2; // STUCK 자동 재연결 횟수(그 뒤에는 '다시 연결' 버튼)

const DEBUG_KEY = 'sb:videoDebug';

/** 개발용 상세 로그(주기 표본) 여부: 개발 빌드, localStorage 'sb:videoDebug'='1', 또는 주소에 ?videoDebug=1. 실기기(운영)에서도 켤 수 있다. */
export function isVideoDebugEnabled() {
  try {
    if (import.meta.env?.DEV) return true;
  } catch (e) { /* node 등 import.meta.env 없음 */ }
  try {
    if (globalThis.localStorage?.getItem(DEBUG_KEY) === '1') return true;
  } catch (e) { /* 저장소 차단 */ }
  try {
    return /[?&]videoDebug=1(?:&|$)/.test(globalThis.location?.search || '');
  } catch (e) {
    return false;
  }
}

/** getStats() 보고서에서 선택된 ICE 후보 쌍(로컬·원격 후보 유형) + 로컬 relay 후보 수. 표준 필드만 사용. */
export function selectedCandidatePair(report) {
  if (!report || typeof report.forEach !== 'function') return null;
  const byId = new Map();
  let selectedId = null;
  let fallback = null;
  let relayCandidates = 0;
  report.forEach((r) => {
    if (!r || !r.type) return;
    byId.set(r.id, r);
    if (r.type === 'transport' && r.selectedCandidatePairId) selectedId = r.selectedCandidatePairId;
    if (r.type === 'candidate-pair' && !fallback && (r.selected || (r.nominated && r.state === 'succeeded'))) fallback = r;
    if (r.type === 'local-candidate' && r.candidateType === 'relay') relayCandidates += 1;
  });
  const pair = (selectedId && byId.get(selectedId)) || fallback;
  const local = pair ? byId.get(pair.localCandidateId) : null;
  const remote = pair ? byId.get(pair.remoteCandidateId) : null;
  return {
    state: pair?.state || null,
    local: local?.candidateType || null,
    remote: remote?.candidateType || null,
    protocol: local?.protocol || null,
    relayProtocol: local?.relayProtocol || null,
    rttMs: Number.isFinite(pair?.currentRoundTripTime) ? Math.round(pair.currentRoundTripTime * 1000) : null,
    relayCandidates,
  };
}

/** 한 번의 측정: ICE·연결 상태 + 영상 rtp(수신 inbound-rtp / 송출 outbound-rtp) + 선택 후보 쌍. pc 가 없으면 null. */
export async function readLinkSample(pc, direction = 'inbound') {
  if (!pc) return null;
  const sample = { ice: pc.iceConnectionState || null, conn: pc.connectionState || null, rtp: null, pair: null };
  if (typeof pc.getStats !== 'function') return sample;
  try {
    const report = await pc.getStats();
    sample.rtp = pickRtp(report, direction === 'outbound' ? 'outbound-rtp' : 'inbound-rtp');
    sample.pair = selectedCandidatePair(report);
  } catch (e) {
    // 닫히는 중인 pc 등 — 상태만으로 판정한다
  }
  // getStats 를 기다리는 동안 상태가 바뀌었을 수 있으므로 마지막 값을 다시 읽는다.
  sample.ice = pc.iceConnectionState || sample.ice;
  sample.conn = pc.connectionState || sample.conn;
  return sample;
}

/**
 * 연결 진행 시계. 같은 pc 에서 영상 바이트·디코딩 프레임이 마지막으로 늘어난 시각을 기억한다.
 *  · bytesStartAt = 패킷이 (다시) 흐르기 시작한 시각 — 디코딩 유예는 여기서부터 센다(늦게 도착한 첫 패킷을 곧바로 '디코딩 없음'으로 보지 않음).
 * reset(now) = 새 pc(재연결) 시작 — 지연·무응답 판정을 처음부터 다시 센다.
 */
export function createLinkClock() {
  let startedAt = null;
  let connectedAt = null;
  let bytes = null;
  let bytesAt = null;
  let bytesStartAt = null;
  let frames = null;
  let framesAt = null;
  return {
    reset(now) {
      startedAt = now;
      connectedAt = null;
      bytes = null;
      bytesAt = null;
      bytesStartAt = null;
      frames = null;
      framesAt = null;
    },
    update(sample, direction, now) {
      if (startedAt === null) startedAt = now;
      const connected = isConnectedState(sample);
      if (!connected) connectedAt = null;
      else if (connectedAt === null) connectedAt = now;
      const rtp = sample?.rtp;
      const b = direction === 'outbound' ? rtp?.bytesSent : rtp?.bytesReceived;
      if (Number.isFinite(b)) {
        if ((bytes === null && b > 0) || (bytes !== null && b > bytes)) {
          if (bytesAt === null || now - bytesAt > MEDIA_NO_DATA_MS) bytesStartAt = now;
          bytesAt = now;
        }
        bytes = b;
      }
      const f = direction === 'outbound' ? (rtp?.framesEncoded ?? rtp?.framesSent) : rtp?.framesDecoded;
      if (Number.isFinite(f)) {
        if ((frames === null && f > 0) || (frames !== null && f > frames)) framesAt = now;
        frames = f;
      }
    },
    get view() {
      return { startedAt, connectedAt, bytes, bytesAt, bytesStartAt, frames, framesAt };
    },
  };
}

function isConnectedState(sample) {
  const ice = sample?.ice;
  return ice === 'connected' || ice === 'completed' || sample?.conn === 'connected';
}

/**
 * 단계 판정(순수 함수).
 * @param direction 'inbound'(원격 구독) | 'outbound'(내 송출)
 * @param sample readLinkSample 결과(null = pc 없음)
 * @param clock createLinkClock().view
 * @param subscribeFailed 구독 협상 실패 기록(recordSubscribeResult)
 * @param reconnecting 이 감시가 부른 stream.reconnect() 진행 중
 */
export function classifyMediaLink({ direction = 'inbound', sample = null, clock = {}, now = 0, subscribeFailed = false, reconnecting = false } = {}) {
  if (reconnecting) return MEDIA_LINK.RECOVERING;
  if (subscribeFailed) return MEDIA_LINK.FAILED;
  if (!sample || sample.ice === 'closed' || sample.conn === 'closed') return MEDIA_LINK.NEGOTIATING;
  if (sample.ice === 'failed' || sample.conn === 'failed') return MEDIA_LINK.FAILED;
  if (sample.ice === 'disconnected' || sample.conn === 'disconnected') return MEDIA_LINK.RECOVERING;
  if (!isConnectedState(sample)) {
    const started = clock.startedAt ?? now;
    return now - started > MEDIA_CONNECT_TIMEOUT_MS ? MEDIA_LINK.STUCK : MEDIA_LINK.CONNECTING;
  }
  const connectedAt = clock.connectedAt ?? now;
  // 연결 뒤(또는 마지막 진행 뒤) MEDIA_NO_DATA_MS 동안 늘지 않으면 '안 옴'. 디코딩은 패킷이 흐르기 시작한 뒤부터 센다.
  if (now - Math.max(clock.bytesAt ?? connectedAt, connectedAt) > MEDIA_NO_DATA_MS) return MEDIA_LINK.NO_MEDIA;
  if (direction === 'inbound') {
    const decodeFrom = Math.max(clock.framesAt ?? -Infinity, clock.bytesStartAt ?? connectedAt, connectedAt);
    if (now - decodeFrom > MEDIA_NO_DATA_MS) return MEDIA_LINK.NO_DECODE;
  }
  return MEDIA_LINK.FLOWING;
}

/** 자동 재연결 여부: ICE 가 연결되지 않은 채 멈춘(STUCK) 경우에만, 최대 MEDIA_AUTO_RECONNECT_MAX 회. */
export const shouldAutoReconnect = (link, attempts) => link === MEDIA_LINK.STUCK && attempts < MEDIA_AUTO_RECONNECT_MAX;

/**
 * 화면 문구. null = 경로 문제 없음(기본 '카메라 연결 중…' 또는 정상). action 'reconnect' = 그 스트림만 다시 협상하는 버튼.
 * short = 작은 타일(모바일 3열 썸네일)용 축약 문구. autoAttempts > 0 = 지연(STUCK)으로 자동 재연결을 이미 했다 →
 * 새 연결을 기다리는 동안에도 '연결 중' 으로 되돌리지 않고 지연 안내를 유지한다.
 * 소리를 끄고 재생하는 등의 우회 동작은 없다 — 원인을 알리고 사용자가 고르게 한다.
 */
export function describeMediaIssue(link, { isLocal = false, autoAttempts = 0 } = {}) {
  if (autoAttempts > 0 && (link === MEDIA_LINK.NEGOTIATING || link === MEDIA_LINK.CONNECTING || link === MEDIA_LINK.RECOVERING)) {
    return {
      text: isLocal ? '내 영상 송출 연결이 지연되고 있어요' : '영상 연결이 지연되고 있어요',
      short: isLocal ? '송출 재시도 중' : '지연 · 재시도 중',
      hint: `자동으로 다시 연결하는 중… (${Math.min(autoAttempts, MEDIA_AUTO_RECONNECT_MAX)}/${MEDIA_AUTO_RECONNECT_MAX})`,
      action: link === MEDIA_LINK.RECOVERING ? null : 'reconnect',
    };
  }
  switch (link) {
    case MEDIA_LINK.RECOVERING:
      return { text: isLocal ? '내 영상 연결을 복구하는 중…' : '영상 연결을 복구하는 중…', short: '복구 중…', action: null };
    case MEDIA_LINK.STUCK:
      return { text: isLocal ? '내 영상 송출 연결이 지연되고 있어요' : '영상 연결이 지연되고 있어요', short: isLocal ? '송출 지연' : '연결 지연', action: 'reconnect' };
    case MEDIA_LINK.FAILED: // ICE 실패와 구독 협상 실패(서버 오류) 모두 — 원인을 단정하지 않는다
      return { text: isLocal ? '내 영상을 보내지 못하고 있어요' : '영상 연결에 실패했어요', short: isLocal ? '송출 실패' : '연결 실패', hint: '네트워크 상태를 확인한 뒤 다시 연결해 주세요', action: 'reconnect' };
    case MEDIA_LINK.NO_MEDIA:
      return isLocal
        ? { text: '내 영상이 다른 참여자에게 전송되지 않고 있어요', short: '전송 안 됨', action: 'reconnect' }
        : { text: '상대방 영상이 서버에 도착하지 않고 있어요', short: '상대 영상 미도착', hint: '상대 기기의 네트워크·카메라 상태를 확인해 주세요', action: 'reconnect' };
    case MEDIA_LINK.NO_DECODE:
      return isLocal ? null : { text: '영상 신호는 오지만 화면을 그리지 못하고 있어요', short: '영상 표시 지연', action: 'reconnect' };
    default:
      return null;
  }
}

/** 로그용 요약(개인정보 없음): ICE/연결 상태, 선택 후보 쌍, 영상 바이트·패킷·손실·프레임·해상도. */
export function summarizeLinkSample(sample, direction = 'inbound') {
  if (!sample) return { pc: false };
  const r = sample.rtp || {};
  const p = sample.pair;
  return {
    ice: sample.ice,
    conn: sample.conn,
    pair: p && p.local ? `${p.local}->${p.remote}/${p.relayProtocol || p.protocol || '?'}` : null,
    relayCandidates: p ? p.relayCandidates : null,
    rttMs: p ? p.rttMs : null,
    bytes: direction === 'outbound' ? (r.bytesSent ?? null) : (r.bytesReceived ?? null),
    packets: direction === 'outbound' ? (r.packetsSent ?? null) : (r.packetsReceived ?? null),
    packetsLost: direction === 'outbound' ? null : (r.packetsLost ?? null),
    frames: direction === 'outbound' ? (r.framesEncoded ?? null) : (r.framesDecoded ?? null),
    w: r.frameWidth || null,
    h: r.frameHeight || null,
    fps: Number.isFinite(r.framesPerSecond) ? r.framesPerSecond : null,
    limitation: direction === 'outbound' ? (r.qualityLimitationReason || null) : null,
  };
}

// ── 구독 협상 결과 기록 ── session.subscribe(..., completionHandler) 의 오류를 타일 감시가 읽는다(라이브러리 객체는 건드리지 않음).
const subscribeErrors = new WeakMap();
const listeners = new Set();
const notify = () => listeners.forEach((l) => { try { l(); } catch (e) { /* ignore */ } });

export function recordSubscribeResult(streamManager, error) {
  if (!streamManager) return;
  if (error) subscribeErrors.set(streamManager, { name: error?.name || 'Error', message: String(error?.message || error).slice(0, 200) });
  else subscribeErrors.delete(streamManager);
  notify();
}

export const getSubscribeError = (streamManager) => (streamManager ? subscribeErrors.get(streamManager) || null : null);

/** 구독 결과가 기록될 때마다 listener 호출. 반환값 = 구독 해제. */
export function subscribeMediaLinkEvents(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const defaultLog = (level, tag, data) => {
  const fn = level === 'warn' ? console.warn : level === 'debug' ? console.debug : console.info;
  try { fn(`[StudyRoomOV] ${tag}`, data); } catch (e) { /* ignore */ }
};

/**
 * 한 스트림(구독자 또는 내 송출자)의 전송 경로 감시기 — React 와 무관(훅·테스트 공용).
 *  · tick() 마다 현재 pc 를 다시 얻는다(재연결 시 openvidu 가 pc 를 새로 만든다 → 시계 reset).
 *  · pc 의 iceconnectionstatechange/connectionstatechange 에서 즉시 다시 판정하고 전이를 로그로 남긴다.
 *  · 단계나 자동 재연결 횟수가 바뀔 때만 onChange(link, { autoAttempts }) — 측정 자체로는 렌더를 일으키지 않는다.
 *  · 영상이 다시 흐르면(FLOWING) 자동 재연결 횟수를 0 으로 되돌린다(다음 장애에 다시 자동 복구 기회).
 *  · reconnect() 는 stream.reconnect() 로 이 스트림만 다시 협상한다. 진행 중 중복 호출은 무시.
 */
export function createMediaLinkWatcher(streamManager, {
  direction = 'inbound',
  onChange = () => {},
  onBusy = () => {},
  now = () => performance.now(),
  log = defaultLog,
  debug = isVideoDebugEnabled(),
  autoReconnect = true,
} = {}) {
  const clock = createLinkClock();
  const label = { dir: direction, streamId: streamManager?.stream?.streamId || null, connectionId: streamManager?.stream?.connection?.connectionId || null };
  let pc = null;
  let sample = null;
  let link = null;
  let notified = null;
  let reconnecting = false;
  let autoAttempts = 0;
  let disposed = false;
  let ticking = null;

  const currentPc = () => {
    try {
      return streamManager?.stream?.getRTCPeerConnection?.() || null;
    } catch (e) {
      return null; // 협상 전(webRtcPeer 없음)
    }
  };

  const evaluate = (reason) => {
    if (disposed) return;
    const subscribeError = direction === 'inbound' ? getSubscribeError(streamManager) : null;
    const next = classifyMediaLink({ direction, sample, clock: clock.view, now: now(), subscribeFailed: !!subscribeError, reconnecting });
    if (next === MEDIA_LINK.FLOWING) autoAttempts = 0;
    if (next !== link) {
      const prev = link;
      link = next;
      const level = next === MEDIA_LINK.FLOWING || next === MEDIA_LINK.CONNECTING || next === MEDIA_LINK.NEGOTIATING ? 'info' : 'warn';
      log(level, 'media:link', { ...label, from: prev, to: next, reason, subscribeError, autoAttempts, ...summarizeLinkSample(sample, direction) });
    }
    const key = `${link}|${autoAttempts}`;
    if (key !== notified) {
      notified = key;
      onChange(link, { autoAttempts });
    }
    if (autoReconnect && shouldAutoReconnect(next, autoAttempts) && !reconnecting) {
      autoAttempts += 1;
      reconnect('auto-stuck');
    }
  };

  const onPcState = () => {
    if (disposed || !pc) return;
    sample = { ...(sample || {}), ice: pc.iceConnectionState || null, conn: pc.connectionState || null };
    clock.update(sample, direction, now());
    evaluate('pc-event');
  };

  const attach = (next) => {
    if (pc) {
      pc.removeEventListener?.('iceconnectionstatechange', onPcState);
      pc.removeEventListener?.('connectionstatechange', onPcState);
    }
    pc = next;
    clock.reset(now());
    sample = null;
    if (pc) {
      pc.addEventListener?.('iceconnectionstatechange', onPcState);
      pc.addEventListener?.('connectionstatechange', onPcState);
    }
  };

  const tick = () => {
    if (disposed) return Promise.resolve(link);
    if (ticking) return ticking;
    ticking = (async () => {
      const cur = currentPc();
      if (cur !== pc) {
        if (pc || cur) log('info', 'media:pc', { ...label, replaced: !!pc, present: !!cur });
        attach(cur);
      }
      const s = await readLinkSample(cur, direction);
      if (disposed || cur !== pc) return link; // 측정 중 pc 가 바뀌었다 — 다음 tick 에서 새 pc 로
      sample = s;
      clock.update(sample, direction, now());
      if (debug) log('debug', 'media:sample', { ...label, link, ...summarizeLinkSample(sample, direction) });
      evaluate('poll');
      return link;
    })().finally(() => { ticking = null; });
    return ticking;
  };

  const reconnect = (reason = 'user') => {
    const stream = streamManager?.stream;
    if (disposed || reconnecting || typeof stream?.reconnect !== 'function') return Promise.resolve(false);
    reconnecting = true;
    onBusy(true);
    evaluate(`reconnect:${reason}`);
    log('warn', 'media:reconnect:start', { ...label, reason, autoAttempts });
    const t0 = now();
    let pending;
    try {
      pending = Promise.resolve(stream.reconnect());
    } catch (e) {
      pending = Promise.reject(e);
    }
    return pending.then(
      () => {
        log('info', 'media:reconnect:ok', { ...label, reason, ms: Math.round(now() - t0) });
        if (direction === 'inbound') recordSubscribeResult(streamManager, null);
        return true;
      },
      (error) => {
        log('warn', 'media:reconnect:failed', { ...label, reason, ms: Math.round(now() - t0), name: error?.name, message: String(error?.message || error).slice(0, 200) });
        return false;
      }
    ).finally(() => {
      reconnecting = false;
      if (disposed) return;
      onBusy(false);
      attach(currentPc()); // 재협상한 새 pc 기준으로 처음부터 다시 센다
      evaluate(`reconnect:${reason}:done`);
      tick();
    });
  };

  return {
    tick,
    reconnect,
    get link() { return link; },
    get autoAttempts() { return autoAttempts; },
    get sample() { return sample; },
    dispose() {
      disposed = true;
      if (pc) {
        pc.removeEventListener?.('iceconnectionstatechange', onPcState);
        pc.removeEventListener?.('connectionstatechange', onPcState);
      }
      pc = null;
    },
  };
}
