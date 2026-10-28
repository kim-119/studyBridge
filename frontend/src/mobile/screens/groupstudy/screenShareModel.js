// Android 네이티브 화면공유 송출 모델(순수 함수). 서버 계약은 EC2 GroupVideoCallService(LLM-clean):
//  POST   /api/groups/{g}/video/screen-token { primaryConnectionId, clientInstanceId, deviceType } → { token, connectionId, maxSendKbps, screenShareLimit }
//  DELETE /api/groups/{g}/video/screen/{connectionId}  (멱등 종료)
//  GET    /api/groups/{g}/video/connections            → { screenShareCount, screenShareLimit, connections[] }
// 그룹당 화면공유 한도·사용자당 1개·발급 후 30초 안 접속(예약 만료)은 서버가 판정한다. 앱의 사전 확인은 안내용이다.

export const SHARE_PHASE = Object.freeze({
  IDLE: 'idle',
  CHECKING: 'checking', // 서버 슬롯 확인
  CONSENT: 'consent', // 시스템 화면 녹화 동의창
  CONNECTING: 'connecting', // 토큰 발급 → 네이티브 송출 연결
  PUBLISHING: 'publishing',
  STOPPING: 'stopping',
});

export const SCREEN_DEVICE_TYPE = 'ANDROID';
const INSTANCE_ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

/** 서버 연결 목록으로 미리 막을 수 있는 경우만 판정한다(최종 판정은 토큰 발급 시 서버). */
export function precheckScreenShare(connectionsResponse, userId) {
  const limit = Number(connectionsResponse?.screenShareLimit) || 2;
  const count = Number(connectionsResponse?.screenShareCount) || 0;
  const mine = (connectionsResponse?.connections || []).some(
    (connection) => connection?.kind === 'SCREEN' && String(connection.userId) === String(userId)
  );
  if (mine) return { ok: false, message: '다른 기기에서 이미 화면을 공유하고 있습니다. 그 기기에서 공유를 끝낸 뒤 다시 시도해 주세요.' };
  if (count >= limit) return { ok: false, message: `현재 화면공유 가능 인원(최대 ${limit}명)이 모두 사용 중입니다.` };
  return { ok: true, limit, count };
}

export function screenClientInstanceId(random = Math.random, now = Date.now()) {
  const suffix = Array.from({ length: 10 }, () => Math.floor(random() * 36).toString(36)).join('');
  const id = `and-scr-${now.toString(36)}-${suffix}`;
  return INSTANCE_ID_PATTERN.test(id) ? id : id.slice(0, 64);
}

/** 웹 화면공유와 같은 clientData 형식(표시용). 신원·종류는 서버 serverData 가 정한다. */
export function buildScreenShareStart({ tokenResponse, iceServers, userId, displayName }) {
  if (!tokenResponse?.token) throw new Error('화면공유 토큰을 받지 못했습니다.');
  return {
    token: tokenResponse.token,
    connectionId: tokenResponse.connectionId || null,
    metadata: JSON.stringify({ userId: String(userId), clientData: displayName || '참여자', kind: 'SCREEN' }),
    iceServers: Array.isArray(iceServers) ? iceServers : [],
    maxSendKbps: Number(tokenResponse.maxSendKbps) || undefined,
  };
}

const SERVER_MESSAGES = {
  NOT_GROUP_MEMBER: '그룹스터디 참여 멤버만 화면을 공유할 수 있습니다.',
  CONNECTION_OWNER_MISMATCH: '내 화상 연결을 확인하지 못했습니다. 방에 다시 들어온 뒤 시도해 주세요.',
  INVALID_CONNECTION_ID: '화상 연결 정보가 올바르지 않습니다. 방에 다시 들어온 뒤 시도해 주세요.',
  PRIMARY_NOT_ACTIVE: '화상 연결이 활성화된 뒤에 화면을 공유할 수 있습니다. 잠시 후 다시 시도해 주세요.',
  SCREEN_ALREADY_ACTIVE: '이미 화면을 공유하고 있습니다.',
  SCREEN_START_IN_PROGRESS: '다른 기기에서 화면공유를 시작하고 있습니다. 잠시 후 다시 시도해 주세요.',
  SCREEN_SHARE_LIMIT_REACHED: null, // 서버 메시지(최대 N명)를 그대로 쓴다
};

