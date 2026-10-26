import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Monitor, Maximize, Minimize, MonitorOff, Volume2, VolumeX, Eye, EyeOff, Scan, Info, AppWindow, Globe,
  Camera, RefreshCw, Radio, ZoomIn, ZoomOut, Activity, CheckCircle2, Circle, Loader2, X,
} from 'lucide-react';
import {
  deriveShareReceipt, pickRtp, summarizeInbound, summarizeOutbound, RECEIPT_INTERVAL_MS,
} from '../../utils/screenReceipt';
import { describeCaptureSurface } from '../../utils/screenShare';
import { useFullscreenViewer } from '../../hooks/useFullscreenViewer';
import FullscreenFrame from './FullscreenViewer';

// 화면공유 메인 스테이지(Discord·Meet 유형). 화면공유가 하나라도 있으면 참가자 타일 위에 크게 표시된다.
//  · 다른 사람의 공유: 원본 비율 유지(object-fit: contain, 잘림 없음) + [원본 크기]: 1 영상 픽셀 = 1 화면 픽셀로 스크롤해서 본다
//    (축소 표시로 작아진 PDF·IDE 글자를 읽기 위함, 필터·샤프닝 없음). 실제로 재생하는 동안 송출자에게 수신 확인(receipt)을 보낸다.
//  · 내 공유: 상태 카드(송출 단계 · 공유 대상 · 송출 통계 · 시청자별 실제 재생 여부). 수신 성공은 시청자의 playing 보고로만 표시한다
//    (미리보기가 보이거나 Publisher 가 만들어졌다는 사실은 수신 성공이 아니다).
//  · 내 미리보기: 꺼짐이 기본. 전체 모니터 공유는 미리보기가 다시 캡처돼 반복 화면이 생기므로 정지 화면(스냅샷)이 기본이고
//    실시간은 사용자가 따로 켤 때만, 작게. Esc 또는 [미리보기 끄기]로 즉시 끈다.
//  · 공유가 여러 개면 칩으로 골라 본다. 선택하지 않은 공유는 렌더하지 않는다(그 소리도 재생하지 않음).
//  · 전체화면 보기(FullscreenViewer): 다른 사람의 공유를 볼 때 PC·모바일 모두 '전체화면 보기' 버튼. Fullscreen API 우선,
//    앱 WebView·iPhone·거부 시 CSS 전체화면 레이어. 스테이지 DOM 을 통째로 옮길 뿐이라 같은 Subscriber·<video> 를 그대로 쓰고,
//    전체화면 안에서도 공유 선택·소리·원본 크기·수신 정보가 그대로 동작한다. 내 공유(송출자)는 상태 카드·미리보기만 —
//    송출 화면을 전체화면으로 띄우면 공유 대상에 다시 찍혀 반복 화면이 생기므로 전체화면 진입 버튼을 두지 않는다
//    (전체화면 중 '내 화면' 칩을 고른 경우에도 종료 버튼은 남는다).
// shares: [{ connectionId, name, isMine, isOwnUser, surface, streamManager, hasAudio }]
// ownShare: { status, step, health, liveSince } · viewers: 송출자 기준 시청 대상(고유 userId) · receipts: 시청자 보고

const PHASE_VIEW = {
  capturing: { label: '화면 선택 중', tone: '#93C5FD' },
  connecting: { label: 'OpenVidu 연결 중', tone: '#93C5FD' },
  sending: { label: '송출 중', tone: '#60A5FA' },
  received: { label: '수신 확인됨', tone: '#34D399' },
  unverified: { label: '수신 확인 불가', tone: '#FBBF24' },
  failed: { label: '연결 장애', tone: '#F87171' },
  ended: { label: '공유 종료', tone: '#9CA3AF' },
};
const VIEWER_STATE = {
  playing: '재생 중',
  hidden: '재생 중(백그라운드 탭)',
  subscribed: '연결됨 · 이 화면을 표시하지 않음',
  stopped: '보지 않음',
  stale: '응답 끊김',
  waiting: '확인 중…',
  'no-response': '확인 불가(응답 없음)',
};
const LIMITATION = { cpu: 'CPU', bandwidth: '대역폭', other: '기타' };
const ZOOMS = [0.25, 0.5, 0.75, 1, 1.5, 2];

