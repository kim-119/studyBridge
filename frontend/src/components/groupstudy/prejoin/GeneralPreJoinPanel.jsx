import React from 'react';
import AvatarPreview from './AvatarPreview';
import ProfileSelector from './ProfileSelector';
import MicrophoneToggle from './MicrophoneToggle';
import MicrophoneDeviceSelector from './MicrophoneDeviceSelector';
import PreJoinNav from './PreJoinNav';

// GENERAL(일반 스터디) 입장 준비 패널: 프로필 중심 UI. 카메라 preview/토글/장치/권한 요소를 포함하지 않는다.
//  구조: [프로필 미리보기(이미지 또는 기본 아이콘) + 닉네임] → [마이크 ON/OFF] → [마이크 장치 설정(토글)] → 하단 내비
export default function GeneralPreJoinPanel({
  avatar, displayName, profile, mic, nav,
}) {
  return (
    <div data-testid="prejoin-panel-general" data-study-type="GENERAL" style={{ width: '100%', backgroundColor: 'var(--color-bg-card)', borderRadius: '16px', overflow: 'hidden', border: '1px solid var(--color-border)', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.12)', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px', padding: '32px 24px 24px', boxSizing: 'border-box' }}>
        <AvatarPreview avatar={avatar} displayName={displayName} />
        <ProfileSelector
          mode={profile.mode}
          profilePhotoUrl={profile.profilePhotoUrl}
          uploadedFileName={profile.uploadedFileName}
          onSelectMode={profile.onSelectMode}
          onPickFile={profile.onPickFile}
          onError={profile.onError}
        />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', padding: '12px 16px', backgroundColor: '#0F172A', borderTop: '1px solid #1F2937' }}>
        <MicrophoneToggle isMicOn={mic.isMicOn} micStatus={mic.micStatus} micLevel={mic.micLevel} onToggle={mic.onToggle} />
      </div>

      {mic.showDeviceSelector && (
        <div className="prejoin-settings" data-testid="prejoin-mic-settings" style={{ backgroundColor: '#F9FAFB', borderTop: '1px solid #E5E7EB', padding: '20px 24px' }}>
          <MicrophoneDeviceSelector mics={mic.mics} selectedMic={mic.selectedMic} onChange={mic.onSelectMic} />
        </div>
      )}

      <PreJoinNav {...nav} settingsLabel="마이크 설정" />
    </div>
  );
}
