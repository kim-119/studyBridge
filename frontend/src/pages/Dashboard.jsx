import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

import LandingNav from '../components/landing/LandingNav';
import MainBanner from '../components/MainBanner';
import FeatureSection from '../components/landing/FeatureSection';
import CtaSection from '../components/landing/CtaSection';
import Footer from '../components/landing/Footer';

/**
 * 메인 랜딩 페이지 (/).
 *  - 상단 네비 → 히어로 → 핵심 기능 → CTA → 푸터 순서로 구성.
 *  - 기존 내부 기능(타이머/캘린더/리포트/투두)은 메인에서 제거하고, 네비/카드 링크로만 연결한다.
 */
export default function Dashboard() {
  const { user } = useAuth();
  const userEmail = localStorage.getItem('userEmail') || 'guest';
  const userName = userEmail.includes('@') ? userEmail.split('@')[0] : userEmail;

  // 관리자 계정은 관리자 페이지로 (기존 라우팅 로직 유지)
  if (user?.role === 'ADMIN' || user?.displayName === '시스템 관리자' || userName === 'admin') {
    return <Navigate to="/admin" replace />;
  }

  return (
    <div className="min-h-screen bg-[#F5F6F7]">
      <LandingNav />
      <MainBanner />
      <FeatureSection />
      <CtaSection />
      <Footer />
    </div>
  );
}
