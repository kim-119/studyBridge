// 그룹스터디 OpenVidu Connection 식별 계약(v1) — Spring VideoConnectionMetadata 와 동일한 규칙(웹·Android 공통).
//
//  connection.data = clientData | serverData | `${clientData}%/%${serverData}`
//   · serverData(Spring 이 토큰 발급 시 기록, 위조 불가): {v, app:'studybridge', groupId, userId, kind, ownerConnectionId, instanceId, deviceType, issuedAt}
//   · clientData(브라우저가 connect 시 보내는 표시용): {userId, clientData(이름), avatarMode, avatarUrl, avatarValue, kind?}
//  신원(userId / kind / ownerConnectionId)은 serverData 만 신뢰한다. serverData 가 없는 Connection 은 배포 이전 발급분(레거시)이다.
//
//  모델: Group Member(DB) ≠ Active User(접속 중인 고유 userId) ≠ Connection(기기·탭마다 PRIMARY 1개 + 화면공유 SCREEN 0~1개).

export const CONNECTION_KIND = Object.freeze({ PRIMARY: 'PRIMARY', SCREEN: 'SCREEN' });
export const METADATA_SEPARATOR = '%/%';
const CONTRACT_APP = 'studybridge';
const INSTANCE_KEY = 'sb-ov-instance-id';
const INSTANCE_RE = /^[A-Za-z0-9_-]{8,64}$/;

const tryParseObject = (s) => {
  if (typeof s !== 'string' || !s) return null;
  try {
    const v = JSON.parse(s);
    return v && typeof v === 'object' && !Array.isArray(v) ? v : null;
  } catch (e) {
    return null;
  }
};

const isContract = (o) => !!o && o.app === CONTRACT_APP && o.userId !== undefined && o.userId !== null;

/**
 * connection.data 문자열 → 식별/표시 메타데이터.
 * 서버가 serverData 를 붙인 경우 항상 마지막 세그먼트가 serverData 다(clientData 안에 구분자를 넣어 위조해도 마지막은 서버 값).
 */
export function parseConnectionMetadata(raw) {
  let client = null;
  let server = null;
  if (typeof raw === 'string' && raw) {
    const parts = raw.split(METADATA_SEPARATOR);
    if (parts.length >= 2) {
      const last = tryParseObject(parts[parts.length - 1]);
      if (isContract(last)) server = last;
      client = tryParseObject(parts.slice(0, -1).join(METADATA_SEPARATOR));
      if (!server && !client) client = last; // 계약이 아닌 두 조각 — 레거시 clientData 로 취급
    } else {
      const only = tryParseObject(raw);
      if (isContract(only)) server = only;
      else client = only;
    }
  }
  const verified = !!server;
  const userId = verified ? server.userId : (client?.userId ?? null);
  const kind = verified && server.kind === CONNECTION_KIND.SCREEN ? CONNECTION_KIND.SCREEN : CONNECTION_KIND.PRIMARY;
  return {
    userId: userId === '' ? null : userId,
    userKey: userId === null || userId === undefined || userId === '' ? null : String(userId),
    verified,
    kind,
    ownerConnectionId: verified ? (server.ownerConnectionId || null) : null,
    instanceId: verified ? (server.instanceId || null) : null,
    deviceType: verified ? (server.deviceType || 'UNKNOWN') : 'UNKNOWN',
    name: client?.clientData || client?.name || client?.nickname || null,
    micOn: client?.micOn,
    cameraOn: client?.cameraOn,
    avatarMode: typeof client?.avatarMode === 'string' ? client.avatarMode : null,
    avatarUrl: typeof client?.avatarUrl === 'string' ? client.avatarUrl : null,
    avatarValue: typeof client?.avatarValue === 'string' ? client.avatarValue : null,
  };
}

const randomId = () => {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID().replace(/-/g, '');
  } catch (e) { /* fall through */ }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
};

/** 탭 인스턴스 id(sessionStorage: 새로고침해도 유지, 탭마다 다름). 저장소가 막혀 있으면 이번 페이지 한정 id. */
export function getClientInstanceId(storage) {
  const store = storage === undefined ? (typeof sessionStorage !== 'undefined' ? sessionStorage : null) : storage;
  try {
    const v = store?.getItem(INSTANCE_KEY);
    if (v && INSTANCE_RE.test(v)) return v;
  } catch (e) { /* storage blocked */ }
  const id = randomId();
  try { store?.setItem(INSTANCE_KEY, id); } catch (e) { /* storage blocked */ }
  return id;
}

/** 서버 계약 deviceType(WEB | ANDROID | IOS). Capacitor/웹뷰도 UA 기준으로 분류한다. */
export function detectDeviceType(userAgent) {
  const ua = String(userAgent ?? (typeof navigator !== 'undefined' ? navigator.userAgent : '') ?? '');
  if (/Android/i.test(ua)) return 'ANDROID';
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/i.test(ua) && /Mobile/i.test(ua))) return 'IOS';
  return 'WEB';
}

export const deviceLabel = (deviceType) => ({ ANDROID: 'Android', IOS: 'iOS', WEB: 'PC' }[deviceType] || '다른 기기');

