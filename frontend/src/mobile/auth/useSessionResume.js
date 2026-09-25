import { useEffect, useRef } from 'react';
import { authService } from '../../services/api';
import { useAuth } from '../../hooks/useAuth';
import { withTimeout } from '../data/withTimeout';
import { registerAppStateChange } from '../platform/nativeShell';
import { hasStoredCredentials } from './session';

const RESUME_TIMEOUT_MS = 8000;

export function useSessionResume() {
  const { logout } = useAuth();
  const logoutRef = useRef(logout);
  logoutRef.current = logout;

  useEffect(() => {
    return registerAppStateChange(async ({ isActive }) => {
      if (!isActive || !hasStoredCredentials()) return;

      try {
        await withTimeout(authService.getProfile(), RESUME_TIMEOUT_MS);
      } catch (error) {
        if (error?.response?.status === 401) {
          console.warn('백그라운드 복귀 후 세션이 만료되어 로그아웃합니다.', error);
          logoutRef.current();
        }
      }
    });
  }, []);
}
