import { Capacitor, registerPlugin } from '@capacitor/core';

const StudyBridgeMedia = registerPlugin('StudyBridgeMedia');

const WEB_FALLBACK = { granted: true, camera: 'granted', microphone: 'granted' };

export async function checkMediaPermissions() {
  if (!Capacitor.isNativePlatform()) return WEB_FALLBACK;
  return StudyBridgeMedia.checkMediaPermissions();
}

export async function requestMediaPermissions() {
  if (!Capacitor.isNativePlatform()) return WEB_FALLBACK;
  return StudyBridgeMedia.requestMediaPermissions();
}

export async function startVoiceSession({ speakerphone = true } = {}) {
  if (!Capacitor.isNativePlatform()) return { active: false, speakerphone };
  return StudyBridgeMedia.startVoiceSession({ speakerphone });
}

export async function stopVoiceSession() {
  if (!Capacitor.isNativePlatform()) return { active: false, speakerphone: false };
  return StudyBridgeMedia.stopVoiceSession();
}

export async function setSpeakerphone(enabled) {
  if (!Capacitor.isNativePlatform()) return { active: false, speakerphone: enabled };
  return StudyBridgeMedia.setSpeakerphone({ enabled });
}
