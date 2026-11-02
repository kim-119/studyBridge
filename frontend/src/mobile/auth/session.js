import { AUTH_TOKENS_REFRESHED_EVENT, refreshAccessToken } from '../../services/api';
import { shareSessionWithNative, signOutNativeStudy, watchNativeAccessTokenRequests } from '../platform/nativeStudy';
import { clearSessionOnDevice, persistSessionToDevice, restoreSessionFromDevice } from '../platform/tokenStore';
import { NATIVE_STUDY_SYNC, isSessionOrphaned, planNativeStudySync } from './sessionRecovery';

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

function warnNativeStudySyncFailure(error) {
  console.warn('[session] 네이티브 학습 기능과 세션을 동기화하지 못했습니다.', error);
}

function syncNativeStudySession({ isAuthChange }) {
  const token = localStorage.getItem('token');
  const plan = planNativeStudySync({
    token,
    refreshToken: localStorage.getItem('refreshToken'),
    isAuthChange,
  });

  if (plan === NATIVE_STUDY_SYNC.SHARE) {
    shareSessionWithNative(token).catch(warnNativeStudySyncFailure);
  } else if (plan === NATIVE_STUDY_SYNC.SIGN_OUT) {
    signOutNativeStudy().catch(warnNativeStudySyncFailure);
  }
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
    syncNativeStudySession({ isAuthChange: true });
  };

  const refreshForNativeStudy = () => {
    if (!hasStoredCredentials()) return;
    refreshAccessToken().catch((error) => {
      console.warn('[session] 네이티브 학습 기능용 토큰을 갱신하지 못했습니다.', error);
    });
  };

  window.addEventListener(AUTH_CHANGE_EVENT, syncToDevice);
  window.addEventListener(AUTH_TOKENS_REFRESHED_EVENT, syncToDevice);
  const stopWatchingNativeRequests = watchNativeAccessTokenRequests(refreshForNativeStudy);
  syncNativeStudySession({ isAuthChange: false });

  return () => {
    window.removeEventListener(AUTH_CHANGE_EVENT, syncToDevice);
    window.removeEventListener(AUTH_TOKENS_REFRESHED_EVENT, syncToDevice);
    stopWatchingNativeRequests();
  };
}