const NATIVE_MESSAGES = {
  ALREADY_SHARING: '이미 화면을 공유하고 있습니다.',
  CONSENT_REQUIRED: '화면 녹화 동의가 만료되었습니다. 다시 시작해 주세요.',
  UNSUPPORTED: '이 기기는 화면공유를 지원하지 않습니다.',
  SERVICE_START_FAILED: '화면공유 서비스를 시작하지 못했습니다.',
  INVALID_REQUEST: '화면공유 요청 정보가 올바르지 않습니다.',
};

export function describeScreenShareError(error) {
  const body = error?.response?.data || {};
  if (body.code && body.code in SERVER_MESSAGES) return SERVER_MESSAGES[body.code] || body.message || '화면공유를 시작할 수 없습니다.';
  if (error?.code && NATIVE_MESSAGES[error.code]) return NATIVE_MESSAGES[error.code];
  const status = error?.status || error?.response?.status;
  if (status === 401) return '로그인이 만료되었습니다. 다시 로그인해 주세요.';
  if (status === 403) return '화면을 공유할 권한이 없습니다.';
  if (status === 409) return body.message || '지금은 화면공유를 시작할 수 없습니다.';
  if (status >= 500) return '화면공유 서버에 일시적인 문제가 있습니다. 잠시 후 다시 시도해 주세요.';
  if (error?.response === undefined && error?.message === 'Network Error') return '서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.';
  return error?.message || '화면공유를 시작하지 못했습니다.';
}

/** 네이티브 stateChange → 화면 단계. idle 이면서 사용자가 직접 끈 경우가 아니면 종료 사유를 안내한다. */
export function phaseFromNative(status) {
  switch (status?.state) {
    case 'starting':
    case 'connecting':
      return SHARE_PHASE.CONNECTING;
    case 'publishing':
      return SHARE_PHASE.PUBLISHING;
    case 'stopping':
      return SHARE_PHASE.STOPPING;
    default:
      return SHARE_PHASE.IDLE;
  }
}

export function stopNoticeFrom(status) {
  if (!status || status.state !== 'idle' || !status.reason) return null;
  if (status.reason === 'user-stopped') return null;
  return status.message || '화면공유가 종료되었습니다.';
}

/** 내 화면공유 연결(내 PRIMARY 소유 SCREEN)은 구독·타일 표시하지 않는다(웹 isOwnScreen 과 같은 규칙). */
export function isOwnScreenConnection(identity, myPrimaryConnectionId) {
  return Boolean(
    identity?.kind === 'SCREEN' && myPrimaryConnectionId && identity.ownerConnectionId === myPrimaryConnectionId
  );
}

const PHASE_MESSAGES = {
  [SHARE_PHASE.CHECKING]: '화면공유 가능 인원을 확인하고 있습니다.',
  [SHARE_PHASE.CONSENT]: '시스템 창에서 공유할 화면(전체 화면 또는 앱)을 선택해 주세요.',
  [SHARE_PHASE.CONNECTING]: '화면공유를 연결하고 있습니다.',
  [SHARE_PHASE.PUBLISHING]: '내 화면을 공유하고 있습니다. 다른 앱으로 이동해도 공유가 계속됩니다.',
  [SHARE_PHASE.STOPPING]: '화면공유를 종료하고 있습니다.',
};

export function describeSharePhase(phase) {
  return PHASE_MESSAGES[phase] || null;
}

export function canStopShare(phase) {
  return phase === SHARE_PHASE.CONNECTING || phase === SHARE_PHASE.PUBLISHING;
}
