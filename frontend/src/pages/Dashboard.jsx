import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

import MainBanner from '../components/MainBanner';
import FeatureSection from '../components/landing/FeatureSection';
import CtaSection from '../components/landing/CtaSection';
import Footer from '../components/landing/Footer';

/**
 * 메인 랜딩 페이지 (/).
 *  - 상단 Header(글로벌 Navbar)는 App.jsx 에서 렌더한다.
 *  - 본문: 히어로(MainBanner) → 핵심 기능(FeatureSection) → CTA(CtaSection) → Footer.
 *  - 로그인 여부와 무관하게 / 에서는 항상 메인 랜딩이 보인다(관리자만 기존대로 /admin 으로).
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
      <MainBanner />
      <FeatureSection />
      <CtaSection />
      <Footer />
    </div>
  );
}
