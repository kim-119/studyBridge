import React from 'react';
import { MonitorUp, X } from 'lucide-react';
import { SCREEN_SHARE_MODES } from '../../utils/screenShare';

// 화면공유 시작 전 짧은 안내. [공유할 화면 선택] 클릭(사용자 제스처)에서만 브라우저 선택창을 연다 — 자동 캡처 없음.
export default function ScreenSharePrepDialog({ mode, withAudio, onModeChange, onAudioChange, aiConsent, onAiConsentChange, onCancel, onConfirm }) {
  const option = (key) => {
    const m = SCREEN_SHARE_MODES[key];
    const on = mode === key;
    return (
      <button
        key={key}
        type="button"
        data-testid={`screen-share-mode-${key}`}
        aria-pressed={on}
        onClick={() => onModeChange?.(key)}
        style={{ flex: 1, textAlign: 'left', padding: '10px 12px', borderRadius: '10px', cursor: 'pointer', border: `1px solid ${on ? 'rgba(96,165,250,0.8)' : 'rgba(255,255,255,0.12)'}`, backgroundColor: on ? 'rgba(59,130,246,0.18)' : 'rgba(255,255,255,0.04)', color: '#E5E7EB' }}
      >
        <div style={{ fontSize: '13px', fontWeight: 700 }}>{m.label}</div>
        <div style={{ fontSize: '11px', color: '#9CA3AF', marginTop: '2px' }}>{m.desc}</div>
      </button>
    );
  };
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="화면 공유"
      data-testid="screen-share-prep"
      onClick={(e) => { if (e.target === e.currentTarget) onCancel?.(); }}
      style={{ position: 'fixed', inset: 0, zIndex: 100000, backgroundColor: 'rgba(2,6,23,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '16px' }}
    >
      <div style={{ width: '100%', maxWidth: '440px', backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '16px', padding: '20px', color: '#F3F4F6', boxShadow: '0 20px 50px rgba(0,0,0,0.5)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <MonitorUp size={18} color="#93C5FD" />
          <span style={{ fontSize: '15px', fontWeight: 800, flex: 1 }}>화면 공유</span>
          <button type="button" aria-label="닫기" onClick={onCancel} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '4px', display: 'flex' }}><X size={16} color="#9CA3AF" /></button>
        </div>
        <ul style={{ margin: '0 0 14px', paddingLeft: '18px', fontSize: '12.5px', lineHeight: 1.6, color: '#CBD5E1' }}>
          <li>PPT·PDF·IDE <b>창</b>이나 <b>다른 탭</b>을 고르면 가장 선명하게 공유됩니다.</li>
          <li>이 회의 탭이나 회의 창이 보이는 <b>전체 모니터</b>를 고르면 화면이 끝없이 반복돼 보일 수 있어요.</li>
        </ul>
        <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
          {option('document')}
          {option('motion')}
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12.5px', color: '#CBD5E1', marginBottom: '16px', cursor: 'pointer' }}>
          <input type="checkbox" data-testid="screen-share-audio" checked={!!withAudio} onChange={(e) => onAudioChange?.(e.target.checked)} />
          공유 대상의 소리도 함께 보내기(선택창에서 다시 확인)
        </label>
        {onAiConsentChange && (
          <label style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '12.5px', color: '#CBD5E1', marginTop: '-6px', marginBottom: '16px', cursor: 'pointer', lineHeight: 1.5 }}>
            <input type="checkbox" data-testid="screen-share-ai-consent" checked={!!aiConsent} onChange={(e) => onAiConsentChange(e.target.checked)} style={{ marginTop: '3px' }} />
            <span>다른 참여자가 <b>AI 화면 분석</b>으로 내 공유 화면을 질문할 수 있게 허용(질문 순간의 화면 한 장만 분석, 저장 안 함 · 공유 중에도 바꿀 수 있어요)</span>
          </label>
        )}
        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button type="button" onClick={onCancel} style={{ padding: '9px 14px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.14)', background: 'rgba(255,255,255,0.04)', color: '#E5E7EB', fontSize: '13px', fontWeight: 700, cursor: 'pointer' }}>취소</button>
          <button type="button" data-testid="screen-share-confirm" onClick={onConfirm} style={{ padding: '9px 14px', borderRadius: '10px', border: '1px solid rgba(96,165,250,0.7)', background: 'rgba(59,130,246,0.35)', color: '#fff', fontSize: '13px', fontWeight: 800, cursor: 'pointer' }}>공유할 화면 선택</button>
        </div>
      </div>
    </div>
  );
}
