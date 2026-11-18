import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

/**
 * CTA 섹션 (레퍼런스 톤).
 *  - 페이지 배경 위 연그린 그라데이션(from-green-50 → green-100) 라운드 카드.
 *  - 제목 + 부제 + "무료로 시작하기" 그린 버튼(중앙). 이동 경로는 우리 것.
 */
export default function CtaSection() {
  const navigate = useNavigate();
  // 로그인 판단은 useAuth(App.jsx initAuth 가 기동 시 프로필 조회로 검증·만료 시 logout 한 상태)를 단일 출처로 쓴다.
  //  · 로그인 상태 → 서비스 메인(/studymate, 히어로 '시작하기'와 동일 목적지)
  //  · 비로그인  → /login (로그인 후 /studymate 로 복귀)
  const { isLoggedIn } = useAuth();
  const handleStart = () => {
    if (isLoggedIn) navigate('/studymate');
    else navigate('/login', { state: { from: '/studymate' } });
  };

  return (
    <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
      <div className="rounded-2xl bg-gradient-to-b from-green-50 to-green-100 px-6 py-14 text-center">
        <h2 className="text-2xl font-bold text-gray-900 md:text-3xl">지금 바로 AI 학습 루틴을 만들어보세요</h2>
        <p className="mt-3 text-gray-500">StudyBridge와 함께라면 더 적은 시간으로 더 나은 결과를 얻을 수 있습니다.</p>
        <button
          onClick={handleStart}
          className="mt-8 rounded-[10px] bg-green-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-green-600"
        >
          무료로 시작하기
        </button>
      </div>
    </section>
  );
}
