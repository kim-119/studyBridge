import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { ShieldAlert, Menu, X } from 'lucide-react';
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
  { to: '/mindmap', label: '마인드맵' },
];

export function Navbar({ authed, username, active }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { user, userEmail, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  // 경로가 바뀌면 모바일 드로어를 닫는다(탭 이동 후 잔류 방지).
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname]);

  // prop 미전달 시 인증/표시명/활성경로를 자동으로 도출
  const isAuthed = authed ?? Boolean(userEmail);
  const displayName =
    username ??
    user?.displayName ?? user?.display_name ?? user?.name ?? user?.nickname ?? user?.email ?? userEmail;
  const activePath = active ?? location.pathname;
  const isAdmin = user?.role === 'ADMIN' || user?.role === 'ROLE_ADMIN';

  const handleLogout = () => {
    setMenuOpen(false);
    logout();
    window.location.href = '/';
  };

  // 비로그인 사용자가 보호 탭을 누르면 이동을 막고 로그인 화면으로 보낸다(원래 경로 보존).
  const handleNavClick = (e, to) => {
    setMenuOpen(false);
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

        {/* 우측: 인증 분기(데스크톱·태블릿) + 모바일 햄버거 */}
        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-3 md:flex">
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

          {/* 모바일 햄버거 버튼: lg 미만에서만 노출 */}
          <button
            type="button"
            aria-label={menuOpen ? '메뉴 닫기' : '메뉴 열기'}
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((v) => !v)}
            className="inline-flex items-center justify-center rounded-[10px] p-2 text-gray-700 transition hover:bg-gray-100 lg:hidden"
          >
            {menuOpen ? <X size={24} /> : <Menu size={24} />}
          </button>
        </div>
      </div>

      {/* 모바일 드로어: 햄버거 열림 시 헤더 아래로 펼쳐짐 */}
      {menuOpen && (
        <div className="lg:hidden">
          {/* 배경 오버레이(탭 외 영역 클릭 시 닫힘) */}
          <button
            type="button"
            aria-label="메뉴 닫기"
            onClick={() => setMenuOpen(false)}
            className="fixed inset-0 top-20 z-20 bg-black/20"
          />
          <nav className="relative z-30 max-h-[calc(100vh-5rem)] overflow-y-auto border-b border-gray-100 bg-white px-4 py-3 shadow-lg">
            {NAV_ITEMS.map(({ to, label }) => {
              const isActive = activePath === to || activePath.startsWith(`${to}/`);
              return (
                <Link
                  key={to}
                  to={to}
                  onClick={(e) => handleNavClick(e, to)}
                  className={
                    'block rounded-[10px] px-3 py-3 text-base transition ' +
                    (isActive
                      ? 'bg-green-50 font-semibold text-green-600'
                      : 'font-medium text-gray-700 hover:bg-gray-50')
                  }
                >
                  {label}
                </Link>
              );
            })}

            {/* 인증 액션(모바일) */}
            <div className="mt-2 border-t border-gray-100 pt-3">
              {isAuthed ? (
                <>
                  {isAdmin && (
                    <Link
                      to="/admin"
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center gap-1 rounded-[10px] px-3 py-3 text-base font-semibold text-red-500 transition hover:bg-red-50"
                    >
                      <ShieldAlert size={18} />
                      관리자
                    </Link>
                  )}
                  <Link
                    to="/mypage"
                    onClick={() => setMenuOpen(false)}
                    className="block rounded-[10px] px-3 py-3 text-base font-medium text-gray-700 transition hover:bg-gray-50"
                  >
                    {displayName}
                  </Link>
                  <button
                    onClick={handleLogout}
                    className="mt-1 w-full rounded-[10px] bg-green-500 px-4 py-3 text-base font-semibold text-white transition hover:bg-green-600"
                  >
                    로그아웃
                  </button>
                </>
              ) : (
                <div className="flex flex-col gap-2">
                  <button
                    onClick={() => { setMenuOpen(false); navigate('/login'); }}
                    className="w-full rounded-[10px] border border-gray-300 px-4 py-3 text-base font-semibold text-gray-700 transition hover:border-green-500 hover:text-green-600"
                  >
                    로그인
                  </button>
                  <button
                    onClick={() => { setMenuOpen(false); navigate('/register'); }}
                    className="w-full rounded-[10px] bg-green-500 px-4 py-3 text-base font-semibold text-white transition hover:bg-green-600"
                  >
                    시작하기
                  </button>
                </div>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}

export default Navbar;
