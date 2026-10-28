import { Capacitor, registerPlugin } from '@capacitor/core';

// 네이티브 화면공유(android/screenshare). -PsbScreenShare=true 로 빌드한 APK 에만 플러그인이 있다.
const PLUGIN_NAME = 'StudyBridgeScreenShare';
const StudyBridgeScreenShare = registerPlugin(PLUGIN_NAME);

export function isNativeScreenShareAvailable() {
  try {
    return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable(PLUGIN_NAME);
  } catch {
    return false;
  }
}

export function getScreenShareStatus() {
  return StudyBridgeScreenShare.getStatus();
}

export function requestScreenShareNotificationPermission() {
  return StudyBridgeScreenShare.requestNotificationPermission();
}

export function requestScreenCaptureConsent() {
  return StudyBridgeScreenShare.requestConsent();
}

export function discardScreenCaptureConsent() {
  return StudyBridgeScreenShare.discardConsent();
}

export function startNativeScreenShare(options) {
  return StudyBridgeScreenShare.start(options);
}

export function stopNativeScreenShare() {
  return StudyBridgeScreenShare.stop();
}

/** 상태 이벤트 구독. 해제 함수를 돌려준다. */
export function onScreenShareStateChange(listener) {
  const handle = StudyBridgeScreenShare.addListener('stateChange', listener);
  return () => {
    Promise.resolve(handle)
      .then((subscription) => subscription?.remove?.())
      .catch(() => {});
  };
}
