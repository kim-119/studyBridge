import React from 'react';
import { ChevronRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import MobileScreen from '../shell/MobileScreen';

const MENU_ITEMS = [
  { label: '홈', path: '/' },
  { label: '오답노트', path: '/review-notes' },
  { label: '주간일정', path: '/weekly-schedule' },
  { label: '지식공유', path: '/knowledge' },
  { label: '마인드맵', path: '/mindmap' },
  { label: '마이페이지', path: '/mypage' },
];

export default function MoreScreen() {
  const navigate = useNavigate();

  return (
    <MobileScreen title="전체">
      <ul className="mobile-menu-list">
        {MENU_ITEMS.map(({ label, path }) => (
          <li key={path}>
            <button
              type="button"
              className="mobile-menu-list__button"
              onClick={() => navigate(path)}
            >
              <span>{label}</span>
              <ChevronRight size={18} />
            </button>
          </li>
        ))}
      </ul>
    </MobileScreen>
  );
}
