import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';

import Navbar from './components/Navbar';
import Login from './pages/Login';
import Register from './pages/Register';
import Dashboard from './pages/Dashboard';
import MyPage from './pages/MyPage';
import StudyMate from './pages/StudyMate';
import GroupStudy from './pages/GroupStudy';

function PrivateRoute({ children }) {
  const isLogin = localStorage.getItem('userEmail');

  return isLogin ? children : <Navigate to="/login" replace />;
}

function App() {
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

          <Route
            path="/studymate"
            element={
              <PrivateRoute>
                <StudyMate />
              </PrivateRoute>
            }
          />

          <Route
            path="/groupstudy"
            element={
              <PrivateRoute>
                <GroupStudy />
              </PrivateRoute>
            }
          />

          {/* 잘못된 주소는 메인으로 이동 */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;