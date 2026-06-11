import React from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { Sparkles, ShieldAlert } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function Navbar() {
  const navigate = useNavigate();
  const { user, userEmail, logout } = useAuth();
  
  const displayText = user?.displayName || user?.display_name || user?.name || user?.nickname || user?.email || userEmail;

  const handleLogout = () => {
    logout();
    window.location.href = '/';
  };

  return (
    <nav className="nav-container">
      <div className="nav-inner">
        {/* 🔹 좌측 */}
        <div className="nav-left">
          <Link to="/" className="nav-logo">
            StudyBridge
          </Link>
          <div className="nav-links">
            {[
              { to: '/studymate', label: '학습메이트' },
              { to: '/groupstudy', label: '그룹스터디' },
              { to: '/archive', label: '자료보관함' },
              { to: '/knowledge', label: '지식공유' },
              { to: '/study-report', label: '학습리포트' },
              { to: '/weekly-schedule', label: '주간일정' },
              { to: '/planner', label: '플래너' },
            ].map(({ to, label }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) => 'nav-link' + (isActive ? ' active' : '')}
              >
                {label}
              </NavLink>
            ))}
          </div>
        </div>

        {/* 🔹 우측 */}
        <div className="nav-right">
          {userEmail ? (
            <>

              <Link to="/mypage" className="nav-user">
                {displayText}
              </Link>

              <button
                className="btn-primary"
                onClick={handleLogout}
                style={{ width: '80px', height: '36px', fontSize: '12px' }}
              >
                로그아웃
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="nav-link">로그인</Link>
              <Link
                to="/register"
                className="btn-primary"
                style={{ width: '80px', height: '36px', fontSize: '12px' }}
              >
                가입하기
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}