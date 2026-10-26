import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { TAB_ITEMS, findActiveTabKey } from './navigationItems';

export default function BottomNav() {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const activeKey = findActiveTabKey(pathname);

  return (
    <nav className="mobile-bottom-nav" aria-label="주요 메뉴">
      {TAB_ITEMS.map(({ key, label, path, icon: Icon }) => {
        const isActive = key === activeKey;

        return (
          <button
            key={key}
            type="button"
            className={isActive ? 'mobile-bottom-nav__item is-active' : 'mobile-bottom-nav__item'}
            aria-current={isActive ? 'page' : undefined}
            onClick={() => navigate(path)}
          >
            <Icon size={22} strokeWidth={isActive ? 2.4 : 1.8} />
            <span>{label}</span>
          </button>
        );
      })}
    </nav>
  );
}
