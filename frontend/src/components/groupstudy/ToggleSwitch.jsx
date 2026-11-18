import React from 'react';

// 접근 가능한 토글 스위치(role=switch). 색상/크기는 index.css .gs-toggle 토큰 사용.
export function ToggleSwitch({ checked, onChange, disabled = false, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked ? 'true' : 'false'}
      aria-label={label}
      className="gs-toggle"
      disabled={disabled}
      onClick={() => { if (!disabled) onChange(!checked); }}
    >
      <span className="gs-toggle-knob" />
    </button>
  );
}

// [제목/설명 + 토글] 한 줄. 열품타식 설정 UX 의 정보구조만 차용(시각 스타일은 StudyBridge 토큰).
export function ToggleRow({ title, description, checked, onChange, disabled = false }) {
  return (
    <div className="gs-toggle-row">
      <div className="gs-toggle-row-text">
        <span className="gs-toggle-row-title">{title}</span>
        {description && <span className="gs-toggle-row-desc">{description}</span>}
      </div>
      <ToggleSwitch checked={checked} onChange={onChange} disabled={disabled} label={title} />
    </div>
  );
}

export default ToggleSwitch;
