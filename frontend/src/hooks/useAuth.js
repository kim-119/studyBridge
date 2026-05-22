import { useState, useEffect } from 'react';

export const normalizeUser = (raw) => ({
  ...raw,
  id: raw.id || raw.userId,
  userId: raw.userId || raw.id,
  displayName: raw.displayName || raw.display_name || raw.name || raw.nickname || '',
  email: raw.email || '',
  major: raw.major || ''
});

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
