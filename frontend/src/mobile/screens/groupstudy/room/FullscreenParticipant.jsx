import React, { useEffect, useRef } from 'react';
import { Minimize2 } from 'lucide-react';
import { MediaIndicators, ParticipantAvatar, isVideoVisible, participantLabel } from './ParticipantTile';

function mediaStreamOf(participant) {
  return participant.streamManager?.stream?.getMediaStream?.() || null;
}

export default function FullscreenParticipant({ participant, isMirrored, onClose }) {
  const videoRef = useRef(null);
  const showsVideo = isVideoVisible(participant);

  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;
    element.srcObject = mediaStreamOf(participant);
  }, [participant, showsVideo]);

  return (
    <div className="mobile-video-fullscreen" role="dialog" aria-label={`${participantLabel(participant)} 전체 화면`}>
      {showsVideo ? (
        <video ref={videoRef} className={isMirrored ? 'is-mirrored' : ''} autoPlay playsInline muted />
      ) : (
        <ParticipantAvatar participant={participant} />
      )}

      <div className="mobile-video-fullscreen__bar">
        <span className="mobile-video-fullscreen__name">
          <MediaIndicators participant={participant} />
          {participantLabel(participant)}
        </span>
        <button
          type="button"
          className="mobile-video-fullscreen__close"
          aria-label="전체 화면 닫기"
          onClick={onClose}
        >
          <Minimize2 size={20} />
        </button>
      </div>
    </div>
  );
}
