import React from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { ShieldAlert } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

/**
 * 공용 상단 네비게이션 (랜딩 디자인 톤으로 일원화).
 *  - 로고는 항상 green-600, 탭 항목은 앱 네비(학습메이트~플래너) 그대로.
 *  - 로그인은 보더 버튼, 시작하기·로그아웃은 그린 채움 버튼.
 *  - authed/username/active prop으로 분기하며, 미전달 시 useAuth/useLocation에서 자동 도출.
 */
const NAV_ITEMS = [
  { to: '/studymate', label: '학습메이트' },
  { to: '/groupstudy', label: '그룹스터디' },
  { to: '/archive', label: '자료보관함' },
  { to: '/review-notes', label: '오답노트' },
  { to: '/knowledge', label: '지식공유' },
  { to: '/study-report', label: '학습리포트' },
  { to: '/weekly-schedule', label: '주간일정' },
  { to: '/planner', label: '플래너' },
];

export function Navbar({ authed, username, active }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, userEmail, logout } = useAuth();

  // prop 미전달 시 인증/표시명/활성경로를 자동으로 도출
  const isAuthed = authed ?? Boolean(userEmail);
  const displayName =
    username ??
    user?.displayName ?? user?.display_name ?? user?.name ?? user?.nickname ?? user?.email ?? userEmail;
  const activePath = active ?? location.pathname;
  const isAdmin = user?.role === 'ADMIN' || user?.role === 'ROLE_ADMIN';

  const handleLogout = () => {
    logout();
    window.location.href = '/';
  };

  // 비로그인 사용자가 보호 탭을 누르면 이동을 막고 로그인 화면으로 보낸다(원래 경로 보존).
  const handleNavClick = (e, to) => {
    if (!isAuthed) {
      e.preventDefault();
      navigate('/login', { state: { from: to } });
    }
  };

  return (
    <header className="fixed inset-x-0 top-0 z-30 border-b border-gray-100" style={{ backgroundColor: '#F5F6F7' }}>
      <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6">
        {/* 좌측: 로고 + 탭 */}
        <div className="flex items-center gap-8">
          <Link to="/" className="text-xl font-extrabold text-green-600">StudyBridge</Link>

          <nav className="hidden items-center gap-6 text-sm lg:flex">
            {NAV_ITEMS.map(({ to, label }) => {
              const isActive = activePath === to || activePath.startsWith(`${to}/`);
              return (
                <Link
                  key={to}
                  to={to}
                  onClick={(e) => handleNavClick(e, to)}
                  className={
                    'pb-1 transition ' +
                    (isActive
                      ? 'border-b-2 border-green-500 font-semibold text-green-600'
                      : 'font-medium text-gray-500 hover:text-gray-900')
                  }
                >
                  {label}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* 우측: 인증 분기 */}
        <div className="flex items-center gap-3">
          {isAuthed ? (
            <>
              {isAdmin && (
                <Link
                  to="/admin"
                  className="flex items-center gap-1 text-sm font-semibold text-red-500 transition hover:text-red-600"
                >
                  <ShieldAlert size={16} />
                  관리자
                </Link>
              )}
              <Link to="/mypage" className="text-sm font-medium text-gray-700 transition hover:text-green-600">
                {displayName}
              </Link>
              <button
                onClick={handleLogout}
                className="rounded-[10px] bg-green-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-600"
              >
                로그아웃
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => navigate('/login')}
                className="rounded-[10px] border border-gray-300 px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-green-500 hover:text-green-600"
              >
                로그인
              </button>
              <button
                onClick={() => navigate('/register')}
                className="rounded-[10px] bg-green-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-600"
              >
                시작하기
              </button>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

export default Navbar;
