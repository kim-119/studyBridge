import React from 'react';
import CameraPreview from './CameraPreview';
import CameraToggle from './CameraToggle';
import MicrophoneToggle from './MicrophoneToggle';
import DeviceSettings from './DeviceSettings';
import PreJoinNav from './PreJoinNav';

// CAM(캠 스터디) 입장 준비 패널: 기존 MediaPreview 구조 유지(카메라 preview + 카메라/마이크 토글 + 장치 설정 + 하단 내비).
export default function CamPreJoinPanel({ camera, mic, devices, nav }) {
  return (
    <div data-testid="prejoin-panel-cam" data-study-type="CAM" style={{ width: '100%', backgroundColor: 'black', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column' }}>
      <CameraPreview
        videoRef={camera.videoRef}
        isVideoOn={camera.isVideoOn}
        cameraStatus={camera.cameraStatus}
        camError={camera.camError}
        photoUrl={camera.photoUrl}
        onRetry={camera.onRetry}
        onUseDefaultCamera={camera.onUseDefaultCamera}
        onEnterWithoutCamera={camera.onEnterWithoutCamera}
      >
        {/* 장치 설정 패널 (토글) - 비디오 영역 위에 오버레이 */}
        {devices.show && (
          <DeviceSettings
            cameras={devices.cameras}
            selectedCamera={devices.selectedCamera}
            onCameraChange={devices.onCameraChange}
            mics={mic.mics}
            selectedMic={mic.selectedMic}
            onMicChange={mic.onSelectMic}
          />
        )}
      </CameraPreview>

      {/* 카메라/마이크 ON·OFF 토글 + 실시간 입력 상태(레벨 미터) */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '14px', padding: '12px 16px', backgroundColor: '#0F172A', borderTop: '1px solid #1F2937', flexWrap: 'wrap' }}>
        <CameraToggle isVideoOn={camera.isVideoOn} cameraStatus={camera.cameraStatus} onToggle={camera.onToggle} />
        <MicrophoneToggle isMicOn={mic.isMicOn} micStatus={mic.micStatus} micLevel={mic.micLevel} onToggle={mic.onToggle} />
      </div>

      <PreJoinNav {...nav} />
    </div>
  );
}
