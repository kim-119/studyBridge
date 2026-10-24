import React, { useEffect, useRef, useState } from 'react';
import { Monitor, Maximize, Minimize, MonitorOff, Volume2, VolumeX, Eye, EyeOff, Scan, AlertTriangle } from 'lucide-react';

// 화면공유 메인 스테이지(Discord·Meet 유형). 화면공유가 하나라도 있으면 참가자 타일 위에 크게 표시된다.
//  · 다른 사람의 공유: 원본 비율 유지(object-fit: contain, 잘림 없음) + [원본 크기]: 1 영상 픽셀 = 1 화면 픽셀로 스크롤해서 본다
//    (축소 표시로 작아진 PDF·IDE 글자를 읽기 위함, 필터·샤프닝 없음). 전체화면은 브라우저 UI(ESC 안내)를 그대로 쓴다.
//  · 내 공유(이 탭·내 다른 기기): 라이브 미리보기 대신 상태 카드. 이 화면이 공유 대상(전체 화면·이 탭)에 보이면 무한 거울이 생기므로
//    미리보기는 사용자가 켤 때만 작게, 음소거로 보여준다.
//  · 공유가 여러 개면 칩으로 골라 본다. 선택하지 않은 공유는 렌더하지 않는다(그 소리도 재생하지 않음).
// shares: [{ connectionId, name, isMine, isOwnUser, surface, streamManager, hasAudio }]

function ScreenVideo({ streamManager, muted, actualSize, dims, onDims, style }) {
  const ref = useRef(null);
  useEffect(() => {
    const v = ref.current;
    if (!v || !streamManager || typeof streamManager.addVideoElement !== 'function') return;
    try { streamManager.addVideoElement(v); } catch (e) { /* 이미 붙어 있으면 무시 */ }
    v.muted = !!muted;
  }, [streamManager, muted]);
  const report = () => { const v = ref.current; if (v?.videoWidth) onDims?.({ w: v.videoWidth, h: v.videoHeight }); };
  const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1;
  const sizeStyle = actualSize && dims?.w
    ? { width: `${dims.w / dpr}px`, height: `${dims.h / dpr}px`, maxWidth: 'none', objectFit: 'fill' }
    : { width: '100%', height: '100%', objectFit: 'contain' };
  return (
    <video
      ref={ref}
      autoPlay
      playsInline
      muted={!!muted}
      data-testid="screen-stage-video"
      onLoadedMetadata={report}
      onResize={report}
      style={{ backgroundColor: '#000', display: 'block', ...sizeStyle, ...style }}
    />
  );
}

