import React, { useCallback, useEffect, useRef, useState } from 'react';
import { authService, bannerService } from '../services/api';
import { useAuth } from '../hooks/useAuth';
import { hasStoredCredentials, restoreSession, watchSessionChanges } from './auth/session';
import { withTimeout } from './data/withTimeout';
import { getNetworkStatus } from './platform/connectivity';
import { hideSplashScreen } from './platform/nativeShell';

const STATUS = {
  CHECKING: 'checking',
  READY: 'ready',
  OFFLINE: 'offline',
  UNREACHABLE: 'unreachable',
};

const BOOT_TIMEOUT_MS = 8000;

const FAILURE_MESSAGE = {
  [STATUS.OFFLINE]: [
    '네트워크에 연결되어 있지 않습니다.',
    '연결 상태를 확인한 뒤 다시 시도해주세요.',
  ],
  [STATUS.UNREACHABLE]: [
    '서버에 연결할 수 없습니다.',
    '잠시 후 다시 시도해주세요.',
  ],
};

function isAuthenticationFailure(error) {
  return error?.response?.status === 401 || error?.message === 'No refresh token';
}

function isSuspended(profile) {
  if (profile?.status === 'BANNED' || profile?.status === 'SUSPENDED') return true;
  return Boolean(profile?.suspensionEndDate && new Date(profile.suspensionEndDate) > new Date());
}

export default function MobileBoot({ children }) {
  const [status, setStatus] = useState(STATUS.CHECKING);
  const { logout, updateUser } = useAuth();

  const authActions = useRef({ logout, updateUser });
  authActions.current = { logout, updateUser };

  const bootstrap = useCallback(async () => {
    setStatus(STATUS.CHECKING);

    try {
      await restoreSession();
      await withTimeout(bannerService.getMainBanner(), BOOT_TIMEOUT_MS);

      if (hasStoredCredentials()) {
        try {
          const profile = await withTimeout(authService.getProfile(), BOOT_TIMEOUT_MS);

          if (isSuspended(profile)) {
            authActions.current.logout();
          } else {
            authActions.current.updateUser(profile);
          }
        } catch (sessionError) {
          if (isAuthenticationFailure(sessionError)) {
            console.warn('[boot] 저장된 세션이 만료되어 로그아웃합니다.', sessionError);
            authActions.current.logout();
          } else {
            console.warn('[boot] 프로필을 갱신하지 못해 저장된 사용자 정보로 계속합니다.', sessionError);
          }
        }
      } else if (localStorage.getItem('userId')) {
        authActions.current.logout();
      }

      setStatus(STATUS.READY);
    } catch (error) {
      console.warn('StudyBridge 서버에 연결하지 못했습니다.', error);
      const network = await getNetworkStatus();
      setStatus(network.connected ? STATUS.UNREACHABLE : STATUS.OFFLINE);
    } finally {
      await hideSplashScreen();
    }
  }, []);

  useEffect(() => {
    const stopWatching = watchSessionChanges({
      onSessionOrphaned: () => authActions.current.logout(),
    });
    bootstrap();
    return stopWatching;
  }, [bootstrap]);

  if (status === STATUS.CHECKING) {
    return (
      <div className="mobile-boot">
        <span className="mobile-boot__brand">StudyBridge</span>
        <p className="mobile-boot__message">학습을 하나로 잇다</p>
      </div>
    );
  }

  if (status !== STATUS.READY) {
    return (
      <div className="mobile-boot">
        <span className="mobile-boot__brand">StudyBridge</span>
        <p className="mobile-boot__message">
          {FAILURE_MESSAGE[status].map((line) => (
            <span key={line}>{line}</span>
          ))}
        </p>
        <button type="button" className="mobile-boot__retry" onClick={bootstrap}>
          다시 시도
        </button>
      </div>
    );
  }

  return children;
}