const fmtKbps = (k) => (k === null || k === undefined ? null : k >= 1000 ? `${(k / 1000).toFixed(1)}Mbps` : `${k}kbps`);
/** 측정한 항목만 나열한다. 하나도 없으면 null(호출부가 '미측정'으로 표시). */
export function formatVideoStats(s, { withLoss = true } = {}) {
  if (!s) return null;
  const parts = [];
  if (s.w && s.h) parts.push(`${s.w}×${s.h}`);
  if (s.fps !== null && s.fps !== undefined) parts.push(`${s.fps}fps`);
  if (fmtKbps(s.kbps)) parts.push(fmtKbps(s.kbps));
  if (withLoss && s.lossPct !== null && s.lossPct !== undefined) parts.push(`손실 ${s.lossPct}%`);
  if (withLoss && s.dropped !== null && s.dropped !== undefined) parts.push(`드롭 ${s.dropped}`);
  return parts.length ? parts.join(' · ') : null;
}

/**
 * 지금 공유 중인 대상(캡처 트랙의 현재 설정). 시작 직후의 설정값은 첫 프레임 전 기본 크기일 수 있고, 공유 중 대상 전환
 * (surfaceSwitching)도 있으므로 렌더마다 다시 읽는다(getSettings 는 동기·저비용).
 */
function currentSurface(share) {
  const base = share.surface || null;
  try {
    const track = share.streamManager?.stream?.getMediaStream?.()?.getVideoTracks?.()[0];
    if (!track || track.readyState !== 'live' || typeof track.getSettings !== 'function') return base;
    const now = describeCaptureSurface(track.getSettings());
    if (now.surface) return { ...base, ...now };
    return { ...base, width: now.width ?? base?.width, height: now.height ?? base?.height, resolution: now.resolution || base?.resolution || null, frameRate: now.frameRate ?? base?.frameRate ?? null };
  } catch (e) {
    return base;
  }
}

function SurfaceIcon({ surface, size = 14 }) {
  if (surface === 'browser') return <Globe size={size} />;
  if (surface === 'window' || surface === 'application') return <AppWindow size={size} />;
  return <Monitor size={size} />;
}

function ScreenVideo({ streamManager, muted, actualSize, dims, onDims, style, videoRef }) {
  const ref = useRef(null);
  const setRef = useCallback((el) => { ref.current = el; if (videoRef) videoRef.current = el; }, [videoRef]);
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
      ref={setRef}
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

/** 표준 getStats() 주기 측정(송출자: outbound-rtp). enabled 일 때만 타이머가 돈다. */
function useOutboundStats(streamManager, enabled) {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    setStats(null);
    if (!enabled || !streamManager) return undefined;
    let prev = null;
    let stopped = false;
    const tick = async () => {
      try {
        const pc = streamManager.stream?.getRTCPeerConnection?.();
        if (!pc?.getStats) { if (!stopped) setStats({ unsupported: true }); return; }
        const cur = pickRtp(await pc.getStats(), 'outbound-rtp');
        if (stopped) return;
        setStats(cur ? summarizeOutbound(prev, cur) : null);
        prev = cur;
      } catch (e) { /* 통계 미지원 */ }
    };
    tick();
    const t = setInterval(tick, RECEIPT_INTERVAL_MS);
    return () => { stopped = true; clearInterval(t); };
  }, [streamManager, enabled]);
  return stats;
}

/**
 * 시청자: 이 공유를 실제로 재생하는 동안만 수신 통계를 측정하고 송출자에게 receipt 를 보낸다.
 * 재생 여부 = 영상 요소가 프레임을 갖고 재생 중(videoWidth>0, paused 아님). 구독만 된 상태는 playing 이 아니다.
 */
