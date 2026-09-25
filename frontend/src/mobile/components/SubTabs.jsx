import React from 'react';

export default function SubTabs({ tabs, activeKey, onChange }) {
  return (
    <div className="mobile-subtabs" role="tablist">
      {tabs.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={key === activeKey}
          className={key === activeKey ? 'mobile-subtabs__tab is-active' : 'mobile-subtabs__tab'}
          onClick={() => onChange(key)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