/**
 * openvidu-browser 2.30 의 join 경쟁 조건 방어(Session 내부 API, 버전 고정 2.30.0).
 *
 * 새로고침하면 이전 탭의 Connection 은 서버에 ~10초 남는다(WS 재연결 유예). 그 사이 같은 사용자가 다시 join 하면 서버는 join 처리 중에
 * 이전 Connection 을 ghost 로 판정해 제거하고 participantLeft/participantEvicted 를 "join 응답보다 먼저" 보낸 뒤, join 응답의 기존 참가자
 * 목록에는 그 ghost 를 그대로 넣는다. openvidu-browser 는 모르는 connectionId 의 participantLeft 를 버리고(또 participantEvicted 는
 * this.connection 미정 상태라 TypeError), join 응답으로 ghost 를 만들어 영구 타일이 된다.
 * → join 완료 전에 도착한 Left/Evicted 의 connectionId 를 tombstone 으로 기록해 connectionCreated/streamCreated 에서 무시한다.
 * 반드시 session.connect() 호출 전에 설치해야 한다(OpenVidu.startWs 가 connect 시점에 핸들러를 bind 한다).
 */
export function installEarlyLeaveGuard(session) {
  const tombstones = new Set();
  if (!session || typeof session.onParticipantLeft !== 'function') {
    return { tombstones, isTombstoned: () => false };
  }
  const origLeft = session.onParticipantLeft.bind(session);
  const origEvicted = typeof session.onParticipantEvicted === 'function' ? session.onParticipantEvicted.bind(session) : null;
  const known = (id) => {
    try { return !!session.remoteConnections?.has?.(id); } catch (e) { return false; }
  };
  session.onParticipantLeft = (event) => {
    const id = event?.connectionId;
    if (id && !session.connection && !known(id)) {
      tombstones.add(id);
      return; // 아직 join 응답 전: 모르는 연결의 퇴장 → 기록만 하고 라이브러리 오류 로그를 건너뛴다
    }
    return origLeft(event);
  };
  if (origEvicted) {
    session.onParticipantEvicted = (event) => {
      const id = event?.connectionId;
      if (!session.connection) {
        if (id) tombstones.add(id);
        return; // this.connection 미정 → 원본은 TypeError
      }
      return origEvicted(event);
    };
  }
  return { tombstones, isTombstoned: (id) => !!id && tombstones.has(id) };
}

/** join 응답으로 이미 생성된 tombstone 연결을 라이브러리 내부 맵에서도 걷어낸다(이후 이벤트·구독 시도 차단). */
export function purgeTombstonedConnections(session, tombstones) {
  const purged = [];
  for (const id of tombstones || []) {
    try {
      const conn = session?.remoteConnections?.get?.(id);
      if (!conn) continue;
      const streamId = conn.stream?.streamId;
      if (streamId) session.remoteStreamsCreated?.delete?.(streamId);
      try { conn.dispose?.(); } catch (e) { /* ignore */ }
      session.remoteConnections.delete(id);
      purged.push(id);
    } catch (e) { /* ignore */ }
  }
  return purged;
}

/**
 * 서버(OpenVidu active Connection) 목록과 로컬 연결 맵 비교 → 제거할 원격 connectionId.
 * fetch 시작 전에 이미 알고 있던(seenAt < fetchStartedAt) 연결만 지운다: fetch 도중 새로 들어온 연결을 잘못 지우지 않기 위함.
 */
export function planReconcile(localConnections, serverConnectionIds, fetchStartedAt) {
  const alive = new Set(serverConnectionIds || []);
  const prune = [];
  for (const [cid, c] of Object.entries(localConnections || {})) {
    if (!c || c.isMe || c.isMine) continue;
    const seenAt = Number(c.connectedAt) || 0;
    if (seenAt < fetchStartedAt && !alive.has(cid)) prune.push(cid);
  }
  return prune;
}

/**
 * 로컬 연결 맵 → 화면 모델.
 *  · participantCount: PRIMARY 연결의 고유 userId 수(+ 나). 화면공유(SCREEN)·두 번째 기기는 인원을 늘리지 않는다.
 *  · primary: 타일 대상(기기마다 1개). 같은 사용자가 여러 기기로 접속하면 multiDevice=true.
 *  · screens: 화면공유 연결.
 */
export function deriveRoomPresence(connections, myUserId) {
  const entries = Object.entries(connections || {});
  const primary = [];
  const screens = [];
  const devicesByUser = new Map();
  for (const [cid, c] of entries) {
    if (!c) continue;
    if (c.kind === CONNECTION_KIND.SCREEN) { screens.push([cid, c]); continue; }
    primary.push([cid, c]);
    const key = c.userId === null || c.userId === undefined ? `conn:${cid}` : String(c.userId);
    devicesByUser.set(key, (devicesByUser.get(key) || 0) + 1);
  }
  const activeUserKeys = new Set(devicesByUser.keys());
  if (myUserId !== null && myUserId !== undefined && myUserId !== '') activeUserKeys.add(String(myUserId));
  const multiDevice = (c, cid) => {
    const key = c.userId === null || c.userId === undefined ? `conn:${cid}` : String(c.userId);
    return (devicesByUser.get(key) || 0) > 1;
  };
  return {
    participantCount: activeUserKeys.size,
    activeUserKeys,
    primary: primary.map(([cid, c]) => [cid, { ...c, multiDevice: multiDevice(c, cid) }]),
    screens,
  };
}