function useViewerReceipt(share, videoRef, onReceipt) {
  const [rx, setRx] = useState(null);
  const connection = share?.streamManager?.stream?.connection || null;
  useEffect(() => {
    setRx(null);
    const sm = share?.streamManager;
    if (!sm) return undefined;
    let prev = null;
    let last = null;
    let playingSent = false;
    let stopped = false;
    const isPlaying = () => { const v = videoRef.current; return !!v && !v.paused && !v.ended && v.readyState >= 2 && v.videoWidth > 0; };
    const send = (phase, stats) => { if (connection && onReceipt) onReceipt(connection, { phase, stats, hidden: document.visibilityState === 'hidden' }); };
    const sample = async () => {
      let s = null;
      try {
        const pc = sm.stream?.getRTCPeerConnection?.();
        if (pc?.getStats) {
          const cur = pickRtp(await pc.getStats(), 'inbound-rtp');
          s = cur ? summarizeInbound(prev, cur) : null;
          prev = cur;
        }
      } catch (e) { s = null; }
      if (stopped) return;
      last = s;
      setRx(s ? { ...s, at: Date.now() } : { at: Date.now(), none: true });
      if (isPlaying()) { send('playing', s); playingSent = true; } else if (playingSent) { send('stopped'); playingSent = false; }
    };
    const onPlaying = () => { if (!playingSent && isPlaying()) { send('playing', last); playingSent = true; } };
    const onVisibility = () => { if (playingSent) send('playing', last); };
    const v = videoRef.current;
    ['playing', 'loadeddata', 'resize'].forEach((e) => v?.addEventListener(e, onPlaying));
    document.addEventListener('visibilitychange', onVisibility);
    const first = setTimeout(sample, 1500);
    const t = setInterval(sample, RECEIPT_INTERVAL_MS);
    return () => {
      stopped = true;
      clearTimeout(first);
      clearInterval(t);
      ['playing', 'loadeddata', 'resize'].forEach((e) => v?.removeEventListener(e, onPlaying));
      document.removeEventListener('visibilitychange', onVisibility);
      if (playingSent) send('stopped');
    };
  }, [share?.connectionId, share?.streamManager, connection, onReceipt, videoRef]);
  return rx;
}

const useNow = (enabled, ms = 2000) => {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!enabled) return undefined;
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [enabled, ms]);
  return now;
};

/** 정지 화면 1장: 같은 트랙을 임시 video 에 붙여 한 프레임을 canvas 에 그린 뒤 바로 떼어낸다(송출에는 영향 없음). */
async function drawSnapshot(track, canvas) {
  if (!track || track.readyState !== 'live' || !canvas || typeof MediaStream === 'undefined') return null;
  const v = document.createElement('video');
  v.muted = true;
  v.playsInline = true;
  v.srcObject = new MediaStream([track]);
  try {
    await v.play();
    await new Promise((resolve) => {
      const done = () => resolve();
      setTimeout(done, 1500);
      if (typeof v.requestVideoFrameCallback === 'function') v.requestVideoFrameCallback(done);
      else if (v.readyState >= 2) done();
      else v.addEventListener('loadeddata', done, { once: true });
    });
    if (!v.videoWidth) return null;
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext('2d').drawImage(v, 0, 0);
    return { w: v.videoWidth, h: v.videoHeight };
  } catch (e) {
    return null;
  } finally {
    try { v.pause(); } catch (e) { /* ignore */ }
    v.srcObject = null;
  }
}

/**
 * 송출자 미리보기. mode: live | snapshot. 크기 기본 = 맞춤(원본 비율 그대로, 검은 여백 없이 가로를 채우되 높이 상한),
 * 확대/축소·100%(1 영상 픽셀 = 1 화면 픽셀, 스크롤). cautious(전체 모니터·내 다른 기기)는 맞춤 높이 상한을 낮춰 작게 시작한다.
 */
