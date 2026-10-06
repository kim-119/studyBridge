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

const DEVICE_ERROR_MESSAGE = {
  NotAllowedError: '카메라 또는 마이크 권한이 거부되었습니다. 설정에서 권한을 허용해주세요.',
  PermissionDeniedError: '카메라 또는 마이크 권한이 거부되었습니다. 설정에서 권한을 허용해주세요.',
  NotFoundError: '사용할 수 있는 카메라 또는 마이크를 찾지 못했습니다.',
  DevicesNotFoundError: '사용할 수 있는 카메라 또는 마이크를 찾지 못했습니다.',
  NotReadableError: '카메라 또는 마이크를 다른 앱이 사용 중입니다.',
  TrackStartError: '카메라 또는 마이크를 다른 앱이 사용 중입니다.',
  OverconstrainedError: '이 기기에서 지원하지 않는 카메라 설정입니다.',
};

export function describeDeviceError(error) {
  if (error?.name && DEVICE_ERROR_MESSAGE[error.name]) return DEVICE_ERROR_MESSAGE[error.name];
  if (error?.message?.toLowerCase().includes('permission')) return DEVICE_ERROR_MESSAGE.NotAllowedError;
  return null;
}

export const PERMISSION_DENIED_MESSAGE = DEVICE_ERROR_MESSAGE.NotAllowedError;
