import React from 'react';
import { Link } from 'react-router-dom';
import {
  FileText, Route, HelpCircle, GraduationCap, Users, FileUp,
} from 'lucide-react';

/**
 * "핵심 기능" 섹션 (레퍼런스 톤).
 *  - 중앙 제목/부제 + 3x2 카드. 페이지 배경(#F5F6F7) 위 흰 카드.
 *  - 문구/아이콘은 레퍼런스를 따르고, 각 카드는 우리 앱 라우트로 연결한다.
 *  - 아이콘 색은 전역 .lucide 오버라이드를 피하려고 인라인 style로 지정.
 */
const FEATURES = [
  { Icon: FileText, title: 'PDF 요약 (Summarize PDFs)', desc: '수백 페이지의 자료를 단 몇 초만에 핵심만 추출하여 시간을 절약하세요.', to: '/studymate' },
  { Icon: Route, title: '로드맵 생성', desc: '목표 학점에 맞춘 주차별 맞춤형 학습 플랜을 AI가 직접 설계합니다.', to: '/studymate' },
  { Icon: HelpCircle, title: '퀴즈 생성', desc: '학습 내용을 바탕으로 객관식/주관식 퀴즈를 자동 생성하여 실력을 점검합니다.', to: '/studymate' },
  { Icon: GraduationCap, title: 'AI 질의응답', desc: '24시간 대기 중인 맞춤형 AI 튜터와 학습 중 궁금한 점을 즉시 해결하세요.', to: '/studymate' },
  { Icon: Users, title: '그룹 스터디', desc: '학우들과 학습 자료를 공유하고 함께 토론하며 성장의 시너지를 만듭니다.', to: '/groupstudy' },
  { Icon: FileUp, title: '학습 진도 관리', desc: '시각화된 대시보드를 통해 나의 학습 현황과 성취도를 한눈에 파악하세요.', to: '/study-report' },
];

export default function FeatureSection() {
  return (
    <section id="features" className="mx-auto max-w-6xl px-6 py-20">
      <h2 className="text-center text-3xl font-bold text-gray-900">핵심 기능</h2>
      <p className="mt-3 text-center text-gray-500">효율적인 학습을 위한 모든 도구가 준비되어 있습니다.</p>

      <div className="mt-12 grid gap-6 md:grid-cols-3">
        {FEATURES.map(({ Icon, title, desc, to }) => (
          <Link
            key={title}
            to={to}
            className="block rounded-2xl border border-gray-200 bg-white p-6 transition hover:border-green-200"
            style={{ boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}
          >
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-green-50">
              <Icon size={22} style={{ color: '#22C55E' }} />
            </div>
            <h3 className="mt-4 font-bold text-gray-900">{title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-gray-500">{desc}</p>
          </Link>
        ))}
      </div>
    </section>
  );
}
