import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
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
            <Link to="/studymate" className="nav-link">
              학습메이트
            </Link>
            <Link to="/groupstudy" className="nav-link">
              그룹스터디
            </Link>
            <Link to="/archive" className="nav-link">
              자료보관함
            </Link>
            <Link to="/knowledge" className="nav-link">
              지식공유
            </Link>
          </div>
        </div>

        {/* 🔹 우측 */}
        <div className="nav-right">
          {userEmail ? (
            <>
              <Link to="/admin" className="nav-link" style={{ display: 'flex', alignItems: 'center', gap: '4px', color: '#10B981', fontWeight: 'bold' }}>
                <ShieldAlert size={16} />
                관리자
              </Link>
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