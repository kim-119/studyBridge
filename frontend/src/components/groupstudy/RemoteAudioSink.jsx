import React, { useEffect, useRef } from 'react';

// 영상 타일이 없는(프로필/아바타) 참가자의 원격 음성 재생용 숨김 미디어 엘리먼트.
//  · OpenVidu 는 session.subscribe(stream, undefined) 로 만든 subscriber 에 엘리먼트를 자동 생성하지 않으므로
//    addVideoElement 로 붙여줘야 오디오가 재생된다. 로컬(publisher)은 자기 소리를 재생하면 안 되므로 붙이지 않는다.
//  · video track 을 만들거나 요청하지 않는다(표시 크기 1px, 투명). GENERAL 음성 대화의 핵심 경로.
export default function RemoteAudioSink({ streamManager, stream }) {
  const ref = useRef(null);
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
  return (
    <video
      ref={ref}
      autoPlay
      playsInline
      data-testid="remote-audio-sink"
      aria-hidden="true"
      style={{ position: 'absolute', width: '1px', height: '1px', opacity: 0, pointerEvents: 'none', left: 0, top: 0 }}
    />
  );
}
