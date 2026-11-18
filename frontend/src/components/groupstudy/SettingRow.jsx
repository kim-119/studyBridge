import React from 'react';

// 생성/수정 폼의 공통 행: 라벨(필수 표시) + 컨트롤 + 힌트. 데스크톱 가로 / 모바일 세로(index.css .gs-form-row).
export default function SettingRow({ label, required = false, hint, children, align = 'start' }) {
  return (
    <div className="gs-form-row">
      <div className="gs-form-label" style={align === 'center' ? { alignItems: 'center', paddingTop: 0 } : undefined}>
        {label}
        {required && <span className="gs-required">*</span>}
      </div>
      <div className="gs-form-control">
        {children}
        {hint && <div className="gs-form-hint">{hint}</div>}
      </div>
    </div>
  );
}
