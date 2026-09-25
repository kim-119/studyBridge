import React from 'react';
import { BookMarked, CalendarRange, LogOut, Network, Newspaper, UserRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ListRow from '../components/ListRow';
import MobileScreen from '../shell/MobileScreen';
import { useAuth } from '../../hooks/useAuth';

const MENU_ITEMS = [
  { label: '오답노트', path: '/review-notes', icon: <BookMarked size={20} /> },
  { label: '주간일정', path: '/weekly-schedule', icon: <CalendarRange size={20} /> },
  { label: '지식공유', path: '/knowledge', icon: <Newspaper size={20} /> },
  { label: '마인드맵', path: '/mindmap', icon: <Network size={20} /> },
  { label: '마이페이지', path: '/mypage', icon: <UserRound size={20} /> },
];

export default function MoreScreen() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <MobileScreen title="전체">
      <section className="mobile-profile-card">
        <span className="mobile-profile-card__avatar">
          {user?.photoUrl ? (
            <img src={user.photoUrl} alt="" />
          ) : (
            <UserRound size={24} />
          )}
        </span>

        <span className="mobile-profile-card__body">
          <strong>{user?.displayName || '학습자'}</strong>
          <span>{user?.major || '전공 미설정'}</span>
          <span>{user?.email}</span>
        </span>
      </section>

      <ul className="mobile-list">
        {MENU_ITEMS.map(({ label, path, icon }) => (
          <li key={path}>
            <ListRow icon={icon} title={label} onClick={() => navigate(path)} />
          </li>
        ))}

        <li>
          <ListRow
            icon={<LogOut size={20} />}
            title="로그아웃"
            onClick={handleLogout}
            trailing={<span />}
          />
        </li>
      </ul>
    </MobileScreen>
  );
}
