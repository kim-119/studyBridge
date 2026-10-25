// 화면공유 수신 확인(receipt) 계약 v1 — 시청자가 "실제로 재생 중인지"를 송출자에게 알린다(웹·Android 공통 규칙).
//
//  경로: 기존 OpenVidu 세션 시그널(session.signal). 새 WebRTC 연결·서버 API·폴링 없음.
//   · 시청자(PRIMARY 세션) → 송출자의 SCREEN Connection 한 곳으로만 보낸다(to: [screenConnection]). 브로드캐스트 금지.
//   · 수신 측 event.from 은 OpenVidu 서버가 보낸 사람의 Connection 으로 채운다(클라이언트가 위조 불가) → 그 Connection 의
//     serverData(Spring 발급)로 userId·kind 를 확인한다. 토큰은 그룹 멤버에게만 발급되므로 세션 참가 자체가 권한 검증이다.
//   · payload 는 표시용 수치일 뿐 권한 판단에 쓰지 않는다. 범위를 벗어난 값은 버리거나 잘라낸다.
//
//  type: 'sb-screen-rx'   data: {"v":1,"phase":"subscribed|playing|stopped","w","h","fps","kbps","lossPct","dropped","hidden"}
//   · subscribed : 구독(WebRTC 협상) 완료 — 아직 화면에 재생 중이라는 뜻은 아니다(다른 공유를 보고 있을 수 있음)
//   · playing    : 영상 요소가 실제 프레임을 재생 중. 재생하는 동안 RECEIPT_INTERVAL_MS 마다 수신 통계와 함께 다시 보낸다
//   · stopped    : 이 공유를 더 이상 화면에 그리지 않음(다른 공유 선택·스테이지 닫힘)

export const SCREEN_RECEIPT_SIGNAL = 'sb-screen-rx';
export const RECEIPT_PHASES = Object.freeze(['subscribed', 'playing', 'stopped']);
export const RECEIPT_INTERVAL_MS = 5000;   // 시청자 통계 측정·보고 주기(재생 중일 때만)
export const RECEIPT_STALE_MS = 16000;     // playing 보고가 이만큼 끊기면 "응답 끊김"
export const RECEIPT_WAIT_MS = 10000;      // 시청자가 보인 뒤 이만큼 아무 보고가 없으면 "응답 없음"(구버전·앱 등)
const MAX_DATA_LENGTH = 512;

const num = (v, max) => {
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 && n <= max ? n : null;
};

/** 시청자 → 송출자 보고 문자열. 측정하지 못한 값은 넣지 않는다(0 으로 채우지 않음). */
export function buildReceipt({ phase, stats, hidden } = {}) {
  const o = { v: 1, phase: RECEIPT_PHASES.includes(phase) ? phase : 'playing' };
  if (o.phase === 'playing' && stats) {
    for (const k of ['w', 'h', 'fps', 'kbps', 'lossPct', 'dropped']) if (stats[k] !== null && stats[k] !== undefined) o[k] = stats[k];
  }
  if (hidden) o.hidden = true;
  return JSON.stringify(o);
}

/** 송출자 측 검증. 알 수 없는 버전·phase, 과대 payload, 범위 밖 수치는 null/제외. */
export function parseReceipt(data) {
  if (typeof data !== 'string' || !data || data.length > MAX_DATA_LENGTH) return null;
  let o;
  try { o = JSON.parse(data); } catch (e) { return null; }
  if (!o || typeof o !== 'object' || o.v !== 1 || !RECEIPT_PHASES.includes(o.phase)) return null;
  const stats = {
    w: num(o.w, 16384), h: num(o.h, 16384), fps: num(o.fps, 240), kbps: num(o.kbps, 1000000),
    lossPct: num(o.lossPct, 100), dropped: num(o.dropped, 100000),
  };
  const measured = Object.values(stats).some(v => v !== null);
  return { phase: o.phase, hidden: o.hidden === true, stats: measured ? stats : null };
}

/** getStats() 결과에서 화면공유 영상 inbound-rtp 한 건(가장 큰 프레임) — 표준 필드만 사용. */
export function pickRtp(report, type) {
  let best = null;
  const visit = (r) => {
    if (!r || r.type !== type || (r.kind || r.mediaType) !== 'video') return;
    if (!best || (r.frameWidth || 0) > (best.frameWidth || 0)) best = r;
  };
  if (report && typeof report.forEach === 'function') report.forEach(visit);
  else if (Array.isArray(report)) report.forEach(visit);
  return best;
}

const round1 = (v) => Math.round(v * 10) / 10;

/** 두 inbound-rtp 표본 → 수신 해상도·fps·실측 kbps·구간 손실률·구간 드롭. 첫 표본(prev 없음)은 누적값이 필요한 항목을 null 로 둔다. */
export function summarizeInbound(prev, cur) {
  if (!cur) return null;
  const dt = prev && cur.timestamp > prev.timestamp ? (cur.timestamp - prev.timestamp) / 1000 : 0;
  const d = (k) => (dt && Number.isFinite(cur[k]) && Number.isFinite(prev[k]) ? Math.max(0, cur[k] - prev[k]) : null);
  const bytes = d('bytesReceived');
  const lost = d('packetsLost');
  const recv = d('packetsReceived');
  const decoded = d('framesDecoded');
  return {
    w: cur.frameWidth || null,
    h: cur.frameHeight || null,
    fps: Number.isFinite(cur.framesPerSecond) ? round1(cur.framesPerSecond) : (decoded !== null ? round1(decoded / dt) : null),
    kbps: bytes !== null ? Math.round((bytes * 8) / dt / 1000) : null,
    lossPct: lost !== null && recv !== null && lost + recv > 0 ? round1((lost / (lost + recv)) * 100) : null,
    dropped: d('framesDropped'),
  };
}

