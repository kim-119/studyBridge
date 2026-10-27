import React, { useEffect, useRef } from 'react';
import { Minimize2 } from 'lucide-react';
import { MediaIndicators, ParticipantAvatar, isVideoVisible, tileLabel } from './ParticipantTile';

function mediaStreamOf(participant) {
  return participant.streamManager?.stream?.getMediaStream?.() || null;
}

export default function FullscreenParticipant({ participant, isMirrored, onClose }) {
  const videoRef = useRef(null);
  const showsVideo = isVideoVisible(participant);
  // 화면공유는 거울 반전하지 않는다.
  const mirrored = isMirrored && !participant.isScreenShare;

  // 같은 MediaStream 을 그대로 재사용한다(새 Subscriber 생성·재구독 없음). 자동재생이 막히면 명시적으로 복구한다.
  useEffect(() => {
    const element = videoRef.current;
    if (!element) return undefined;
    element.srcObject = mediaStreamOf(participant);

    let cancelled = false;
    const tryPlay = () => {
      if (cancelled) return;
      const promise = element.play?.();
      if (promise?.catch) promise.catch(() => { /* 자동재생 차단 — 이벤트에서 재시도 */ });
    };
    tryPlay();
    element.addEventListener('loadedmetadata', tryPlay);
    element.addEventListener('canplay', tryPlay);
    return () => {
      cancelled = true;
      element.removeEventListener('loadedmetadata', tryPlay);
      element.removeEventListener('canplay', tryPlay);
    };
  }, [participant, showsVideo]);

  return (
    <div
      className="mobile-video-fullscreen"
      data-kind={participant.isScreenShare ? 'screen' : 'camera'}
      role="dialog"
      aria-label={`${tileLabel(participant)} 전체 화면`}
    >
      {/* 하단 타일 비디오가 오디오를 계속 재생하므로 전체화면 비디오는 음소거(오디오 중복 방지). */}
      {showsVideo ? (
        <video ref={videoRef} className={mirrored ? 'is-mirrored' : ''} autoPlay playsInline muted />
      ) : (
        <ParticipantAvatar participant={participant} />
      )}

      <div className="mobile-video-fullscreen__bar">
        <span className="mobile-video-fullscreen__name">
          <MediaIndicators participant={participant} />
          {tileLabel(participant)}
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