function OwnPreview({ share, surface, mode, onModeChange, onClose, isMobile, cautious, allowSnapshot }) {
  const [zoom, setZoom] = useState('fit');
  const [dims, setDims] = useState(() => (surface?.width ? { w: surface.width, h: surface.height } : null));
  const [snapAt, setSnapAt] = useState(null);
  const [snapFailed, setSnapFailed] = useState(false);
  const canvasRef = useRef(null);
  const dpr = typeof window !== 'undefined' ? (window.devicePixelRatio || 1) : 1;

  const takeSnapshot = useCallback(async () => {
    const track = share.streamManager?.stream?.getMediaStream?.()?.getVideoTracks?.()[0];
    const r = await drawSnapshot(track, canvasRef.current);
    if (r) { setDims(r); setSnapAt(Date.now()); setSnapFailed(false); } else setSnapFailed(true);
  }, [share.streamManager]);
  useEffect(() => { if (mode === 'snapshot') takeSnapshot(); }, [mode, takeSnapshot]);

  // Esc = 미리보기 즉시 끄기(반복 화면이 생겼을 때 가장 빠른 탈출구). 입력 중인 칸에서는 무시.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      const t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
      onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const w = dims?.w || 16;
  const h = dims?.h || 9;
  const zoomIdx = zoom === 'fit' ? -1 : ZOOMS.indexOf(zoom);
  const stepZoom = (dir) => {
    if (zoom === 'fit') { setZoom(dir > 0 ? 1 : 0.5); return; }
    const next = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, zoomIdx + dir))];
    setZoom(next);
  };
  const maxH = isMobile ? '50vh' : (cautious ? 'min(32vh, 300px)' : 'min(58vh, 640px)');
  const media = mode === 'live'
    ? <ScreenVideo key={`live-${share.connectionId}`} streamManager={share.streamManager} muted onDims={setDims} style={zoom === 'fit' ? undefined : { width: `${(w / dpr) * zoom}px`, height: `${(h / dpr) * zoom}px`, maxWidth: 'none', objectFit: 'fill' }} />
    : <canvas ref={canvasRef} data-testid="screen-own-snapshot" style={{ display: 'block', backgroundColor: '#000', ...(zoom === 'fit' ? { width: '100%', height: '100%', objectFit: 'contain' } : { width: `${(w / dpr) * zoom}px`, height: `${(h / dpr) * zoom}px` }) }} />;
  const ctl = { display: 'flex', alignItems: 'center', gap: '4px', padding: '4px 8px', borderRadius: '6px', border: '1px solid rgba(255,255,255,0.14)', backgroundColor: 'rgba(255,255,255,0.06)', color: '#E5E7EB', fontSize: '11.5px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' };
  const on = { ...ctl, backgroundColor: 'rgba(59,130,246,0.35)' };

  return (
    <div data-testid="screen-own-preview" data-mode={mode} data-zoom={String(zoom)} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '11.5px', color: '#94A3B8', marginRight: '4px' }}>
          {mode === 'live' ? '내 화면 실시간 미리보기' : `정지 화면${snapAt ? ` · ${new Date(snapAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}` : ''}`}
        </span>
        {allowSnapshot && (mode === 'snapshot' ? (
          <>
            <button type="button" style={ctl} data-testid="screen-preview-snapshot" onClick={takeSnapshot}><RefreshCw size={12} />다시 찍기</button>
            <button type="button" style={ctl} data-testid="screen-preview-live" onClick={() => onModeChange('live')} title="실시간 미리보기는 화면 안에 다시 찍혀 반복될 수 있어요"><Radio size={12} />실시간 보기</button>
          </>
        ) : (
          <button type="button" style={ctl} data-testid="screen-preview-to-snapshot" onClick={() => onModeChange('snapshot')}><Camera size={12} />정지 화면으로</button>
        ))}
        <span style={{ flex: 1 }} />
        <button type="button" style={zoom === 'fit' ? on : ctl} data-testid="screen-preview-fit" aria-pressed={zoom === 'fit'} onClick={() => setZoom('fit')}>맞춤</button>
        <button type="button" style={ctl} data-testid="screen-preview-zoom-out" aria-label="축소" disabled={zoomIdx === 0} onClick={() => stepZoom(-1)}><ZoomOut size={12} /></button>
        <button type="button" style={zoom === 1 ? on : ctl} data-testid="screen-preview-actual" aria-pressed={zoom === 1} onClick={() => setZoom(1)} title="원본 크기(글자 확인)">100%</button>
        <button type="button" style={ctl} data-testid="screen-preview-zoom-in" aria-label="확대" disabled={zoomIdx === ZOOMS.length - 1} onClick={() => stepZoom(1)}><ZoomIn size={12} /></button>
        {zoom !== 'fit' && zoom !== 1 && <span style={{ fontSize: '11px', color: '#CBD5E1' }}>{Math.round(zoom * 100)}%</span>}
        <button type="button" style={ctl} data-testid="screen-preview-close" onClick={onClose} title="미리보기 끄기(Esc)"><X size={12} />끄기{!isMobile && <span style={{ color: '#94A3B8', fontWeight: 600 }}>Esc</span>}</button>
      </div>
      {mode === 'live' && cautious && (
        <div data-testid="screen-preview-live-note" style={{ fontSize: '11.5px', color: '#FCD34D' }}>
          이 미리보기가 공유 중인 화면에 보이면 다시 찍혀 반복돼 보여요. 반복되면 Esc 를 누르세요.
        </div>
      )}
      {snapFailed && mode === 'snapshot' && <div style={{ fontSize: '11.5px', color: '#FCA5A5' }}>정지 화면을 가져오지 못했어요. 다시 찍기를 눌러 주세요.</div>}
      {zoom === 'fit' ? (
        <div style={{ width: `min(100%, calc(${maxH} * ${(w / h).toFixed(4)}))`, aspectRatio: `${w} / ${h}`, margin: '0 auto', backgroundColor: '#000', borderRadius: '8px', overflow: 'hidden' }}>
          {media}
        </div>
      ) : (
        <div data-preview-scroller="true" style={{ maxHeight: isMobile ? '60vh' : 'min(64vh, 720px)', overflow: 'auto', backgroundColor: '#000', borderRadius: '8px' }}>
          {media}
        </div>
      )}
    </div>
  );
}