export default function ScreenShareStage({ shares, selectedId, onSelect, onStopMine, isMobile }) {
  const stageRef = useRef(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [remoteMuted, setRemoteMuted] = useState(false);
  const [actualSize, setActualSize] = useState(false);
  const [ownPreview, setOwnPreview] = useState(false);
  const [dims, setDims] = useState(null);
  const active = shares.find(s => s.connectionId === selectedId) || shares[shares.length - 1] || null;

  useEffect(() => {
    const onChange = () => setIsFullscreen(document.fullscreenElement === stageRef.current);
    document.addEventListener('fullscreenchange', onChange);
    return () => document.removeEventListener('fullscreenchange', onChange);
  }, []);
  useEffect(() => { setDims(null); setActualSize(false); }, [active?.connectionId]);

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

  const own = !!active.isOwnUser;
  const title = active.isMine ? '내 화면을 공유하고 있습니다' : own ? `${active.name}에서 화면을 공유하고 있습니다` : `${active.name || '참여자'}님의 화면`;
  const btn = { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.14)', backgroundColor: 'rgba(255,255,255,0.06)', color: '#E5E7EB', fontSize: '12px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' };
  const surface = active.surface;

  return (
    <div
      ref={stageRef}
      className="room-screen-stage"
      data-testid="screen-stage"
      data-connection-id={active.connectionId}
      data-mine={active.isMine ? 'true' : 'false'}
      data-own={own ? 'true' : 'false'}
      style={{ display: 'flex', flexDirection: 'column', backgroundColor: '#000', borderRadius: isFullscreen ? 0 : '16px', overflow: 'hidden', border: isFullscreen ? 'none' : '1px solid rgba(255,255,255,0.08)', marginBottom: isFullscreen ? 0 : '16px', height: isFullscreen ? '100%' : (own && !ownPreview ? 'auto' : (isMobile ? 'auto' : 'min(68vh, calc(100vh - 320px))')), minHeight: isMobile || (own && !ownPreview) ? 0 : '260px' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', backgroundColor: 'rgba(15,23,42,0.92)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '10px', fontWeight: 800, letterSpacing: '0.5px', color: '#fff', backgroundColor: '#EF4444', padding: '2px 6px', borderRadius: '4px' }}>LIVE</span>
        <Monitor size={15} color="#93C5FD" />
        <span data-testid="screen-stage-title" style={{ color: '#F3F4F6', fontSize: '13px', fontWeight: 700, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: '1 1 auto' }}>{title}</span>
        {shares.length > 1 && (
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {shares.map(s => (
              <button key={s.connectionId} type="button" onClick={() => onSelect?.(s.connectionId)} aria-pressed={s.connectionId === active.connectionId}
                style={{ ...btn, backgroundColor: s.connectionId === active.connectionId ? 'rgba(59,130,246,0.35)' : btn.backgroundColor }}>
                {s.isMine ? '내 화면' : (s.name || '참여자')}
              </button>
            ))}
          </div>
        )}
        {own ? (
          <button type="button" style={btn} data-testid="screen-stage-own-preview" onClick={() => setOwnPreview(v => !v)} title={ownPreview ? '미리보기 끄기' : '미리보기 켜기'}>
            {ownPreview ? <EyeOff size={14} /> : <Eye size={14} />}{!isMobile && (ownPreview ? '미리보기 끄기' : '미리보기')}
          </button>
        ) : (
          <>
            {active.hasAudio && (
              <button type="button" style={btn} onClick={() => setRemoteMuted(m => !m)} title={remoteMuted ? '공유 소리 켜기' : '공유 소리 끄기'}>
                {remoteMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
            )}
            <button type="button" style={{ ...btn, backgroundColor: actualSize ? 'rgba(59,130,246,0.35)' : btn.backgroundColor }} data-testid="screen-stage-actual-size" aria-pressed={actualSize}
              onClick={() => setActualSize(v => !v)} title={actualSize ? '화면에 맞추기' : '원본 크기로 보기(작은 글자 읽기)'}>
              <Scan size={14} />{!isMobile && (actualSize ? '화면 맞춤' : `원본 크기${dims ? ` ${dims.w}×${dims.h}` : ''}`)}
            </button>
            <button type="button" style={btn} onClick={toggleFullscreen} data-testid="screen-stage-fullscreen" title={isFullscreen ? '전체화면 종료' : '전체화면으로 보기'}>
              {isFullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
              {!isMobile && (isFullscreen ? '전체화면 종료' : '전체화면')}
            </button>
          </>
        )}
        {active.isMine && (
          <button type="button" data-testid="screen-stage-stop" style={{ ...btn, backgroundColor: 'rgba(239,68,68,0.2)', borderColor: 'rgba(239,68,68,0.45)', color: '#FCA5A5' }} onClick={() => onStopMine?.()}>
            <MonitorOff size={14} /> 공유 중지
          </button>
        )}
      </div>

      {own ? (
        <div data-testid="screen-stage-own" style={{ backgroundColor: '#0B1220', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div style={{ color: '#CBD5E1', fontSize: '13px' }}>
            {active.isMine
              ? <>참여자에게 선택한 <b>{surface?.label || '화면'}</b>{surface?.resolution ? `(${surface.resolution})` : ''} 화면이 크게 보이고 있어요. 마이크·카메라·채팅은 그대로 쓸 수 있습니다.</>
              : '내 다른 기기에서 공유 중인 화면입니다. 이 화면이 공유 대상에 보이면 반복 화면이 생길 수 있어 미리보기는 꺼 두었어요.'}
          </div>
          {surface?.recursionRisk && (
            <div data-testid="screen-stage-recursion-warning" style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', padding: '8px 10px', borderRadius: '8px', backgroundColor: 'rgba(234,179,8,0.12)', border: '1px solid rgba(234,179,8,0.35)', color: '#FCD34D', fontSize: '12px' }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: '1px' }} />
              <span>전체 화면을 공유 중입니다. 이 회의 창이 화면에 보이면 다른 사람에게 화면이 반복돼 보여요. 공유할 앱을 앞에 띄우거나 창·탭 공유를 써 주세요.</span>
            </div>
          )}
          {ownPreview && (
            <div style={{ position: 'relative', height: isMobile ? 'auto' : '220px', aspectRatio: isMobile ? '16 / 9' : undefined, backgroundColor: '#000', borderRadius: '8px', overflow: 'hidden' }}>
              <ScreenVideo key={active.connectionId} streamManager={active.streamManager} muted />
            </div>
          )}
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, position: 'relative', aspectRatio: isMobile && !isFullscreen && !actualSize ? '16 / 9' : undefined, maxHeight: isMobile && actualSize ? '70vh' : undefined, overflow: actualSize ? 'auto' : 'hidden' }}>
          <ScreenVideo key={active.connectionId} streamManager={active.streamManager} muted={remoteMuted} actualSize={actualSize} dims={dims} onDims={setDims} />
        </div>
      )}
    </div>
  );
}
