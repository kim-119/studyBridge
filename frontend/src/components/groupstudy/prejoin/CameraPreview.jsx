import React from 'react';
import { Camera, AlertTriangle, User } from 'lucide-react';
import { AVATAR_FALLBACK_ICON_SIZE } from './prejoinUi';

// CAM 전용 카메라 미리보기(기존 MediaPreview 박스 그대로). 카메라 OFF 면 아바타, ON 이면 <video> + 확인 중/오류 오버레이.
//  · video element 와 상태 메시지만 담당하고 getUserMedia 는 상위(GroupStudy) effect 가 수행한다.
export default function CameraPreview({ videoRef, isVideoOn, cameraStatus, camError, photoUrl, onRetry, onUseDefaultCamera, onEnterWithoutCamera, children }) {
  return (
    <div data-testid="prejoin-camera-preview" style={{ position: 'relative', width: '100%', paddingTop: '56.25%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: isVideoOn ? '#1F2937' : 'black' }}>
      {!isVideoOn ? (
        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', color: '#4B5563' }}>
          {photoUrl ? (
            <img src={photoUrl} alt="avatar" style={{ width: '80px', height: '80px', borderRadius: '50%', objectFit: 'cover', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }} />
          ) : (
            <div style={{ width: '80px', height: '80px', borderRadius: '50%', backgroundColor: '#374151', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
              <User size={AVATAR_FALLBACK_ICON_SIZE} color="#9CA3AF" />
            </div>
          )}
        </div>
      ) : (
        <>
          <video
            ref={videoRef}
            autoPlay
            playsInline
            muted
            data-testid="prejoin-camera-video"
            style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover' }}
          />
          {/* 권한/장치 확인이 끝나기 전에는 "확인 중"을 보여주고, 실패 메시지는 retry가 끝난 뒤에만 노출 */}
          {cameraStatus === 'checking' && !camError && (
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'rgba(0,0,0,0.6)', color: '#E5E7EB', padding: '14px 18px', borderRadius: '8px', textAlign: 'center', zIndex: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
              <Camera size={28} color="#60A5FA" />
              <div style={{ fontSize: '13px', fontWeight: '600' }}>카메라를 확인하는 중입니다…</div>
            </div>
          )}
          {camError && (
            <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'rgba(0,0,0,0.7)', color: '#FCA5A5', padding: '16px', borderRadius: '8px', textAlign: 'center', maxWidth: '80%', zIndex: 10 }}>
              <AlertTriangle size={32} color="#EF4444" style={{ marginBottom: '8px' }} />
              <div style={{ fontSize: '14px', fontWeight: 'bold' }}>카메라 사용에 문제가 있습니다.</div>
              <div style={{ fontSize: '12px', marginTop: '4px', wordBreak: 'break-all' }}>{camError}</div>
              <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap', justifyContent: 'center' }}>
                <button type="button" onClick={onRetry} style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #FCA5A5', background: 'transparent', color: '#FCA5A5', cursor: 'pointer', fontSize: '12px' }}>
                  다시 시도
                </button>
                <button type="button" onClick={onUseDefaultCamera} style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #93C5FD', background: 'transparent', color: '#93C5FD', cursor: 'pointer', fontSize: '12px' }}>
                  기본 카메라로 전환
                </button>
                <button type="button" onClick={onEnterWithoutCamera} style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #D1D5DB', background: 'transparent', color: '#D1D5DB', cursor: 'pointer', fontSize: '12px' }}>
                  카메라 없이 입장
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {children}
    </div>
  );
}
