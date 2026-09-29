import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, Upload, FileUp, FileText, Route, HelpCircle, GraduationCap,
} from 'lucide-react';

/**
 * 메인 배너 (Hero).
 *  - 좌: 헤드라인(검정 + 그린 그라데이션) · 설명 · CTA 2개(시작하기 / 자료 업로드)
 *  - 우: 흰 카드 + 브랜드 로고(이미지) + 2x2 기능 칩
 *  - 헤드라인/설명/버튼 문구는 지정 카피를 그대로 사용한다.
 *    (백엔드 /api/banners/main 은 다른 문구를 반환하고 이번엔 백엔드 수정 범위가 아니므로 프론트에서 확정한다.)
 *  - 우측 로고는 env(VITE_MAIN_LOGO_URL) 이미지를 쓰되, 값이 없거나 로딩 실패 시
 *    기본 아이콘으로 fallback 한다. (랜딩 전체를 로고 값에 의존시키지 않는다.)
 */
const FEATURES = [
  { label: '자료 업로드', to: '/archive', Icon: FileUp },
  { label: '핵심 요약', to: '/studymate', Icon: FileText },
  { label: '맞춤 로드맵', to: '/studymate', Icon: Route },
  { label: '복습 퀴즈', to: '/studymate', Icon: HelpCircle },
];

export default function MainBanner() {
  const navigate = useNavigate();

  // 로고: env 우선, 실패 시 기본 아이콘 fallback (조건부 렌더링은 로고 영역에만 적용).
  const mainLogoUrl = import.meta.env.VITE_MAIN_LOGO_URL;
  const [logoError, setLogoError] = useState(false);
  const showLogoImage = Boolean(mainLogoUrl) && !logoError;

  return (
    <section className="mx-auto max-w-6xl px-6 py-16">
      <div className="grid items-center gap-12 md:grid-cols-2">
        {/* Left */}
        <div>
          <h1 className="text-4xl font-extrabold leading-tight text-gray-900 md:text-5xl">
            학습을 하나로 잇다
          </h1>
          <h1 className="mt-1 bg-gradient-to-r from-green-400 to-green-500 bg-clip-text text-4xl font-extrabold leading-tight text-transparent md:text-5xl">
            StudyBridge
          </h1>

          <p className="mt-6 max-w-md leading-relaxed text-gray-500">
            자료 업로드부터 핵심 요약, 맞춤 로드맵, 복습 퀴즈까지 학습 과정을 하나의 흐름으로 연결하는 대학생 학습 플랫폼입니다.
          </p>

          <div className="mt-8 flex flex-wrap gap-3">
            <button
              onClick={() => navigate('/studymate')}
              className="flex items-center gap-2 rounded-[10px] bg-green-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-green-600"
            >
              시작하기 <ArrowRight size={16} style={{ color: '#FFFFFF' }} />
            </button>
            <button
              onClick={() => navigate('/archive')}
              className="flex items-center gap-2 rounded-[10px] border border-gray-200 bg-white px-5 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
            >
              <Upload size={16} style={{ color: '#374151' }} /> 자료 업로드
            </button>
          </div>
        </div>

        {/* Right card */}
        <div className="rounded-2xl border border-gray-200 bg-white p-8" style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
          <div className="mb-6 flex flex-col items-center rounded-xl bg-gray-50 py-6">
            {showLogoImage ? (
              <img
                src={mainLogoUrl}
                alt="StudyBridge logo"
                onError={() => setLogoError(true)}
                className="object-contain"
                style={{ maxWidth: '100%', maxHeight: '120px' }}
              />
            ) : (
              <GraduationCap size={36} style={{ color: '#16A34A' }} />
            )}
            <span className="mt-2 text-base font-extrabold text-green-700">자료 → 요약 → 계획 → 복습</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {FEATURES.map(({ label, to, Icon }) => (
              <button
                key={label}
                onClick={() => navigate(to)}
                className="flex items-center gap-2 rounded-lg bg-green-50 px-3 py-3 text-left text-sm font-medium text-gray-700 transition hover:bg-green-100"
              >
                <Icon size={16} style={{ color: '#22C55E' }} className="shrink-0" />
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
