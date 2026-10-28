import { useState, useEffect } from 'react';
import { authService } from '../services/api';

export const normalizeUser = (raw) => ({
  ...raw,
  id: raw.id || raw.userId,
  userId: raw.userId || raw.id,
  displayName: raw.displayName || raw.display_name || raw.name || raw.nickname || '',
  email: raw.email || '',
  major: raw.major || '',
  photoUrl: raw.photoUrl || raw.photo_url || '',
  role: raw.role || 'USER'
});

const isExhibitUser = () => {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null')?.exhibitAccount === true;
  } catch (e) {
    return false;
  }
};

export function useAuth() {
  const [user, setUser] = useState(() => {
    const saved = localStorage.getItem('user');
    return saved ? JSON.parse(saved) : null;
  });

  const userId = localStorage.getItem('userId');
  const userEmail = localStorage.getItem('userEmail');

  useEffect(() => {
    const handleAuthChange = () => {
      const saved = localStorage.getItem('user');
      setUser(saved ? JSON.parse(saved) : null);
    };

    window.addEventListener('auth-change', handleAuthChange);
    return () => window.removeEventListener('auth-change', handleAuthChange);
  }, []);

  const login = (userData) => {
    localStorage.setItem('user', JSON.stringify(userData));
    localStorage.setItem('userId', userData.userId || userData.id);
    localStorage.setItem('userEmail', userData.email);
    if (userData.accessToken) {
      localStorage.setItem('token', userData.accessToken);
    }
    if (userData.refreshToken) {
      localStorage.setItem('refreshToken', userData.refreshToken);
    }
    window.dispatchEvent(new Event('auth-change'));
  };

  const logout = () => {
    // 체험 계정은 서버의 이 기기 세션 슬롯을 반환한다(토큰을 지우기 전에). 일반 사용자는 기존대로 로컬 정리만 한다.
    if (isExhibitUser()) authService.releaseExhibitSession();
    localStorage.removeItem('user');
    localStorage.removeItem('userId');
    localStorage.removeItem('userEmail');
    localStorage.removeItem('userName');
    localStorage.removeItem('userMajor');
    localStorage.removeItem('token');
    localStorage.removeItem('refreshToken');
    sessionStorage.clear();
    window.dispatchEvent(new Event('auth-change'));
  };

  const updateUser = (newUser) => {
    const normalized = normalizeUser({
      ...user,
      ...newUser
    });
    setUser(normalized);
    localStorage.setItem('user', JSON.stringify(normalized));
    localStorage.setItem('userId', normalized.userId);
    localStorage.setItem('userEmail', normalized.email);
    window.dispatchEvent(new Event('auth-change'));
  };

  return { 
    user,
    userId: user?.userId || user?.id || userId, 
    userEmail: user?.email || userEmail, 
    login, 
    logout,
    updateUser,
    isLoggedIn: !!(user || userId) 
  };
}
