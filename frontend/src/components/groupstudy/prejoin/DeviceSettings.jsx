import React from 'react';
import { Camera, Volume2 } from 'lucide-react';
import MicrophoneDeviceSelector from './MicrophoneDeviceSelector';
import { ICON_SIZE, SELECT_STYLE, SELECT_CARET_STYLE, SECTION_LABEL_STYLE, HINT_STYLE } from './prejoinUi';

// CAM 전용 장치 설정 패널(카메라 / 마이크 / 스피커). 마이크 선택기는 GENERAL 과 공통 컴포넌트를 재사용한다.
export default function DeviceSettings({ cameras = [], selectedCamera = '', onCameraChange, mics = [], selectedMic = '', onMicChange }) {
  return (
    <div className="prejoin-settings" data-testid="prejoin-device-settings" style={{ position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: '#F9FAFB', borderTop: '1px solid #E5E7EB', display: 'flex', padding: '24px', zIndex: 20 }}>
      {/* Camera */}
      <div style={{ flex: 1, padding: '0 16px', borderRight: '1px solid #E5E7EB' }} data-testid="prejoin-camera-device-selector">
        <div style={SECTION_LABEL_STYLE}>
          <Camera size={ICON_SIZE} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>카메라</span>
        </div>
        <div style={{ position: 'relative', marginBottom: '8px' }}>
          <select aria-label="카메라 장치 선택" value={selectedCamera} onChange={(e) => onCameraChange?.(e.target.value)} style={SELECT_STYLE}>
            {cameras.length === 0 ? (
              <option value="">카메라 찾는 중...</option>
            ) : (
              cameras.map((cam, idx) => (
                <option key={cam.deviceId} value={cam.deviceId}>
                  {cam.label || `카메라 ${idx + 1}`}
                </option>
              ))
            )}
          </select>
          <div style={SELECT_CARET_STYLE}>▼</div>
        </div>
        <div style={HINT_STYLE}>목록에서 다른 카메라를 선택해보세요</div>
      </div>
      {/* Mic (공통) */}
      <div style={{ flex: 1, padding: '0 16px', borderRight: '1px solid #E5E7EB' }}>
        <MicrophoneDeviceSelector mics={mics} selectedMic={selectedMic} onChange={onMicChange} />
      </div>
      {/* Speaker */}
      <div style={{ flex: 1, padding: '0 16px' }}>
        <div style={SECTION_LABEL_STYLE}>
          <Volume2 size={ICON_SIZE} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>스피커</span>
        </div>
        <div style={{ position: 'relative', marginBottom: '8px' }}>
          <select aria-label="스피커 선택" style={SELECT_STYLE} defaultValue="default">
            <option value="default">default</option>
          </select>
          <div style={SELECT_CARET_STYLE}>▼</div>
        </div>
        <div style={HINT_STYLE}>정상적으로 작동중입니다</div>
      </div>
    </div>
  );
}
