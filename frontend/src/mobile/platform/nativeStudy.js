import { Capacitor, registerPlugin } from '@capacitor/core';

const StudyNative = registerPlugin('StudyBridgeStudyNative');
const ACCESS_TOKEN_REQUESTED_EVENT = 'accessTokenRequested';

export function isNativeStudyAvailable() {
  return Capacitor.isNativePlatform() && Capacitor.isPluginAvailable('StudyBridgeStudyNative');
}

export async function shareSessionWithNative(accessToken) {
  if (!isNativeStudyAvailable() || !accessToken) return;
  await StudyNative.shareSession({ accessToken });
}

export async function signOutNativeStudy() {
  if (!isNativeStudyAvailable()) return;
  await StudyNative.signOut();
}

export async function openNativeReminderSettings() {
  if (!isNativeStudyAvailable()) return false;
  await StudyNative.openReminderSettings();
  return true;
}

export function watchNativeAccessTokenRequests(onRequested) {
  if (!isNativeStudyAvailable()) return () => {};

  const handle = StudyNative.addListener(ACCESS_TOKEN_REQUESTED_EVENT, onRequested);
  return () => {
    Promise.resolve(handle).then((listener) => listener.remove());
  };
}
