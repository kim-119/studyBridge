import React, { useEffect, useRef, useState } from 'react';
import { forgetPlayback, isPlaybackBlocked, requestPlayback, retryBlockedPlayback, subscribePlaybackBlocked } from '../../utils/mediaAutoplay';

// 영상 타일이 없는(프로필/아바타) 참가자의 원격 음성 재생용 숨김 미디어 엘리먼트.
//  · OpenVidu 는 session.subscribe(stream, undefined) 로 만든 subscriber 에 엘리먼트를 자동 생성하지 않으므로
//    addVideoElement 로 붙여줘야 오디오가 재생된다. 로컬(publisher)은 자기 소리를 재생하면 안 되므로 붙이지 않는다.
//  · video track 을 만들거나 요청하지 않는다(표시 크기 1px, 투명). GENERAL 음성 대화의 핵심 경로.
//  · 브라우저가 소리 자동재생을 막으면(utils/mediaAutoplay) 이 타일에 '소리 재생' 버튼을 띄운다 — 누르면 막힌 소리·영상을 모두 다시 재생.
export default function RemoteAudioSink({ streamManager, stream }) {
  const ref = useRef(null);
  const [blocked, setBlocked] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (streamManager && typeof streamManager.addVideoElement === 'function') {
      try {
        streamManager.addVideoElement(el);
        console.info('[StudyRoomOV] audio:attached', { streamId: streamManager?.stream?.streamId || null });
      } catch (error) {
        console.warn('[StudyRoomOV] audio:attach-failed', { name: error?.name, message: error?.message });
        if (stream && el.srcObject !== stream) el.srcObject = stream;
      }
    } else if (stream && el.srcObject !== stream) {
      el.srcObject = stream;
    }
  }, [streamManager, stream]);
  // openvidu 는 autoplay 만 켜고 play() 를 부르지 않는다 → 직접 불러 자동재생 차단(NotAllowedError)을 감지한다.
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const sync = () => setBlocked(isPlaybackBlocked(el));
    const tryPlay = () => {
      if (el.srcObject && el.paused && !el.ended && !isPlaybackBlocked(el)) requestPlayback(el);
    };
    const unsubscribe = subscribePlaybackBlocked(sync);
    ['loadstart', 'loadedmetadata', 'canplay'].forEach((type) => el.addEventListener(type, tryPlay));
    tryPlay();
    sync();
    return () => {
      unsubscribe();
      ['loadstart', 'loadedmetadata', 'canplay'].forEach((type) => el.removeEventListener(type, tryPlay));
      forgetPlayback(el);
    };
  }, [streamManager, stream]);
  return (
    <>
      <video
        ref={ref}
        autoPlay
        playsInline
        data-testid="remote-audio-sink"
        aria-hidden="true"
        style={{ position: 'absolute', width: '1px', height: '1px', opacity: 0, pointerEvents: 'none', left: 0, top: 0 }}
      />
      {blocked && (
        <button type="button" data-testid="remote-audio-play" onClick={() => { retryBlockedPlayback(); }} style={{ position: 'absolute', top: '10px', left: '50%', transform: 'translateX(-50%)', zIndex: 5, padding: '5px 12px', borderRadius: '999px', border: 'none', backgroundColor: '#3B82F6', color: '#FFFFFF', fontSize: '12px', fontWeight: 700, cursor: 'pointer' }}>
          자동 재생이 막혔어요 · 소리 재생
        </button>
      )}
    </>
  );
}
