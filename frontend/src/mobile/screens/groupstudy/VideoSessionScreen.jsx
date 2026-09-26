import React, { useEffect, useRef } from 'react';
import { Mic, MicOff, PhoneOff, Video, VideoOff, Volume2, VolumeX } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import { ErrorState, LoadingState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { SESSION_STATE, useVideoSession } from './useVideoSession';

function ParticipantTile({ participant }) {
  const videoRef = useRef(null);

  useEffect(() => {
    const element = videoRef.current;
    if (!element || !participant.streamManager) return;

    participant.streamManager.addVideoElement(element);
  }, [participant.streamManager]);

  return (
    <li className="mobile-video__tile">
      {participant.streamManager ? (
        <video ref={videoRef} autoPlay playsInline muted={participant.isMe} />
      ) : (
        <span className="mobile-video__placeholder">{participant.name}</span>
      )}
      <span className="mobile-video__name">{participant.name}</span>
    </li>
  );
}

export default function VideoSessionScreen() {
  const { groupId } = useParams();
  const navigate = useNavigate();
  const session = useVideoSession(groupId);

  const leaveSession = async () => {
    await session.leave();
    navigate(`/groupstudy/${groupId}`, { replace: true });
  };

  if (session.state === SESSION_STATE.IDLE) {
    return (
      <MobileScreen title="화상 스터디" showBackButton>
        <section className="mobile-card mobile-section">
          <p className="mobile-paragraph">
            카메라와 마이크를 사용해 그룹 스터디에 참여합니다. 참여하면 권한 요청이 표시됩니다.
          </p>
        </section>

        <Button fullWidth onClick={() => session.join()}>
          화상 스터디 참여
        </Button>
      </MobileScreen>
    );
  }

  if (session.state === SESSION_STATE.FAILED) {
    return (
      <MobileScreen title="화상 스터디" showBackButton>
        <ErrorState message={session.errorMessage} onRetry={() => session.join()} />
      </MobileScreen>
    );
  }

  if (session.state !== SESSION_STATE.CONNECTED) {
    const label =
      session.state === SESSION_STATE.REQUESTING_PERMISSION
        ? '카메라와 마이크 권한을 확인하는 중입니다'
        : session.state === SESSION_STATE.RECONNECTING
          ? `연결이 끊겨 다시 연결하는 중입니다 (${session.reconnectAttempt}회차)`
          : '화상 스터디에 연결하는 중입니다';

    return (
      <MobileScreen title="화상 스터디" showBackButton>
        <LoadingState label={label} />
      </MobileScreen>
    );
  }

  return (
    <div className="mobile-video">
      <ul className="mobile-video__grid">
        {session.participants.map((participant) => (
          <ParticipantTile key={participant.connectionId} participant={participant} />
        ))}
      </ul>

      <div className="mobile-video__controls">
        <button
          type="button"
          aria-label={session.isMicrophoneOn ? '마이크 끄기' : '마이크 켜기'}
          className={session.isMicrophoneOn ? 'mobile-video__control' : 'mobile-video__control is-off'}
          onClick={session.toggleMicrophone}
        >
          {session.isMicrophoneOn ? <Mic size={22} /> : <MicOff size={22} />}
        </button>

        <button
          type="button"
          aria-label={session.isCameraOn ? '카메라 끄기' : '카메라 켜기'}
          className={session.isCameraOn ? 'mobile-video__control' : 'mobile-video__control is-off'}
          onClick={session.toggleCamera}
        >
          {session.isCameraOn ? <Video size={22} /> : <VideoOff size={22} />}
        </button>

        <button
          type="button"
          aria-label={session.isSpeakerphoneOn ? '스피커 끄기' : '스피커 켜기'}
          className={session.isSpeakerphoneOn ? 'mobile-video__control' : 'mobile-video__control is-off'}
          onClick={session.toggleSpeakerphone}
        >
          {session.isSpeakerphoneOn ? <Volume2 size={22} /> : <VolumeX size={22} />}
        </button>

        <button
          type="button"
          aria-label="나가기"
          className="mobile-video__control is-danger"
          onClick={leaveSession}
        >
          <PhoneOff size={22} />
        </button>
      </div>
    </div>
  );
}
