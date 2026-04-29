import { useState, useEffect } from 'react';

export function useAuth() {
  const [userId, setUserId] = useState(localStorage.getItem('userId'));
  const [userEmail, setUserEmail] = useState(localStorage.getItem('userEmail'));

  useEffect(() => {
    const handleAuthChange = () => {
      setUserId(localStorage.getItem('userId'));
      setUserEmail(localStorage.getItem('userEmail'));
    };

    window.addEventListener('auth-change', handleAuthChange);
    return () => window.removeEventListener('auth-change', handleAuthChange);
  }, []);

  const login = (id, email) => {
    localStorage.setItem('userId', id);
    localStorage.setItem('userEmail', email);
    window.dispatchEvent(new Event('auth-change'));
  };

  const logout = () => {
    localStorage.removeItem('userId');
    localStorage.removeItem('userEmail');
    window.dispatchEvent(new Event('auth-change'));
  };

  return { userId, userEmail, login, logout };
}
