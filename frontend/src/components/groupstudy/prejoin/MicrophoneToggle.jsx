import React from 'react';
import { Mic, MicOff } from 'lucide-react';
import { micStateLabel } from '../../../utils/groupStudy';
import { ICON_SIZE, PILL_BUTTON_STYLE } from './prejoinUi';

// GENERAL/CAM 공통 마이크 ON/OFF 토글 + 현재 사용 가능 여부(켜짐/꺼짐/없음) + 입력 레벨 미터.
//  · 상태 계산은 micStateLabel(utils) 단일 지점. 꺼짐/없음 상태여도 입장은 막지 않는다(입장 버튼은 상위가 담당).
export default function MicrophoneToggle({ isMicOn, micStatus, micLevel = 0, onToggle, variant = 'dark' }) {
  const light = variant === 'light';
  const label = micStateLabel(isMicOn, micStatus);
  const live = isMicOn && micStatus === 'available';
  const activity = live ? (micLevel > 12 ? '말하는 중' : micLevel > 0 ? '입력 감지 중' : '입력 대기 중') : null;
  return (
    <div data-testid="prejoin-mic-toggle" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '14px', flexWrap: 'wrap' }}>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={isMicOn}
        aria-label={isMicOn ? '마이크 끄기' : '마이크 켜기'}
        style={{
          ...PILL_BUTTON_STYLE,
          borderColor: isMicOn ? 'rgba(34,197,94,0.5)' : 'rgba(148,163,184,0.4)',
          backgroundColor: isMicOn ? 'rgba(34,197,94,0.12)' : 'rgba(148,163,184,0.1)',
          color: isMicOn ? (light ? '#15803D' : '#86EFAC') : (light ? '#4B5563' : '#94A3B8'),
        }}
      >
        {isMicOn ? <Mic size={ICON_SIZE} /> : <MicOff size={ICON_SIZE} />}
        <span data-testid="prejoin-mic-state">{label}</span>
        {activity && <span style={{ opacity: 0.8 }}>· {activity}</span>}
      </button>
      {isMicOn && (micStatus === 'available' || micStatus === 'checking') && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '120px' }}>
          <div style={{ flex: 1, height: '6px', borderRadius: '4px', backgroundColor: light ? 'var(--color-border)' : 'rgba(255,255,255,0.12)', overflow: 'hidden', minWidth: '90px' }}>
            <div style={{ width: `${micLevel}%`, height: '100%', backgroundColor: micLevel > 12 ? '#22C55E' : '#60A5FA', transition: 'width 0.1s linear' }} />
          </div>
        </div>
      )}
    </div>
  );
}