function StepChip({ ok, label, testid }) {
  return (
    <span data-testid={testid} data-ok={ok ? 'true' : 'false'} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', fontSize: '11.5px', color: ok ? '#A7F3D0' : '#94A3B8' }}>
      {ok ? <CheckCircle2 size={12} color="#34D399" /> : <Circle size={12} color="#475569" />}{label}
    </span>
  );
}

function OwnShareCard({ share, ownShare, viewers, receipts, isMobile, previewMode, setPreviewMode }) {
  const mine = share.isMine;
  const now = useNow(mine && !!ownShare);
  const summary = mine ? deriveShareReceipt({ share: ownShare, viewers, receipts, now }) : null;
  const send = useOutboundStats(share.streamManager, mine && ownShare?.status === 'live');
  const surface = mine ? currentSurface(share) : null;
  const view = summary ? (PHASE_VIEW[summary.phase] || PHASE_VIEW.sending) : null;
  const closePreview = useCallback(() => setPreviewMode('off'), [setPreviewMode]);

  let detail = null;
  if (summary) {
    if (summary.phase === 'received') detail = `${summary.playing}/${summary.expected}명이 실제로 재생 중`;
    else if (summary.phase === 'sending') {
      detail = summary.expected === 0 ? '방에 다른 참여자가 없어요 · 수신 확인 대기'
        : summary.waiting > 0 ? `시청자 ${summary.waiting}명의 재생 확인을 기다리는 중`
          : `시청자 ${summary.expected}명 모두 지금 이 화면을 보고 있지 않아요`;
    }
    else if (summary.phase === 'unverified') detail = '시청자에게서 재생 확인이 오지 않았어요(앱·이전 버전은 확인 신호를 보내지 않을 수 있어요)';
    else if (summary.phase === 'failed') detail = ownShare.health === 'failed' ? '송출 연결이 끊겼어요. 공유를 다시 시작해 주세요.' : '서버와 다시 연결하는 중이에요';
    else if (summary.phase === 'connecting') detail = '미디어 서버와 연결을 맺는 중';
  }
  const sendText = send?.unsupported ? '이 브라우저는 송출 통계를 제공하지 않아요' : formatVideoStats(send, { withLoss: false });

  return (
    <div data-testid="screen-stage-own" style={{ backgroundColor: '#0B1220', padding: isMobile ? '12px' : '14px 16px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {summary && (
        <div data-testid="screen-own-status" data-phase={summary.phase} data-viewers-expected={summary.expected} data-viewers-playing={summary.playing}
          style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '3px 10px', borderRadius: '999px', fontSize: '12.5px', fontWeight: 800, color: view.tone, backgroundColor: 'rgba(255,255,255,0.06)', border: `1px solid ${view.tone}55` }}>
            {summary.phase === 'connecting' ? <Loader2 size={12} className="animate-spin" /> : <span style={{ width: 7, height: 7, borderRadius: '50%', backgroundColor: view.tone }} />}
            {view.label}
          </span>
          {detail && <span style={{ fontSize: '12.5px', color: '#CBD5E1' }}>{detail}</span>}
        </div>
      )}
      {!mine && (
        <div style={{ color: '#CBD5E1', fontSize: '13px' }}>내 다른 기기에서 공유 중인 화면입니다. 이 화면이 공유 대상에 보이면 반복 화면이 생길 수 있어 미리보기는 꺼 두었어요.</div>
      )}
      {mine && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12.5px', color: '#CBD5E1' }}>
          <div data-testid="screen-own-surface" style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
            <SurfaceIcon surface={surface?.surface} />
            <span>공유 대상 <b style={{ color: '#F3F4F6' }}>{surface?.label || '화면'}</b></span>
            <span style={{ color: '#94A3B8' }}>· 원본 캡처 {surface?.resolution || '해상도 미확인'}{surface?.frameRate ? ` · 최대 ${surface.frameRate}fps` : ''}</span>
            {surface?.modeLabel && <span style={{ color: '#94A3B8' }}>· {surface.modeLabel} 모드</span>}
          </div>
          <div data-testid="screen-own-send" style={{ color: '#94A3B8' }}>
            서버로 송출 {sendText || '측정 중…'}{fmtKbps(send?.targetKbps) ? ` · 허용 ${fmtKbps(send.targetKbps)}` : ''}{send?.limitation && send.limitation !== 'none' ? ` · 화질 제한: ${LIMITATION[send.limitation] || send.limitation}` : ''}
          </div>
        </div>
      )}
      {summary && (
        <div data-testid="screen-own-steps" style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
          <StepChip testid="screen-step-publisher" ok={ownShare.health === 'ok'} label="송출 연결" />
          <StepChip testid="screen-step-subscribed" ok={summary.subscribed > 0} label={`원격 구독 ${summary.subscribed}`} />
          <StepChip testid="screen-step-playing" ok={summary.playing > 0} label={`원격 재생 ${summary.playing}`} />
          <StepChip testid="screen-step-quality" ok={summary.measured > 0} label={`수신 품질 ${summary.measured}`} />
        </div>
      )}
      {summary && summary.viewers.length > 0 && (
        <div data-testid="screen-own-viewers" style={{ display: 'flex', flexDirection: 'column', gap: '4px', padding: '8px 10px', borderRadius: '8px', backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
          {summary.viewers.map((v) => {
            const stats = formatVideoStats(v.stats);
            const app = v.state === 'no-response' && (v.deviceType === 'ANDROID' || v.deviceType === 'IOS');
            const color = v.state === 'playing' || v.state === 'hidden' ? '#A7F3D0' : v.state === 'no-response' || v.state === 'stale' ? '#FCD34D' : '#CBD5E1';
            return (
              <div key={v.userKey} data-testid="screen-own-viewer" data-user-id={v.userKey} data-state={v.state} style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', fontSize: '12px', color: '#CBD5E1' }}>
                <b style={{ color: '#F3F4F6', fontWeight: 700 }}>{v.name}</b>
                <span style={{ color }}>{app ? '확인 불가(앱 — 확인 신호 미지원일 수 있음)' : VIEWER_STATE[v.state]}</span>
                {(v.state === 'playing' || v.state === 'hidden') && <span style={{ color: '#94A3B8' }}>{stats ? `· 수신 ${stats}` : '· 수신 통계 미측정'}</span>}
              </div>
            );
          })}
        </div>
      )}
      {mine && surface?.recursionPossible && (
        <div data-testid="screen-stage-recursion-hint" style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: '#94A3B8' }}>
          <Info size={12} style={{ flexShrink: 0 }} />
          <span>{surface.recursionRisk ? '전체 모니터를 공유 중이에요. 이 회의 창이 보이면 반복 화면이 생길 수 있어 미리보기는 정지 화면으로 보여드려요.' : '이 브라우저 창을 공유했다면 미리보기가 반복돼 보일 수 있어요.'}</span>
        </div>
      )}
      {previewMode !== 'off' && (
        <OwnPreview
          share={share}
          surface={surface}
          mode={previewMode}
          onModeChange={setPreviewMode}
          onClose={closePreview}
          isMobile={isMobile}
          cautious={!mine || !!surface?.recursionRisk}
          allowSnapshot={mine}
        />
      )}
    </div>
  );
}

