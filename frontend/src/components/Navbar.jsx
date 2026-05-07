import React from 'react';
import { Link, useNavigate } from 'react-router-dom';

export default function Navbar() {
  const navigate = useNavigate();
  const userEmail = localStorage.getItem('userEmail');

  const handleLogout = () => {
    localStorage.clear();
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
          <div style={{ display: 'flex', gap: '16px', marginLeft: '16px' }}>
            <Link to="/studymate" className="nav-link">
              학습메이트
            </Link>
            <Link to="/groupstudy" className="nav-link">
              그룹스터디
            </Link>
          </div>
        </div>

        {/* 🔹 우측 */}
        <div className="nav-right">
          {userEmail ? (
            <>
              {/* 🔥 이메일 클릭 → 마이페이지 */}
              <Link to="/mypage" className="nav-user">
                {userEmail}
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