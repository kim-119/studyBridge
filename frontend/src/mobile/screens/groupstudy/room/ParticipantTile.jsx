import React, { useEffect, useRef, useState } from 'react';
import { Maximize2, Mic, MicOff, MonitorUp, UserRound, Video, VideoOff } from 'lucide-react';

export function participantLabel(participant) {
  return participant.isMe ? `${participant.name} (나)` : participant.name;
}

// 화면공유 타일은 소유자 이름 뒤에 "화면공유" 를 붙여 카메라 타일과 구분한다.
export function tileLabel(participant) {
  const base = participantLabel(participant);
  return participant.isScreenShare ? `${base} 화면공유` : base;
}

// 카메라/화면공유 어느 쪽이든 활성 영상이 있으면 영상을 표시한다.
export function isVideoVisible(participant) {
  return Boolean(participant.streamManager) && (participant.cameraOn === true || participant.screenOn === true);
}

// 모바일 WebView 는 자동재생을 막을 수 있어, 스트림 부착 후 명시적으로 play() 를 시도하고 실패 시 이벤트로 복구한다.
export function attachStreamToVideo(streamManager, element) {
  if (!streamManager || !element) return undefined;
  streamManager.addVideoElement(element);

  let cancelled = false;
  const tryPlay = () => {
    if (cancelled) return;
    const promise = element.play?.();
    if (promise?.catch) promise.catch(() => { /* 사용자 제스처 전까지 자동재생 차단 — 이벤트에서 재시도 */ });
  };

  tryPlay();
  element.addEventListener('loadedmetadata', tryPlay);
  element.addEventListener('canplay', tryPlay);

  return () => {
    cancelled = true;
    element.removeEventListener('loadedmetadata', tryPlay);
    element.removeEventListener('canplay', tryPlay);
  };
}

export function ParticipantAvatar({ participant }) {
  const [hasPhotoError, setPhotoError] = useState(false);
  const showsPhoto = Boolean(participant.photoUrl) && !hasPhotoError;

  return (
    <span className="mobile-video__placeholder">
      {showsPhoto ? (
        <img
          className="mobile-video__avatar mobile-video__avatar--photo"
          src={participant.photoUrl}
          alt=""
          onError={() => setPhotoError(true)}
        />
      ) : (
        <span className="mobile-video__avatar" aria-hidden="true">
          <UserRound size={28} />
        </span>
      )}
    </span>
  );
}

export function MediaIndicators({ participant }) {
  // 화면공유 타일은 마이크/카메라 상태 대신 화면공유 배지를 표시한다.
  if (participant.isScreenShare) {
    return (
      <span className="mobile-video__indicators">
        <span className="mobile-video__indicator" aria-label="화면공유">
          <MonitorUp size={12} />
        </span>
      </span>
    );
  }

  return (
    <span className="mobile-video__indicators">
      <span
        className={participant.micOn ? 'mobile-video__indicator' : 'mobile-video__indicator is-off'}
        aria-label={participant.micOn ? '마이크 켜짐' : '마이크 꺼짐'}
      >
        {participant.micOn ? <Mic size={12} /> : <MicOff size={12} />}
      </span>
      <span
        className={participant.cameraOn ? 'mobile-video__indicator' : 'mobile-video__indicator is-off'}
        aria-label={participant.cameraOn ? '카메라 켜짐' : '카메라 꺼짐'}
      >
        {participant.cameraOn ? <Video size={12} /> : <VideoOff size={12} />}
      </span>
    </span>
  );
}

function videoClassName(showsVideo, isMirrored) {
  return [showsVideo ? '' : 'is-hidden', isMirrored ? 'is-mirrored' : ''].filter(Boolean).join(' ');
}

export default function ParticipantTile({ participant, isMirrored, onExpand }) {
  const videoRef = useRef(null);
  const showsVideo = isVideoVisible(participant);
  // 화면공유는 거울 반전하지 않는다(소유자 PC 화면이므로).
  const mirrored = isMirrored && !participant.isScreenShare;

  // streamManager(구독자) 또는 실제 스트림(streamId)이 바뀔 때만 재부착한다 →
  // 속성 변경(카메라 토글 등)만으로 Subscriber/비디오 요소가 재생성되지 않는다.
  useEffect(() => {
    const element = videoRef.current;
    if (!element || !participant.streamManager) return undefined;
    return attachStreamToVideo(participant.streamManager, element);
  }, [participant.streamManager, participant.streamId]);

  return (
    <li
      className="mobile-video__tile"
      data-user-id={participant.userId ?? ''}
      data-connection-id={participant.connectionId}
      data-local={participant.isMe ? 'true' : 'false'}
      data-kind={participant.isScreenShare ? 'screen' : 'camera'}
      data-camera={participant.cameraOn ? 'on' : 'off'}
      data-screen={participant.screenOn ? 'on' : 'off'}
      data-mic={participant.micOn ? 'on' : 'off'}
    >
      <button
        type="button"
        className="mobile-video__tile-button"
        aria-label={`${tileLabel(participant)} 크게 보기`}
        onClick={() => onExpand(participant.connectionId)}
      >
        {participant.streamManager && (
          <video
            ref={videoRef}
            className={videoClassName(showsVideo, mirrored)}
            autoPlay
            playsInline
            muted={participant.isMe}
          />
        )}
        {!showsVideo && <ParticipantAvatar participant={participant} />}
      </button>

      <span className="mobile-video__expand" aria-hidden="true">
        <Maximize2 size={14} />
      </span>
      <span className="mobile-video__name">
        <MediaIndicators participant={participant} />
        <span className="mobile-video__name-text">{tileLabel(participant)}</span>
      </span>
    </li>
  );
}