/** 송출자 outbound-rtp 두 표본 → 서버(미디어 서버)로 보내는 해상도·fps·kbps·화질 제한 사유. */
export function summarizeOutbound(prev, cur) {
  if (!cur) return null;
  const dt = prev && cur.timestamp > prev.timestamp ? (cur.timestamp - prev.timestamp) / 1000 : 0;
  const bytes = dt && Number.isFinite(cur.bytesSent) && Number.isFinite(prev.bytesSent) ? Math.max(0, cur.bytesSent - prev.bytesSent) : null;
  return {
    w: cur.frameWidth || null,
    h: cur.frameHeight || null,
    fps: Number.isFinite(cur.framesPerSecond) ? round1(cur.framesPerSecond) : null,
    kbps: bytes !== null ? Math.round((bytes * 8) / dt / 1000) : null,
    limitation: typeof cur.qualityLimitationReason === 'string' ? cur.qualityLimitationReason : null,
  };
}

const STATE_RANK = { playing: 5, hidden: 4, subscribed: 3, stale: 2, stopped: 1, waiting: 0, 'no-response': 0 };

/**
 * 송출자 화면 모델. 미리보기·Publisher 생성만으로는 절대 "수신 확인됨"이 되지 않는다 — 원격 playing 보고가 있어야 한다.
 *  share: { status:'starting'|'live', step:'capture'|'connect', health:'ok'|'connecting'|'unstable'|'reconnecting'|'failed', liveSince }
 *  viewers: [{ userKey, name, deviceType, connectionIds:[], since }]  (나 자신·내 다른 기기 제외, 고유 userId 단위)
 *  receipts: { [viewerConnectionId]: { userKey, phase, hidden, stats, at } }
 */
export function deriveShareReceipt({ share, viewers = [], receipts = {}, now = Date.now() }) {
  const empty = { viewers: [], playing: 0, subscribed: 0, measured: 0, waiting: 0, notWatching: 0 };
  if (!share || share.status === 'idle') return { ...empty, phase: 'idle', expected: 0 };
  if (share.status === 'starting') return { ...empty, phase: share.step === 'capture' ? 'capturing' : 'connecting', expected: viewers.length };
  const liveSince = Number.isFinite(share.liveSince) ? share.liveSince : now;
  const rows = viewers.map((v) => {
    let best = null;
    for (const cid of v.connectionIds || []) {
      const r = receipts[cid];
      if (!r || String(r.userKey) !== String(v.userKey)) continue;
      let state = r.phase;
      if (state === 'playing') {
        if (now - r.at > RECEIPT_STALE_MS) state = 'stale';
        else if (r.hidden) state = 'hidden';
      }
      if (!best || STATE_RANK[state] > STATE_RANK[best.state]) best = { state, stats: state === 'playing' || state === 'hidden' ? r.stats : null, at: r.at };
    }
    if (!best) best = { state: now - Math.max(liveSince, v.since || 0) < RECEIPT_WAIT_MS ? 'waiting' : 'no-response', stats: null, at: null };
    return { ...v, ...best };
  });
  const playing = rows.filter(r => r.state === 'playing' || r.state === 'hidden').length;
  const subscribed = rows.filter(r => r.state !== 'waiting' && r.state !== 'no-response').length;
  const measured = rows.filter(r => r.stats && (r.stats.kbps !== null || r.stats.w !== null)).length;
  // 방금 구독만 알린 시청자는 곧 playing 을 보낼 수 있으므로 잠시 "대기"로 본다.
  const waiting = rows.filter(r => r.state === 'waiting' || (r.state === 'subscribed' && r.at !== null && now - r.at < RECEIPT_WAIT_MS)).length;
  // 응답은 했지만 지금 이 화면을 그리지 않는 시청자(다른 공유 선택·보기 중단) — 확인 불가가 아니라 "보는 사람 없음"이다.
  const notWatching = rows.filter(r => r.state === 'stopped' || (r.state === 'subscribed' && !(r.at !== null && now - r.at < RECEIPT_WAIT_MS))).length;
  let phase;
  if (share.health === 'failed' || share.health === 'reconnecting' || share.health === 'unstable') phase = 'failed';
  else if (share.health === 'connecting') phase = 'connecting';
  else if (playing > 0) phase = 'received';
  else if (rows.length === 0 || waiting > 0 || notWatching === rows.length) phase = 'sending';
  else phase = 'unverified';
  return { phase, viewers: rows, expected: rows.length, playing, subscribed, measured, waiting, notWatching };
}

/** 원격 PeerConnection 상태 → 송출 건강 상태. */
export function healthFromPeerState(state) {
  if (state === 'connected') return 'ok';
  if (state === 'failed') return 'failed';
  if (state === 'disconnected') return 'unstable';
  return 'connecting'; // new | connecting
}
