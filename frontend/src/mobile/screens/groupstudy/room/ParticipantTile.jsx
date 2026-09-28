import React, { useEffect, useRef, useState } from 'react';
import { Maximize2, Mic, MicOff, UserRound, Video, VideoOff } from 'lucide-react';

export function participantLabel(participant) {
  return participant.isMe ? `${participant.name} (나)` : participant.name;
}

export function isVideoVisible(participant) {
  return Boolean(participant.streamManager) && participant.cameraOn === true;
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

  useEffect(() => {
    const element = videoRef.current;
    if (!element || !participant.streamManager) return;
    participant.streamManager.addVideoElement(element);
  }, [participant.streamManager]);

  return (
    <li
      className="mobile-video__tile"
      data-user-id={participant.userId ?? ''}
      data-connection-id={participant.connectionId}
      data-local={participant.isMe ? 'true' : 'false'}
      data-camera={participant.cameraOn ? 'on' : 'off'}
      data-mic={participant.micOn ? 'on' : 'off'}
    >
      <button
        type="button"
        className="mobile-video__tile-button"
        aria-label={`${participantLabel(participant)} 크게 보기`}
        onClick={() => onExpand(participant.connectionId)}
      >
        {participant.streamManager && (
          <video
            ref={videoRef}
            className={videoClassName(showsVideo, isMirrored)}
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
        <span className="mobile-video__name-text">{participantLabel(participant)}</span>
      </span>
    </li>
  );
}
