import React from 'react';
import { Link, useNavigate } from 'react-router-dom';

export default function Navbar() {
  const navigate = useNavigate();
  const userEmail = localStorage.getItem('userEmail');

  const handleLogout = () => {
    localStorage.removeItem('userEmail');
    navigate('/');
  };

  return (
    <nav style={styles.nav}>
      <div style={styles.inner}>
        {/* 🔹 좌측 */}
        <div style={styles.left}>
          <Link to="/" style={styles.logo}>
            StudyBridge
          </Link>

          {userEmail && (
            <Link to="/group" style={styles.link}>
              그룹게시판
            </Link>
          )}
        </div>

        {/* 🔹 우측 */}
        <div style={styles.right}>
          {userEmail ? (
            <>
              {/* 🔥 이메일 클릭 → 마이페이지 */}
              <Link to="/mypage" style={styles.user}>
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
              <Link to="/login" style={styles.link}>로그인</Link>
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

const styles = {
  nav: {
    position: 'fixed',
    top: 0,
    left: 0,
    width: '100%',
    height: '64px',
    background: '#fff',
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 1000,
  },
  inner: {
    width: '100%',
    maxWidth: '1200px',
    padding: '0 24px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },

  left: {
    display: 'flex',
    alignItems: 'center',
    gap: '20px',
  },

  right: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
  },

  logo: {
    fontSize: '18px',
    fontWeight: '700',
    color: 'var(--color-text-main)',
    textDecoration: 'none',
  },

  link: {
    fontSize: '14px',
    color: 'var(--color-text-main)',
    textDecoration: 'none',
    fontWeight: 500,
  },

  user: {
    fontSize: '14px',
    color: 'var(--color-text-muted)',
    textDecoration: 'none',
    cursor: 'pointer',
  },
};