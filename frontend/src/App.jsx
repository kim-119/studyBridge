import React, { useEffect, useState } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './hooks/useAuth';
import { authService } from './services/api';

import Navbar from './components/Navbar';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import MyPage from './pages/MyPage';
import AdminPage from './pages/AdminPage';
import StudyMate from './pages/StudyMate';
import LearningMate from './pages/LearningMate';
import GroupStudy from './pages/GroupStudy';
import Archive from './pages/Archive';
import ArchiveDetail from './pages/ArchiveDetail';
import Knowledge from './pages/Knowledge';
import KnowledgeDetail from './pages/KnowledgeDetail';
import StudyReport from './pages/StudyReport';
import WeeklySchedule from './pages/WeeklySchedule';
import Planner from './pages/Planner';
import ReviewNotesPage from './pages/ReviewNotesPage';
function PrivateRoute({ children }) {
  const { isLoggedIn } = useAuth();
  const location = useLocation();
  return isLoggedIn ? children : <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />;
}

function AdminRoute({ children }) {
  const { isLoggedIn, user } = useAuth();
  if (!isLoggedIn) return <Navigate to="/login" replace />;
  const isAdmin = user?.role === 'ADMIN' || user?.role === 'ROLE_ADMIN';
  return isAdmin ? children : <Navigate to="/" replace />;
}

function App() {
  const { logout, updateUser } = useAuth();
  const [isAuthChecking, setIsAuthChecking] = useState(true);
  const location = useLocation();
  const isAdminRoute = location.pathname.startsWith('/admin');

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
          if (profile.status === 'BANNED' || profile.status === 'SUSPENDED' || (profile.suspensionEndDate && new Date(profile.suspensionEndDate) > new Date())) {
            console.warn('제재된 계정입니다. 자동 로그아웃됩니다.');
            logout();
            setIsAuthChecking(false);
            return;
          }
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

  // Hide Navbar and top padding for Archive Detail pages to make it full screen
  const hideNavbar = location.pathname.includes('/archive/pdf/') || location.pathname.includes('/archive/journal/') || location.pathname.includes('/archive/reviewNote/') || location.pathname.includes('/archive/mindmap/');

  return (
    <div className={isAdminRoute ? "" : "app-container"} style={isAdminRoute ? { width: '100%', height: '100vh', overflow: 'hidden' } : {}}>
      {(!isAdminRoute && !hideNavbar) && <Navbar />}

      <main style={isAdminRoute ? { height: '100vh', display: 'flex' } : { paddingTop: hideNavbar ? '0' : '80px', height: hideNavbar ? '100vh' : 'auto' }}>
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

          <Route path="/admin" element={<AdminRoute><AdminPage /></AdminRoute>} />
          <Route path="/studymate" element={<PrivateRoute><StudyMate /></PrivateRoute>} />
          <Route path="/learning-mate" element={<PrivateRoute><LearningMate /></PrivateRoute>} />
          <Route path="/groupstudy" element={<PrivateRoute><GroupStudy /></PrivateRoute>} />
          <Route path="/archive" element={<PrivateRoute><Archive /></PrivateRoute>} />
          <Route path="/archive/:type/:id" element={<PrivateRoute><ArchiveDetail /></PrivateRoute>} />
          <Route path="/review-notes" element={<PrivateRoute><ReviewNotesPage /></PrivateRoute>} />
          <Route path="/knowledge" element={<PrivateRoute><Knowledge /></PrivateRoute>} />
          <Route path="/knowledge/:id" element={<PrivateRoute><KnowledgeDetail /></PrivateRoute>} />

          {/* 학습 플래너 관련 신규 탭 */}
          <Route path="/study-report" element={<PrivateRoute><StudyReport /></PrivateRoute>} />
          <Route path="/weekly-schedule" element={<PrivateRoute><WeeklySchedule /></PrivateRoute>} />
          <Route path="/planner" element={<PrivateRoute><Planner /></PrivateRoute>} />
          {/* 잘못된 주소는 메인으로 이동 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;