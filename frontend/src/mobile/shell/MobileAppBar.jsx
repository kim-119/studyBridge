import React from 'react';
import { ArrowLeft, House } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { HOME_PATH } from './navigationItems';

export default function MobileAppBar({ title, showBackButton, actions }) {
  const navigate = useNavigate();

  if (!showBackButton) {
    return (
      <header className="mobile-app-bar">
        <button
          type="button"
          className="mobile-app-bar__brand"
          aria-label="홈으로 이동"
          onClick={() => navigate(HOME_PATH)}
        >
          StudyBridge
        </button>
        <div className="mobile-app-bar__actions">{actions}</div>
      </header>
    );
  }

  return (
    <header className="mobile-app-bar">
      <button
        type="button"
        className="mobile-app-bar__icon-button"
        aria-label="뒤로 가기"
        onClick={() => navigate(-1)}
      >
        <ArrowLeft size={24} />
      </button>
      <h1 className="mobile-app-bar__title">{title}</h1>
      <div className="mobile-app-bar__actions">{actions}</div>
      <button
        type="button"
        className="mobile-app-bar__icon-button"
        aria-label="홈으로 이동"
        onClick={() => navigate(HOME_PATH)}
      >
        <House size={22} />
      </button>
    </header>
  );
}
