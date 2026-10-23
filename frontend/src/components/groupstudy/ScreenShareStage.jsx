import React, { useEffect, useRef, useState } from 'react';
import { Monitor, Maximize, Minimize, MonitorOff, Volume2, VolumeX } from 'lucide-react';

// 화면공유 메인 스테이지(Discord 스타일). 화면공유가 하나라도 있으면 참가자 타일 위에 크게 표시된다.
//  · 원본 비율 유지: object-fit: contain(잘림 없음) + 검은 여백. 해상도는 송출 측 원본 그대로(강제 리사이즈 없음).
//  · 전체화면: 스테이지 요소 requestFullscreen(iOS Safari 는 video 요소 webkitEnterFullscreen 폴백).
//  · 내 공유는 로컬 미리보기(publisher) 를 음소거로 보여준다(공유 화면 소리가 내 스피커로 다시 나오는 중복 방지).
//  · 공유가 여러 개면 칩으로 골라 본다. 선택하지 않은 공유는 렌더하지 않는다(그 소리도 재생하지 않음).
// shares: [{ connectionId, name, isMine, streamManager, hasAudio }]

function ScreenVideo({ streamManager, muted }) {
  const ref = useRef(null);
  useEffect(() => {
    const v = ref.current;
    if (!v || !streamManager || typeof streamManager.addVideoElement !== 'function') return;
    try { streamManager.addVideoElement(v); } catch (e) { /* 이미 붙어 있으면 무시 */ }
    v.muted = !!muted;
  }, [streamManager, muted]);
  return (
    <video
      ref={ref}
      autoPlay
      playsInline
      muted={!!muted}
      data-testid="screen-stage-video"
      style={{ width: '100%', height: '100%', objectFit: 'contain', backgroundColor: '#000', display: 'block' }}
    />
  );
}

export default function ScreenShareStage({ shares, selectedId, onSelect, onStopMine, isMobile }) {
  const stageRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [remoteMuted, setRemoteMuted] = useState(false);
  const active = shares.find(s => s.connectionId === selectedId) || shares[shares.length - 1] || null;

  useEffect(() => {
    const onChange = () => setIsFullscreen(document.fullscreenElement === stageRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);

  if (!active) return null;

  const toggleFullscreen = async () => {
    const el = stageRef.current;
    try {
      if (document.fullscreenElement) { await document.exitFullscreen(); return; }
      if (el?.requestFullscreen) { await el.requestFullscreen(); return; }
      const video = el?.querySelector('video');
      if (video?.webkitEnterFullscreen) video.webkitEnterFullscreen();
    } catch (e) { /* 브라우저가 거부하면 무시 */ }
  };

  const title = active.isMine ? '내 화면을 공유하고 있습니다' : `${active.name || '참여자'}님의 화면`;
  const btn = { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.14)', backgroundColor: 'rgba(255,255,255,0.06)', color: '#E5E7EB', fontSize: '12px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' };

  return (
    <div
      ref={stageRef}
      className="room-screen-stage"
      data-testid="screen-stage"
      data-connection-id={active.connectionId}
      data-mine={active.isMine ? 'true' : 'false'}
      style={{ display: 'flex', flexDirection: 'column', backgroundColor: '#000', borderRadius: isFullscreen ? 0 : '16px', overflow: 'hidden', border: isFullscreen ? 'none' : '1px solid rgba(255,255,255,0.08)', marginBottom: isFullscreen ? 0 : '16px', height: isFullscreen ? '100%' : (isMobile ? 'auto' : 'min(68vh, calc(100vh - 320px))'), minHeight: isMobile ? 0 : '260px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', backgroundColor: 'rgba(15,23,42,0.92)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '10px', fontWeight: 800, letterSpacing: '0.5px', color: '#fff', backgroundColor: '#EF4444', padding: '2px 6px', borderRadius: '4px' }}>LIVE</span>
        <Monitor size={15} color="#93C5FD" />
        <span data-testid="screen-stage-title" style={{ color: '#F3F4F6', fontSize: '13px', fontWeight: 700, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: '1 1 auto' }}>{title}</span>
        {shares.length > 1 && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {shares.map(s => (
              <button
                key={s.connectionId}
                type="button"
                onClick={() => onSelect?.(s.connectionId)}
                aria-pressed={s.connectionId === active.connectionId}
                style={{ ...btn, backgroundColor: s.connectionId === active.connectionId ? 'rgba(59,130,246,0.35)' : btn.backgroundColor }}
              >
                {s.isMine ? '내 화면' : (s.name || '참여자')}
              </button>
            ))}
          </div>
        )}
        {!active.isMine && active.hasAudio && (
          <button type="button" style={btn} onClick={() => setRemoteMuted(m => !m)} title={remoteMuted ? '공유 소리 켜기' : '공유 소리 끄기'}>
            {remoteMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
          </button>
        )}
        <button type="button" style={btn} onClick={toggleFullscreen} data-testid="screen-stage-fullscreen" title={isFullscreen ? '전체화면 종료' : '전체화면으로 보기'}>
          {isFullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
          {!isMobile && (isFullscreen ? '전체화면 종료' : '전체화면')}
        </button>
        {active.isMine && (
          <button type="button" data-testid="screen-stage-stop" style={{ ...btn, backgroundColor: 'rgba(239,68,68,0.2)', borderColor: 'rgba(239,68,68,0.45)', color: '#FCA5A5' }} onClick={() => onStopMine?.()}>
            <MonitorOff size={14} /> 공유 중지
          </button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, position: 'relative', aspectRatio: isMobile && !isFullscreen ? '16 / 9' : undefined }}>
        <ScreenVideo key={active.connectionId} streamManager={active.streamManager} muted={active.isMine || remoteMuted} />
      </div>
    </div>
  );
}
