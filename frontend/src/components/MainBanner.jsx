import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowRight, Upload, FileUp, FileText, Route, HelpCircle, GraduationCap,
} from 'lucide-react';
import { bannerService } from '../services/api';

/**
 * 메인 배너 (Hero) — 레퍼런스 디자인 톤 기준.
 *  - 좌: 헤드라인(검정 + 그린 그라데이션) · 설명 · CTA 2개
 *  - 우: 흰 카드 + 브랜드 블록 + 2x2 기능 칩
 *  - 문구/버튼/이동 경로는 백엔드 GET /api/banners/main 값을 우선 사용(없으면 기본값).
 *    아이콘 색은 전역 .lucide(muted) 오버라이드를 피하려고 인라인 style로 지정한다.
 */
const FEATURES = [
  { label: '자료 업로드', to: '/archive', Icon: FileUp },
  { label: '핵심 요약', to: '/studymate', Icon: FileText },
  { label: '맞춤 로드맵', to: '/studymate', Icon: Route },
  { label: '복습 퀴즈', to: '/studymate', Icon: HelpCircle },
];

export default function MainBanner() {
  const navigate = useNavigate();
  const [banner, setBanner] = useState(null);

  useEffect(() => {
    let mounted = true;
    bannerService.getMainBanner()
      .then((data) => { if (mounted) setBanner(data); })
      .catch((err) => { console.warn('메인 배너 로드 실패:', err?.message || err); });
    return () => { mounted = false; };
  }, []);

  const headlineBlack = banner?.title || 'AI가 자료를 읽고, 계획을 만들고, 복습까지 도와주는';
  const headlineAccent = banner?.titleAccent || '대학생 학습 플랫폼';
  const description = banner?.subtitle
    || '복잡한 전공 서적부터 밀린 강의 노트까지, AI가 당신의 학습 스타일을 분석하여 최적화된 로드맵과 퀴즈를 자동으로 생성합니다.';

  const primaryText = banner?.primaryButtonText || '시작하기';
  const primaryPath = banner?.primaryButtonPath || '/studymate';
  const secondaryText = banner?.secondaryButtonText || '자료 업로드';
  const secondaryPath = banner?.secondaryButtonPath || '/archive';

  return (
    <section className="mx-auto max-w-6xl px-6 py-16">
      <div className="grid items-center gap-12 md:grid-cols-2">
        {/* Left */}
        <div>
          <h1 className="whitespace-pre-line text-4xl font-extrabold leading-tight text-gray-900 md:text-5xl">
            {headlineBlack}
          </h1>
          <h1 className="mt-1 bg-gradient-to-r from-green-400 to-green-500 bg-clip-text text-4xl font-extrabold leading-tight text-transparent md:text-5xl">
            {headlineAccent}
          </h1>

          <p className="mt-6 max-w-md leading-relaxed text-gray-500">{description}</p>

          <div className="mt-8 flex flex-wrap gap-3">
            <button
              onClick={() => navigate(primaryPath)}
              className="flex items-center gap-2 rounded-[10px] bg-green-500 px-5 py-3 text-sm font-semibold text-white transition hover:bg-green-600"
            >
              {primaryText} <ArrowRight size={16} style={{ color: '#FFFFFF' }} />
            </button>
            <button
              onClick={() => navigate(secondaryPath)}
              className="flex items-center gap-2 rounded-[10px] border border-gray-200 bg-white px-5 py-3 text-sm font-semibold text-gray-700 transition hover:bg-gray-50"
            >
              <Upload size={16} style={{ color: '#374151' }} /> {secondaryText}
            </button>
          </div>
        </div>

        {/* Right card */}
        <div className="rounded-2xl border border-gray-200 bg-white p-8" style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
          <div className="mb-6 flex flex-col items-center rounded-xl bg-gray-50 py-6">
            <GraduationCap size={36} style={{ color: '#16A34A' }} />
            <span className="mt-2 text-lg font-bold text-green-700">StudyBridge</span>
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