function RemoteShareView({ share, isMobile, isFullscreen, actualSize, dims, onDims, remoteMuted, onReceipt, showRx }) {
  const videoRef = useRef(null);
  const rx = useViewerReceipt(share, videoRef, onReceipt);
  const rxText = rx && !rx.none ? formatVideoStats(rx) : null;
  return (
    <>
      {showRx && (
        <div data-testid="screen-stage-rx" data-measured={!rx ? 'pending' : rxText ? 'yes' : 'no'} style={{ padding: '6px 12px', backgroundColor: 'rgba(15,23,42,0.92)', borderTop: '1px solid rgba(255,255,255,0.06)', fontSize: '11.5px', color: '#CBD5E1', display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <span><b style={{ color: '#F3F4F6' }}>내 수신</b> {rxText || (rx ? '측정할 수 없음' : '측정 중…')}</span>
          <span style={{ color: '#94A3B8' }}>전체화면·원본 크기는 내 화면의 표시 방식이라 송출 해상도나 화질을 바꾸지 않아요.</span>
        </div>
      )}
      {/* 맞춤 = object-fit:contain(원본 비율·잘림 없음). 원본 크기 = 1 영상 픽셀 : 1 화면 픽셀 스크롤(전체화면에서는 남은 높이 전체). */}
      <div data-testid="screen-stage-viewport" style={{ flex: 1, minHeight: 0, position: 'relative', aspectRatio: isMobile && !isFullscreen && !actualSize ? '16 / 9' : undefined, maxHeight: isMobile && actualSize && !isFullscreen ? '70vh' : undefined, overflow: actualSize ? 'auto' : 'hidden', overscrollBehavior: 'contain' }}>
        <ScreenVideo key={share.connectionId} streamManager={share.streamManager} muted={remoteMuted} actualSize={actualSize} dims={dims} onDims={onDims} videoRef={videoRef} />
      </div>
    </>
  );
}

/** 공유 준비 단계·종료 직후의 짧은 상태 표시(스테이지가 없을 때). */
export function ScreenShareNotice({ phase, why, onDismiss }) {
  if (phase === 'ended') {
    const reason = { 'track-ended': '브라우저에서 공유를 중지했어요.', user: '화면 공유를 종료했어요.' }[why]
      || (/^(disconnected|server-evicted)/.test(String(why || '')) ? '연결이 끊겨 화면 공유가 종료됐어요.' : '화면 공유가 종료됐어요.');
    return (
      <div data-testid="screen-share-ended" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', padding: '8px 12px', borderRadius: '10px', backgroundColor: 'rgba(148,163,184,0.12)', border: '1px solid rgba(148,163,184,0.3)', color: '#CBD5E1', fontSize: '12.5px' }}>
        <MonitorOff size={14} /><span style={{ flex: 1 }}><b>공유 종료</b> · {reason}</span>
        {onDismiss && <button type="button" aria-label="닫기" onClick={onDismiss} style={{ background: 'none', border: 'none', cursor: 'pointer', display: 'flex', padding: 2 }}><X size={14} color="#94A3B8" /></button>}
      </div>
    );
  }
  const view = PHASE_VIEW[phase];
  if (!view) return null;
  return (
    <div data-testid="screen-share-pending" data-phase={phase} style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px', padding: '8px 12px', borderRadius: '10px', backgroundColor: 'rgba(59,130,246,0.12)', border: '1px solid rgba(96,165,250,0.3)', color: '#BFDBFE', fontSize: '12.5px' }}>
      <Loader2 size={14} className="animate-spin" />
      <b>{view.label}</b>
      <span style={{ color: '#94A3B8' }}>{phase === 'capturing' ? '브라우저 선택창에서 공유할 탭·창·화면을 고르세요.' : '공유 화면을 서버에 연결하고 있어요.'}</span>
    </div>
  );
}

export default function ScreenShareStage({ shares, selectedId, onSelect, onStopMine, isMobile, ownShare, viewers, receipts, onReceipt, portalTarget }) {
  const viewer = useFullscreenViewer({ label: '화면공유 전체화면' });
  const isFullscreen = viewer.isFullscreen;
  const [remoteMuted, setRemoteMuted] = useState(false);
  const [actualSize, setActualSize] = useState(false);
  const [previewMode, setPreviewMode] = useState('off'); // off | live | snapshot (내 공유 미리보기)
  const [showRx, setShowRx] = useState(false);
  const [dims, setDims] = useState(null);
  const active = shares.find(s => s.connectionId === selectedId) || shares[shares.length - 1] || null;

  // 공유를 바꾸면 표시 방식만 초기화한다(전체화면은 유지 — 전체화면 안에서 다른 공유로 전환).
  useEffect(() => { setDims(null); setActualSize(false); setPreviewMode('off'); }, [active?.connectionId]);

  if (!active) return null;

  const own = !!active.isOwnUser;
  const title = active.isMine ? '내 화면을 공유하고 있습니다' : own ? `${active.name}에서 화면을 공유하고 있습니다` : `${active.name || '참여자'}님의 화면`;
  const btn = { display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.14)', backgroundColor: 'rgba(255,255,255,0.06)', color: '#E5E7EB', fontSize: '12px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' };
  // 미리보기 켜기: 전체 모니터는 정지 화면부터(실시간은 미리보기 안에서 따로), 그 외는 실시간.
  const openPreview = () => setPreviewMode(active.isMine && currentSurface(active)?.previewPolicy === 'snapshot' ? 'snapshot' : 'live');
  const failed = active.isMine && (ownShare?.health === 'failed' || ownShare?.health === 'reconnecting' || ownShare?.health === 'unstable');

  const fullscreenButton = (
    <button type="button" style={{ ...btn, ...(isFullscreen ? { backgroundColor: 'rgba(59,130,246,0.35)' } : null) }} onClick={() => viewer.toggle()} data-testid="screen-stage-fullscreen" aria-pressed={isFullscreen}
      title={isFullscreen ? '전체화면 종료(Esc·뒤로가기)' : '내 화면에서 크게 보기(송출 화질·해상도는 그대로)'}>
      {isFullscreen ? <Minimize size={14} /> : <Maximize size={14} />}
      {isFullscreen ? '전체화면 종료' : '전체화면 보기'}
    </button>
  );

  return (
    <FullscreenFrame viewer={viewer} portalTarget={portalTarget} label={`${title} 전체화면`} testId="screen-stage-fullscreen-layer">
    <div
      className="room-screen-stage"
      data-testid="screen-stage"
      data-connection-id={active.connectionId}
      data-mine={active.isMine ? 'true' : 'false'}
      data-own={own ? 'true' : 'false'}
      data-fullscreen={viewer.mode || 'off'}
      style={{ display: 'flex', flexDirection: 'column', backgroundColor: '#000', borderRadius: isFullscreen ? 0 : '16px', overflow: 'hidden', border: isFullscreen ? 'none' : '1px solid rgba(255,255,255,0.08)', marginBottom: isFullscreen ? 0 : '16px', ...(isFullscreen ? { flex: 1, minHeight: 0, height: '100%' } : { height: own || isMobile ? 'auto' : 'min(68vh, calc(100vh - 320px))', minHeight: isMobile || own ? 0 : '260px' }) }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', backgroundColor: 'rgba(15,23,42,0.92)', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '10px', fontWeight: 800, letterSpacing: '0.5px', color: '#fff', backgroundColor: failed ? '#D97706' : '#EF4444', padding: '2px 6px', borderRadius: '4px' }}>{failed ? '장애' : 'LIVE'}</span>
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
          <>
          <button type="button" style={btn} data-testid="screen-stage-own-preview" aria-pressed={previewMode !== 'off'} onClick={() => (previewMode === 'off' ? openPreview() : setPreviewMode('off'))} title={previewMode !== 'off' ? '미리보기 끄기(Esc)' : '내가 보내는 화면 미리보기'}>
            {previewMode !== 'off' ? <EyeOff size={14} /> : <Eye size={14} />}{!isMobile && (previewMode !== 'off' ? '미리보기 끄기' : '미리보기')}
          </button>
          {isFullscreen && fullscreenButton}
          </>
        ) : (
          <>
            {active.hasAudio && (
              <button type="button" style={btn} onClick={() => setRemoteMuted(m => !m)} title={remoteMuted ? '공유 소리 켜기' : '공유 소리 끄기'} aria-label={remoteMuted ? '공유 소리 켜기' : '공유 소리 끄기'}>
                {remoteMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              </button>
            )}
            <button type="button" style={{ ...btn, backgroundColor: showRx ? 'rgba(59,130,246,0.35)' : btn.backgroundColor }} data-testid="screen-stage-rx-toggle" aria-pressed={showRx} onClick={() => setShowRx(v => !v)} title="내가 실제로 받고 있는 해상도·fps·비트레이트" aria-label="수신 정보">
              <Activity size={14} />{!isMobile && '수신 정보'}
            </button>
            <button type="button" style={{ ...btn, backgroundColor: actualSize ? 'rgba(59,130,246,0.35)' : btn.backgroundColor }} data-testid="screen-stage-actual-size" aria-pressed={actualSize}
              onClick={() => setActualSize(v => !v)} title={actualSize ? '화면에 맞추기' : '원본 크기로 보기(작은 글자 읽기)'} aria-label={actualSize ? '화면에 맞추기' : '원본 크기로 보기'}>
              <Scan size={14} />{!isMobile && (actualSize ? '화면 맞춤' : `원본 크기${dims ? ` ${dims.w}×${dims.h}` : ''}`)}
            </button>
            {fullscreenButton}
          </>
        )}
        {active.isMine && (
          <button type="button" data-testid="screen-stage-stop" style={{ ...btn, backgroundColor: 'rgba(239,68,68,0.2)', borderColor: 'rgba(239,68,68,0.45)', color: '#FCA5A5' }} onClick={() => onStopMine?.()}>
            <MonitorOff size={14} /> 공유 중지
          </button>
        )}
      </div>

      {own ? (
        <OwnShareCard share={active} ownShare={ownShare} viewers={viewers} receipts={receipts} isMobile={isMobile} previewMode={previewMode} setPreviewMode={setPreviewMode} />
      ) : (
        <RemoteShareView share={active} isMobile={isMobile} isFullscreen={isFullscreen} actualSize={actualSize} dims={dims} onDims={setDims} remoteMuted={remoteMuted} onReceipt={onReceipt} showRx={showRx} />
      )}
    </div>
    </FullscreenFrame>
  );
}
