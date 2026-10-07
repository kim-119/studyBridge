import React from 'react';
import { Mic } from 'lucide-react';
import { ICON_SIZE, SELECT_STYLE, SELECT_CARET_STYLE, SECTION_LABEL_STYLE, HINT_STYLE } from './prejoinUi';

// GENERAL/CAM 공통 마이크 입력 장치 선택. 선택값은 상위(selectedMic)가 보관하고 입장 시 StudyRoom 으로 전달된다.
export default function MicrophoneDeviceSelector({ mics = [], selectedMic = '', onChange, disabled = false }) {
  const current = mics.find((m) => m.deviceId === selectedMic);
  return (
    <div data-testid="prejoin-mic-device-selector">
      <div style={SECTION_LABEL_STYLE}>
        <Mic size={ICON_SIZE} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
      </div>
      <div style={{ position: 'relative', marginBottom: '8px' }}>
        <select
          aria-label="마이크 장치 선택"
          value={selectedMic}
          disabled={disabled || mics.length === 0}
          onChange={(e) => onChange?.(e.target.value)}
          style={{ ...SELECT_STYLE, cursor: mics.length === 0 ? 'not-allowed' : 'pointer' }}
        >
          {mics.length === 0 ? (
            <option value="">연결된 마이크 없음</option>
          ) : (
            <>
              <option value="">기본 마이크</option>
              {mics.map((mic, idx) => (
                <option key={mic.deviceId || idx} value={mic.deviceId}>
                  {mic.label || `마이크 ${idx + 1}`}
                </option>
              ))}
            </>
          )}
        </select>
        <div style={SELECT_CARET_STYLE}>▼</div>
      </div>
      {mics.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--color-danger)' }}>연결된 마이크가 없어 음소거(듣기 전용)로 입장합니다</div>
      ) : (
        <div style={HINT_STYLE} data-testid="prejoin-mic-device-current">
          {mics.length}개의 마이크 연결됨 · 선택: {current ? (current.label || '이름 없는 마이크') : '기본 마이크'}
        </div>
      )}
    </div>
  );
}
