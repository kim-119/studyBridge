import React, { useState } from 'react';
import { Mic, MicOff, ShieldCheck, SwitchCamera, Video, VideoOff } from 'lucide-react';
import Button from '../../components/Button';
import MobileScreen from '../../shell/MobileScreen';
import { FACING_MODE, cloneLiveVideoTrack, oppositeFacingMode } from './cameraTrack';
import {
  DEVICE_STATUS,
  PERMISSION_STATUS,
  useCameraPreview,
  useMediaPermission,
  useMicrophoneLevel,
} from './useDevicePreview';

const DEVICE_STATUS_LABEL = {
  [DEVICE_STATUS.OFF]: '꺼짐',
  [DEVICE_STATUS.CHECKING]: '확인 중',
  [DEVICE_STATUS.READY]: '사용 가능',
  [DEVICE_STATUS.ERROR]: '사용 불가',
};

function DeviceStatusRow({ icon, label, status, errorMessage, children }) {
  return (
    <li className="mobile-prejoin__device">
      <span className="mobile-prejoin__device-icon">{icon}</span>
      <span className="mobile-prejoin__device-body">
        <span className="mobile-prejoin__device-name">{label}</span>
        <span className={`mobile-prejoin__device-status is-${status}`}>
          {errorMessage || DEVICE_STATUS_LABEL[status]}
        </span>
        {children}
      </span>
    </li>
  );
}

function PermissionNotice({ permission }) {
  if (permission.status === PERMISSION_STATUS.GRANTED) return null;

  if (permission.status === PERMISSION_STATUS.CHECKING) {
    return <p className="mobile-chat__status">카메라와 마이크 권한을 확인하는 중입니다</p>;
  }

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-paragraph">
        {permission.errorMessage ||
          '카메라·마이크 권한 없이도 입장할 수 있습니다. 채팅, AI 질문, 자료와 퀴즈를 그대로 이용하고 다른 참여자의 화면도 볼 수 있습니다. 화상으로 참여하려면 권한을 허용해주세요.'}
      </p>
      <div className="mobile-card__actions">
        <Button variant="secondary" onClick={permission.request}>
          <ShieldCheck size={16} />
          권한 허용하기
        </Button>
      </div>
    </section>
  );
}

function describeEntryMode({ isCameraOn, isMicOn }) {
  if (isCameraOn && isMicOn) return '카메라와 마이크를 켠 상태로 입장합니다.';
  if (isCameraOn) return '마이크를 끈 상태로 입장합니다.';
  if (isMicOn) return '카메라 없이 음성으로만 입장합니다.';
  return '카메라와 마이크를 끈 상태로 입장합니다. 다른 참여자의 화면과 소리는 그대로 보고 들을 수 있습니다.';
}

export default function VideoPreJoin({ groupTitle, onJoin }) {
  const [isCameraOn, setCameraOn] = useState(true);
  const [isMicOn, setMicOn] = useState(true);
  const [facingMode, setFacingMode] = useState(FACING_MODE.FRONT);

  const permission = useMediaPermission();
  const isGranted = permission.status === PERMISSION_STATUS.GRANTED;
  const camera = useCameraPreview({ isEnabled: isGranted && isCameraOn, facingMode });
  const microphone = useMicrophoneLevel({ isEnabled: isGranted && isMicOn });

  const joinRoom = () => {
    onJoin({
      cameraOn: isCameraOn,
      micOn: isMicOn,
      facingMode,
      videoTrack: isCameraOn && isGranted ? cloneLiveVideoTrack(camera.streamRef.current) : null,
    });
  };

  return (
    <MobileScreen title={groupTitle || '화상 스터디'} showBackButton>
      <p className="mobile-card__meta">입장하기 전에 카메라와 마이크 상태를 확인하세요.</p>

      <PermissionNotice permission={permission} />

      <div className="mobile-prejoin__preview">
        {isCameraOn && isGranted && (
          <video
            ref={camera.videoRef}
            className={facingMode === FACING_MODE.FRONT ? 'is-mirrored' : ''}
            autoPlay
            playsInline
            muted
          />
        )}
        {camera.status !== DEVICE_STATUS.READY && (
          <span className="mobile-prejoin__preview-label">
            {isCameraOn ? camera.errorMessage || DEVICE_STATUS_LABEL[camera.status] : '카메라 꺼짐'}
          </span>
        )}
      </div>

      <div className="mobile-prejoin__toggles">
        <button
          type="button"
          className={isCameraOn ? 'mobile-video__control' : 'mobile-video__control is-off'}
          aria-label={isCameraOn ? '카메라 끄기' : '카메라 켜기'}
          onClick={() => setCameraOn((previous) => !previous)}
        >
          {isCameraOn ? <Video size={22} /> : <VideoOff size={22} />}
        </button>
        <button
          type="button"
          className={isMicOn ? 'mobile-video__control' : 'mobile-video__control is-off'}
          aria-label={isMicOn ? '마이크 끄기' : '마이크 켜기'}
          onClick={() => setMicOn((previous) => !previous)}
        >
          {isMicOn ? <Mic size={22} /> : <MicOff size={22} />}
        </button>
        <button
          type="button"
          className="mobile-video__control"
          aria-label={facingMode === FACING_MODE.FRONT ? '후면 카메라로 전환' : '전면 카메라로 전환'}
          disabled={!isCameraOn}
          onClick={() => setFacingMode(oppositeFacingMode)}
        >
          <SwitchCamera size={22} />
        </button>
      </div>

      <ul className="mobile-prejoin__devices">
        <DeviceStatusRow
          icon={<Video size={18} />}
          label={facingMode === FACING_MODE.FRONT ? '카메라 (전면)' : '카메라 (후면)'}
          status={camera.status}
          errorMessage={camera.errorMessage}
        />
        <DeviceStatusRow
          icon={<Mic size={18} />}
          label="마이크"
          status={microphone.status}
          errorMessage={microphone.errorMessage}
        >
          {microphone.status === DEVICE_STATUS.READY && (
            <span className="mobile-prejoin__meter" aria-label={`입력 레벨 ${microphone.level}`}>
              <span style={{ width: `${microphone.level}%` }} />
            </span>
          )}
        </DeviceStatusRow>
      </ul>

      <p className="mobile-field__hint mobile-prejoin__entry-mode">{describeEntryMode({ isCameraOn, isMicOn })}</p>

      <Button fullWidth onClick={joinRoom}>
        스터디룸 입장
      </Button>
    </MobileScreen>
  );
}
