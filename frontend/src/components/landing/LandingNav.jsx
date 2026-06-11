import React from 'react';
import { Link, useNavigate } from 'react-router-dom';

/**
 * 랜딩 전용 상단 네비게이션 (레퍼런스 톤).
 *  - 배경은 페이지와 동일한 #F5F6F7, 보더 없음, 높이 64px(h-16).
 *  - 좌 로고(그린) / 중앙 메뉴(주요 기능 활성 언더라인) / 우 로그인 + 시작하기.
 *  - 메인(/)에서만 사용하며 글로벌 Navbar는 App.jsx에서 숨긴다.
 */
export default function LandingNav() {
  const navigate = useNavigate();

  return (
    <header className="sticky top-0 z-20" style={{ backgroundColor: '#F5F6F7' }}>
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <Link to="/" className="text-xl font-extrabold text-green-600">StudyBridge</Link>

        <nav className="hidden items-center gap-8 text-sm md:flex">
          <a href="#features" className="border-b-2 border-green-500 pb-1 font-semibold text-green-600">주요 기능</a>
          <a href="#" className="text-gray-500 hover:text-gray-900">요금제</a>
          <a href="#" className="text-gray-500 hover:text-gray-900">학습 커뮤니티</a>
        </nav>

        <div className="flex items-center gap-4">
          <button onClick={() => navigate('/login')} className="text-sm text-gray-500 hover:text-gray-900">로그인</button>
          <button
            onClick={() => navigate('/login')}
            className="rounded-[10px] bg-green-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-green-600"
          >
            시작하기
          </button>
        </div>
      </div>
    </header>
  );
}
