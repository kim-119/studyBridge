import React, { useEffect } from 'react';
import { X, Check } from 'lucide-react';
import { PROFILE_EMOJIS } from '../../../utils/groupStudy';
import { ICON_SIZE } from './prejoinUi';

// GENERAL 프로필 이모지 선택기(데스크톱: 모달 / ≤768px: 바텀시트, index.css .sb-emoji-picker*).
//  · 항목은 Unicode 이모지(PROFILE_EMOJIS) — 외부 API/CDN/PNG 없음. UI 아이콘(X/Check)만 lucide-react.
//  · 클릭 즉시 onSelect 로 상위 preview 가 바뀌고, [선택 완료]/X/배경 클릭으로 닫는다.
//  · 선택 상태: primary 테두리 + 연한 primary 배경 + Check 배지(기존 토큰만 사용).
export default function EmojiProfilePicker({ value, onSelect, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="sb-emoji-picker-overlay" data-testid="emoji-profile-picker" role="dialog" aria-modal="true" aria-label="프로필 아이콘 선택" onClick={onClose}>
      <div className="sb-emoji-picker glass-panel animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="sb-emoji-picker-header">
          <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--color-text-main)' }}>프로필 아이콘 선택</h3>
          <button type="button" aria-label="닫기" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '6px', display: 'flex', color: 'var(--color-text-muted)' }}>
            <X size={20} />
          </button>
        </div>
        <div className="sb-emoji-grid" role="listbox" aria-label="이모지 목록">
          {PROFILE_EMOJIS.map((emoji) => {
            const selected = emoji === value;
            return (
              <button
                key={emoji}
                type="button"
                role="option"
                aria-selected={selected}
                data-testid="emoji-option"
                data-emoji={emoji}
                data-selected={selected ? 'true' : 'false'}
                className={`sb-emoji-option${selected ? ' is-selected' : ''}`}
                onClick={() => onSelect?.(emoji)}
              >
                <span aria-hidden="true">{emoji}</span>
                {selected && (
                  <span className="sb-emoji-check" aria-label="선택됨"><Check size={ICON_SIZE - 4} /></span>
                )}
              </button>
            );
          })}
        </div>
        <div className="sb-emoji-picker-footer">
          <button type="button" className="btn-primary" style={{ width: 'auto', padding: '0 20px' }} onClick={onClose} data-testid="emoji-picker-done">
            선택 완료
          </button>
        </div>
      </div>
    </div>
  );
}
