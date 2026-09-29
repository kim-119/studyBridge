export const MEDIA_PHASE = {
  IDLE: 'idle',
  CONNECTING: 'connecting',
  CONNECTED: 'connected',
  RECONNECTING: 'reconnecting',
  FAILED: 'failed',
};

export const MEDIA_ACTION = {
  CONNECT_STARTED: 'connect-started',
  CONNECTED: 'connected',
  CONNECT_FAILED: 'connect-failed',
  RECONNECT_SCHEDULED: 'reconnect-scheduled',
  NOTICE_CHANGED: 'notice-changed',
  LEFT: 'left',
};

export const INITIAL_MEDIA_STATE = {
  phase: MEDIA_PHASE.IDLE,
  errorMessage: null,
  notice: null,
  reconnectAttempt: 0,
};

export const DEVICE_TOGGLE = {
  NONE: 'none',
  MUTE: 'mute',
  UNMUTE: 'unmute',
  REPUBLISH: 'republish',
};

export function mediaSessionReducer(state, action) {
  switch (action.type) {
    case MEDIA_ACTION.CONNECT_STARTED:
      return {
        ...state,
        phase: action.isReconnect ? MEDIA_PHASE.RECONNECTING : MEDIA_PHASE.CONNECTING,
        errorMessage: null,
      };
    case MEDIA_ACTION.CONNECTED:
      return { ...state, phase: MEDIA_PHASE.CONNECTED, errorMessage: null, reconnectAttempt: 0 };
    case MEDIA_ACTION.CONNECT_FAILED:
      return { ...state, phase: MEDIA_PHASE.FAILED, errorMessage: action.message, reconnectAttempt: 0 };
    case MEDIA_ACTION.RECONNECT_SCHEDULED:
      return { ...state, phase: MEDIA_PHASE.RECONNECTING, reconnectAttempt: action.attempt };
    case MEDIA_ACTION.NOTICE_CHANGED:
      return { ...state, notice: action.message || null };
    case MEDIA_ACTION.LEFT:
      return INITIAL_MEDIA_STATE;
    default:
      return state;
  }
}

function isPermissionGranted(value, fallback) {
  if (value === undefined || value === null) return Boolean(fallback);
  return value === 'granted';
}

export function resolvePermissionGrants(result) {
  return {
    camera: isPermissionGranted(result?.camera, result?.granted),
    microphone: isPermissionGranted(result?.microphone, result?.granted),
  };
}

function joinDeviceNames(names) {
  return names.join('와 ');
}

export function describeMissingPermissions({ wantsCamera, wantsMicrophone, grants }) {
  const missing = [
    wantsCamera && !grants.camera ? '카메라' : null,
    wantsMicrophone && !grants.microphone ? '마이크' : null,
  ].filter(Boolean);

  if (missing.length === 0) return null;
  return `${joinDeviceNames(missing)} 권한이 없어 끈 상태로 참여했습니다. 기기 설정에서 권한을 허용하면 다시 켤 수 있습니다.`;
}

export function planLocalMedia({ wantsCamera, wantsMicrophone, grants }) {
  const useCamera = Boolean(wantsCamera && grants.camera);
  const useMicrophone = Boolean(wantsMicrophone && grants.microphone);

  return {
    useCamera,
    useMicrophone,
    shouldPublish: useCamera || useMicrophone,
    notice: describeMissingPermissions({ wantsCamera, wantsMicrophone, grants }),
  };
}

export function withoutCamera(plan, reason) {
  return {
    ...plan,
    useCamera: false,
    shouldPublish: plan.useMicrophone,
    notice: reason ? `${reason} 카메라 없이 참여합니다.` : plan.notice,
  };
}

export function publishAttempts({ useCamera, useMicrophone }) {
  const candidates = [
    { useCamera, useMicrophone },
    { useCamera: false, useMicrophone },
    { useCamera, useMicrophone: false },
  ];
  const seen = new Set();

  return candidates.filter((candidate) => {
    const key = `${candidate.useCamera}-${candidate.useMicrophone}`;
    const hasAnyDevice = candidate.useCamera || candidate.useMicrophone;
    if (!hasAnyDevice || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function planDeviceToggle({ enable, hasPublisher, hasTrack }) {
  if (!enable) return hasPublisher ? DEVICE_TOGGLE.MUTE : DEVICE_TOGGLE.NONE;
  if (hasPublisher && hasTrack) return DEVICE_TOGGLE.UNMUTE;
  return DEVICE_TOGGLE.REPUBLISH;
}

export function describeMediaStatus({ phase, errorMessage, reconnectAttempt }) {
  switch (phase) {
    case MEDIA_PHASE.CONNECTING:
      return '화상 연결 중입니다. 채팅과 자료는 바로 사용할 수 있습니다.';
    case MEDIA_PHASE.RECONNECTING:
      return `화상 연결이 끊겨 다시 연결하는 중입니다${reconnectAttempt ? ` (${reconnectAttempt}회차)` : ''}.`;
    case MEDIA_PHASE.FAILED:
      return `화상 연결에 실패했습니다. ${errorMessage || ''} 채팅·AI·자료는 계속 사용할 수 있습니다.`.replace(/\s+/g, ' ');
    default:
      return null;
  }
}
