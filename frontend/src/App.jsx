import React, { useEffect, useState } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { authService } from './services/api';

import Navbar from './components/Navbar';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import MyPage from './pages/MyPage';
import StudyMate from './pages/StudyMate';
import GroupStudy from './pages/GroupStudy';
import Materials from './pages/Materials';

function PrivateRoute({ children }) {
  const { isLoggedIn } = useAuth();
  return isLoggedIn ? children : <Navigate to="/login" replace />;
}

function App() {
  const { logout, updateUser } = useAuth();
  const [isAuthChecking, setIsAuthChecking] = useState(true);

  useEffect(() => {
    const initAuth = async () => {
      const storedUser = localStorage.getItem("user");
      const userId = localStorage.getItem("userId");
      const token = localStorage.getItem("token");

      if (!userId && !token) {
        logout();
        setIsAuthChecking(false);
        return;
      }

      try {
        if (userId) {
          const profile = await authService.getProfile(userId);
          updateUser(profile);
        } else {
          throw new Error('유효한 사용자 ID가 없습니다.');
        }
      } catch (e) {
        console.warn('기존 로그인 세션이 유효하지 않습니다. 자동 로그아웃됩니다.');
        logout();
      } finally {
        setIsAuthChecking(false);
      }
    };

    initAuth();
  }, []);

  if (isAuthChecking) {
    return <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh', color: 'var(--color-primary)', fontWeight: 'bold' }}>Loading...</div>;
  }

  return (
    <div className="app-container">
      <Navbar />

      <main style={{ paddingTop: '80px' }}>
        <Routes>
          {/* 메인페이지: 누구나 접근 가능 */}
          <Route path="/" element={<Dashboard />} />

          {/* 인증 페이지 */}
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />

          {/* 로그인 필요 페이지 */}
          <Route
            path="/mypage"
            element={
              <PrivateRoute>
                <MyPage />
              </PrivateRoute>
            }
          />

          <Route path="/studymate" element={<StudyMate />} />
          <Route path="/groupstudy" element={<GroupStudy />} />

          <Route path="/materials" element={<Materials />} />

          {/* 잘못된 주소는 메인으로 이동 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;