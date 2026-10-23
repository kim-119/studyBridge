export const FACING_MODE = {
  FRONT: 'user',
  BACK: 'environment',
};

export function oppositeFacingMode(facingMode) {
  return facingMode === FACING_MODE.BACK ? FACING_MODE.FRONT : FACING_MODE.BACK;
}

export function hasMediaDevices() {
  return Boolean(navigator.mediaDevices?.getUserMedia);
}

export async function acquireCameraStream(facingMode) {
  return navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: facingMode } },
    audio: false,
  });
}

export async function acquireCameraTrack(facingMode) {
  const stream = await acquireCameraStream(facingMode);
  return stream.getVideoTracks()[0];
}

export function stopStream(stream) {
  stream?.getTracks().forEach((track) => track.stop());
}

export function cloneLiveVideoTrack(stream) {
  const track = stream?.getVideoTracks()[0];
  return track && track.readyState === 'live' ? track.clone() : null;
}

const DEVICE_NAME = {
  camera: '카메라',
  microphone: '마이크',
};

const ANY_DEVICE_NAME = '카메라 또는 마이크';

const DEVICE_ERROR_KIND = {
  NotAllowedError: 'denied',
  PermissionDeniedError: 'denied',
  NotFoundError: 'missing',
  DevicesNotFoundError: 'missing',
  NotReadableError: 'busy',
  TrackStartError: 'busy',
  OverconstrainedError: 'unsupported',
};

const DEVICE_ERROR_MESSAGE_BUILDERS = {
  denied: (deviceName) => `${deviceName} 권한이 거부되었습니다. 설정에서 권한을 허용해주세요.`,
  missing: (deviceName) => `사용할 수 있는 ${deviceName}를 찾지 못했습니다.`,
  busy: (deviceName) => `${deviceName}를 다른 앱이 사용 중입니다.`,
  unsupported: () => '이 기기에서 지원하지 않는 카메라 설정입니다.',
};

function deviceErrorKind(error) {
  if (error?.name && DEVICE_ERROR_KIND[error.name]) return DEVICE_ERROR_KIND[error.name];
  if (error?.message?.toLowerCase().includes('permission')) return 'denied';
  return null;
}

export function describeDeviceError(error, device) {
  const kind = deviceErrorKind(error);
  if (!kind) return null;
  return DEVICE_ERROR_MESSAGE_BUILDERS[kind](DEVICE_NAME[device] || ANY_DEVICE_NAME);
}

export const PERMISSION_DENIED_MESSAGE = DEVICE_ERROR_MESSAGE_BUILDERS.denied(ANY_DEVICE_NAME);
