import { AUTH_TOKENS_REFRESHED_EVENT } from '../../services/api';
import { clearSessionOnDevice, persistSessionToDevice, restoreSessionFromDevice } from '../platform/tokenStore';
import { isSessionOrphaned } from './sessionRecovery';

const AUTH_CHANGE_EVENT = 'auth-change';

export async function restoreSession() {
  try {
    await restoreSessionFromDevice();
  } catch (error) {
    console.warn('[session] 기기에 저장된 세션을 복구하지 못했습니다.', error);
  }
}

export function hasStoredCredentials() {
  return Boolean(localStorage.getItem('token') || localStorage.getItem('refreshToken'));
}

function readSessionSnapshot() {
  return {
    userId: localStorage.getItem('userId'),
    token: localStorage.getItem('token'),
    refreshToken: localStorage.getItem('refreshToken'),
  };
}

export function watchSessionChanges({ onSessionOrphaned }) {
  const syncToDevice = () => {
    if (isSessionOrphaned(readSessionSnapshot())) {
      onSessionOrphaned();
      return;
    }

    const persist = hasStoredCredentials() ? persistSessionToDevice : clearSessionOnDevice;
    persist().catch((error) => {
      console.warn('[session] 세션을 기기 저장소와 동기화하지 못했습니다.', error);
    });
  };

  window.addEventListener(AUTH_CHANGE_EVENT, syncToDevice);
  window.addEventListener(AUTH_TOKENS_REFRESHED_EVENT, syncToDevice);

  return () => {
    window.removeEventListener(AUTH_CHANGE_EVENT, syncToDevice);
    window.removeEventListener(AUTH_TOKENS_REFRESHED_EVENT, syncToDevice);
  };
}
