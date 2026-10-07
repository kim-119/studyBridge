import React from 'react';
import { Camera, CameraOff } from 'lucide-react';
import { ICON_SIZE, PILL_BUTTON_STYLE } from './prejoinUi';

// CAM 전용 카메라 ON/OFF 토글(GENERAL 에서는 절대 렌더하지 않는다).
export default function CameraToggle({ isVideoOn, cameraStatus, onToggle }) {
  const label = !isVideoOn ? '카메라 꺼짐'
    : cameraStatus === 'checking' ? '카메라 확인 중…'
    : cameraStatus === 'available' ? '카메라 켜짐'
    : cameraStatus === 'unavailable' ? '카메라 없음'
    : cameraStatus === 'error' ? '카메라 권한/오류'
    : '카메라';
  return (
    <button
      type="button"
      data-testid="prejoin-camera-toggle"
      onClick={onToggle}
      aria-pressed={isVideoOn}
      aria-label={isVideoOn ? '카메라 끄기' : '카메라 켜기'}
      style={{
        ...PILL_BUTTON_STYLE,
        borderColor: isVideoOn ? 'rgba(96,165,250,0.5)' : 'rgba(148,163,184,0.4)',
        backgroundColor: isVideoOn ? 'rgba(59,130,246,0.15)' : 'rgba(148,163,184,0.1)',
        color: isVideoOn ? '#93C5FD' : '#94A3B8',
      }}
    >
      {isVideoOn ? <Camera size={ICON_SIZE} /> : <CameraOff size={ICON_SIZE} />}
      <span>{label}</span>
    </button>
  );
}
