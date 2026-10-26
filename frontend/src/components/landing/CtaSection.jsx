import React from 'react';
import { useNavigate } from 'react-router-dom';

/**
 * CTA 섹션 (레퍼런스 톤).
 *  - 페이지 배경 위 연그린 그라데이션(from-green-50 → green-100) 라운드 카드.
 *  - 제목 + 부제 + "무료로 시작하기" 그린 버튼(중앙). 이동 경로는 우리 것.
 */
export default function CtaSection() {
  const navigate = useNavigate();

  return (
    <section className="mx-auto max-w-6xl px-6 pb-20">
      <div className="rounded-2xl bg-gradient-to-b from-green-50 to-green-100 px-6 py-14 text-center">
        <h2 className="text-2xl font-bold text-gray-900 md:text-3xl">지금 바로 AI 학습 루틴을 만들어보세요</h2>
        <p className="mt-3 text-gray-500">StudyBridge와 함께라면 더 적은 시간으로 더 나은 결과를 얻을 수 있습니다.</p>
        <button
          onClick={() => navigate('/login')}
          className="mt-8 rounded-[10px] bg-green-500 px-6 py-3 text-sm font-semibold text-white transition hover:bg-green-600"
        >
          무료로 시작하기
        </button>
      </div>
    </section>
  );
}
