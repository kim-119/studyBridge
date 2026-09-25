import React from 'react';
import { ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

export default function MobileAppBar({ title, showBackButton = false, actions = null }) {
  const navigate = useNavigate();

  return (
    <header className="mobile-app-bar">
      {showBackButton ? (
        <button
          type="button"
          className="mobile-app-bar__back"
          aria-label="뒤로 가기"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft size={24} />
        </button>
      ) : (
        <span className="mobile-app-bar__brand">StudyBridge</span>
      )}

      <h1 className="mobile-app-bar__title">{title}</h1>

      <div className="mobile-app-bar__actions">{actions}</div>
    </header>
  );
}
