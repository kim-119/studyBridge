// OpenVidu Connection 식별 계약(v1) — 서버(Spring VideoConnectionMetadata)·웹(utils/videoConnection.js, LLM-clean)과 같은 규칙.
//
//  connection.data = clientData | serverData | `${clientData}%/%${serverData}`
//   · serverData: Spring 이 토큰 발급 시 기록(위조 불가) {v, app:'studybridge', groupId, userId, kind, ownerConnectionId, ...}
//   · clientData: 접속 기기가 보내는 표시용 {userId, clientData(이름), ...}
//  신원(userId)·연결 종류(kind)는 serverData 만 신뢰한다. 서버가 붙인 경우 항상 마지막 세그먼트가 serverData 다.
//  serverData 가 없는 연결은 계약 이전 발급분(레거시)이라 clientData 로 표시만 한다.

export const CONNECTION_KIND = Object.freeze({ PRIMARY: 'PRIMARY', SCREEN: 'SCREEN' });

const SEPARATOR = '%/%';
const CONTRACT_APP = 'studybridge';

function parseObject(text) {
  if (typeof text !== 'string' || !text) return null;
  try {
    const value = JSON.parse(text);
    return value && typeof value === 'object' && !Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

const isServerData = (value) => Boolean(value) && value.app === CONTRACT_APP && value.userId != null;

export function parseConnectionIdentity(connection) {
  const raw = typeof connection === 'string' ? connection : connection?.data;
  let client = null;
  let server = null;

  if (typeof raw === 'string' && raw) {
    const parts = raw.split(SEPARATOR);
    const last = parseObject(parts[parts.length - 1]);
    if (isServerData(last)) {
      server = last;
      client = parts.length > 1 ? parseObject(parts.slice(0, -1).join(SEPARATOR)) : null;
    } else {
      client = parseObject(parts[0]) || last;
    }
  }

  const verified = Boolean(server);
  const userId = verified ? server.userId : client?.userId ?? null;

  return {
    verified,
    userId: userId === '' || userId == null ? null : String(userId),
    kind: verified && server.kind === CONNECTION_KIND.SCREEN ? CONNECTION_KIND.SCREEN : CONNECTION_KIND.PRIMARY,
    ownerConnectionId: verified ? server.ownerConnectionId || null : null,
    deviceType: verified ? server.deviceType || 'UNKNOWN' : 'UNKNOWN',
    name: client?.clientData || client?.name || client?.nickname || null,
  };
}

// 단일 SCREEN 판정 규칙:
//  1) 서버가 SCREEN 토큰으로 발급한 연결(serverData.kind=SCREEN)이면 typeOfVideo 와 무관하게 SCREEN
//     (네이티브 libwebrtc 송출은 typeOfVideo 가 CUSTOM 등으로 올 수 있어 서버 값이 우선한다).
//  2) 그 외(PRIMARY·레거시)는 스트림 typeOfVideo='SCREEN' 일 때만 SCREEN. CUSTOM·IPCAM·누락은 카메라.
export function isScreenConnection(identity, stream) {
  if (identity?.kind === CONNECTION_KIND.SCREEN) return true;
  return String(stream?.typeOfVideo || '').toUpperCase() === 'SCREEN';
}
