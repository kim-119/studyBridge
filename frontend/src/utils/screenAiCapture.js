// AI 화면 분석용 현재 프레임 1장 캡처(브라우저 표준 API만, OpenVidu 내부 API 비의존).
//
// · 기존 OpenVidu 수신 스트림(Subscriber)·내 화면공유 Publisher 를 그대로 쓴다 — 캡처를 위해 Publisher/Subscriber 를 새로 만들지 않는다.
//   1순위: 스테이지가 이미 그리고 있는 <video>(StreamManager.videos — 선택된 공유)에서 바로 그린다.
//   2순위: 선택되지 않은 공유는 스테이지가 렌더하지 않으므로, 같은 MediaStreamTrack 을 화면 밖 임시 <video> 에 잠깐 붙여 한 프레임만 그리고 즉시 뗀다
//          (ScreenShareStage drawSnapshot 과 같은 방식, 새 WebRTC 연결·서버 요청 없음).
// · canvas 보안: WebRTC MediaStream 은 same-origin 데이터라 canvas 가 오염(tainted)되지 않는다 → toBlob/toDataURL 허용.
//   (교차 출처 URL 을 src 로 쓰는 <video> 만 오염된다 — 여기서는 쓰지 않는다.)
// · Android WebView(Capacitor)·iOS WebKit: 분리된(DOM 밖) <video> 는 프레임을 내지 않는 엔진이 있어 임시 video 를 1px 로 문서에 붙이고
//   muted + playsInline 으로 재생한다. toBlob 이 없으면 toDataURL 로 대체한다.
// · 계약(ai07): JPEG, 긴 변 1280px 이하, 짧은 변 32px 이상, 디코딩 1MB 이하. 권장 ~300KB → quality 0.75, 넘으면 0.6, 그래도 크면 축소.

export const SCREEN_AI_CAPTURE = Object.freeze({
  maxLongSide: 1280,
  minSide: 32,
  quality: 0.75,
  fallbackQuality: 0.6,
  targetBytes: 300 * 1024,
  maxBytes: 1024 * 1024,
  frameTimeoutMs: 4000,
});

export class ScreenCaptureError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'ScreenCaptureError';
    this.code = code;
  }
}

/** 원본 비율 유지, 긴 변을 maxLongSide 이하로(확대하지 않음). */
export function fitWithin(width, height, maxLongSide = SCREEN_AI_CAPTURE.maxLongSide) {
  const w = Math.max(0, Math.floor(Number(width) || 0));
  const h = Math.max(0, Math.floor(Number(height) || 0));
  if (!w || !h) return { width: 0, height: 0, scale: 0 };
  const scale = Math.min(1, maxLongSide / Math.max(w, h));
  return { width: Math.max(1, Math.round(w * scale)), height: Math.max(1, Math.round(h * scale)), scale };
}

const hasFrame = (v) => !!v && v.readyState >= 2 && v.videoWidth > 0 && v.videoHeight > 0 && !v.ended;

/** 스테이지 등에서 이미 재생 중인 이 StreamManager 의 <video>(프레임이 있는 것). 없으면 null. */
export function pickRenderedVideo(streamManager) {
  const list = Array.isArray(streamManager?.videos) ? streamManager.videos : [];
  for (const item of list) {
    const v = item?.video;
    if (hasFrame(v)) return v;
  }
  return null;
}

/** 이 StreamManager 의 살아 있는 영상 트랙. */
export function liveVideoTrack(streamManager) {
  try {
    const track = streamManager?.stream?.getMediaStream?.()?.getVideoTracks?.()[0];
    return track && track.readyState === 'live' ? track : null;
  } catch (e) {
    return null;
  }
}

/**
 * 인코딩 예산 맞추기(순수 로직). encode(width, height, quality) → Promise<{ size, ... }>.
 * quality → fallbackQuality 순으로 targetBytes 이하를 찾고, maxBytes 를 넘으면 0.75 배씩 줄여 최대 3번 다시 시도한다.
 * targetBytes 는 권장치라 넘어도 maxBytes 이하면 보낸다.
 */
export async function encodeWithinBudget(encode, size, opts = {}) {
  const o = { ...SCREEN_AI_CAPTURE, ...opts };
  let { width, height } = size;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (Math.min(width, height) < o.minSide) break;
    let out = await encode(width, height, o.quality);
    let quality = o.quality;
    if (out.size > o.targetBytes) {
      out = await encode(width, height, o.fallbackQuality);
      quality = o.fallbackQuality;
    }
    if (out.size <= o.maxBytes) return { ...out, width, height, quality };
    width = Math.round(width * 0.75);
    height = Math.round(height * 0.75);
  }
  throw new ScreenCaptureError('TOO_LARGE', '화면 이미지를 분석 가능한 크기로 줄이지 못했습니다.');
}

function waitForFrame(video, timeoutMs) {
  return new Promise((resolve, reject) => {
    if (hasFrame(video)) { resolve(); return; }
    let done = false;
    const finish = (ok) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearInterval(poll);
      ['loadeddata', 'playing', 'resize'].forEach((ev) => video.removeEventListener(ev, check));
      if (ok) resolve(); else reject(new ScreenCaptureError('NO_FRAME', '공유 화면을 아직 받지 못했습니다. 잠시 후 다시 시도해 주세요.'));
    };
    const check = () => { if (hasFrame(video)) finish(true); };
    ['loadeddata', 'playing', 'resize'].forEach((ev) => video.addEventListener(ev, check));
    const poll = setInterval(check, 100);
    const timer = setTimeout(() => finish(hasFrame(video)), timeoutMs);
  });
}

function attachTempVideo(track) {
  const v = document.createElement('video');
  v.muted = true;
  v.playsInline = true;
  v.autoplay = true;
  v.setAttribute('playsinline', '');
  v.setAttribute('muted', '');
  v.setAttribute('aria-hidden', 'true');
  v.style.cssText = 'position:fixed;left:-10px;top:-10px;width:1px;height:1px;opacity:0;pointer-events:none;';
  v.srcObject = new MediaStream([track]);
  document.body.appendChild(v);
  const p = v.play?.();
  if (p && typeof p.catch === 'function') p.catch(() => { /* muted 재생 거부는 프레임 대기 타임아웃으로 처리 */ });
  return v;
}

function detachTempVideo(v) {
  if (!v) return;
  try { v.pause(); } catch (e) { /* ignore */ }
  try { v.srcObject = null; } catch (e) { /* ignore */ } // 트랙은 멈추지 않는다(Subscriber·송출 소유)
  try { v.remove(); } catch (e) { /* ignore */ }
}

function canvasToJpeg(canvas, quality) {
  return new Promise((resolve, reject) => {
    const fromDataUrl = () => {
      try {
        const url = canvas.toDataURL('image/jpeg', quality);
        const base64 = url.slice(url.indexOf(',') + 1);
        resolve({ base64, size: Math.floor((base64.length * 3) / 4) - (base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0) });
      } catch (e) {
        reject(new ScreenCaptureError(e?.name === 'SecurityError' ? 'CANVAS_TAINTED' : 'ENCODE_FAILED', '화면 이미지를 만들지 못했습니다.'));
      }
    };
    if (typeof canvas.toBlob !== 'function') { fromDataUrl(); return; }
    try {
      canvas.toBlob((blob) => {
        if (!blob || blob.type !== 'image/jpeg') { fromDataUrl(); return; } // JPEG 미지원 엔진은 PNG 를 돌려준다
        resolve({ blob, size: blob.size });
      }, 'image/jpeg', quality);
    } catch (e) {
      reject(new ScreenCaptureError(e?.name === 'SecurityError' ? 'CANVAS_TAINTED' : 'ENCODE_FAILED', '화면 이미지를 만들지 못했습니다.'));
    }
  });
}

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => { const s = String(r.result || ''); resolve(s.slice(s.indexOf(',') + 1)); };
    r.onerror = () => reject(new ScreenCaptureError('ENCODE_FAILED', '화면 이미지를 만들지 못했습니다.'));
    r.readAsDataURL(blob);
  });
}

/** 16×9 로 줄여 가장 밝은 화소가 거의 검정이면 빈 프레임(아직 디코딩 전·검은 화면)으로 본다. */
function isBlankFrame(source) {
  try {
    const c = document.createElement('canvas');
    c.width = 16;
    c.height = 9;
    const ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(source, 0, 0, 16, 9);
    const d = ctx.getImageData(0, 0, 16, 9).data;
    let max = 0;
    for (let i = 0; i < d.length; i += 4) max = Math.max(max, d[i], d[i + 1], d[i + 2]);
    return max < 6;
  } catch (e) {
    return false; // 판단할 수 없으면 막지 않는다
  }
}

/**
 * 공유 화면의 현재 프레임 1장 → { base64, mime, width, height, bytes, quality, source }.
 * 실패 시 ScreenCaptureError(code: NO_STREAM | NO_FRAME | BLANK_FRAME | CANVAS_TAINTED | ENCODE_FAILED | TOO_LARGE).
 */
export async function captureShareFrame(streamManager, opts = {}) {
  const o = { ...SCREEN_AI_CAPTURE, ...opts };
  if (typeof document === 'undefined') throw new ScreenCaptureError('NO_STREAM', '이 환경에서는 화면을 캡처할 수 없습니다.');
  let video = pickRenderedVideo(streamManager);
  let temp = null;
  const source = video ? 'stage' : 'track';
  try {
    if (!video) {
      const track = liveVideoTrack(streamManager);
      if (!track) throw new ScreenCaptureError('NO_STREAM', '선택한 화면공유가 종료되었거나 아직 연결되지 않았습니다.');
      temp = attachTempVideo(track);
      video = temp;
      await waitForFrame(video, o.frameTimeoutMs);
    }
    const fit = fitWithin(video.videoWidth, video.videoHeight, o.maxLongSide);
    if (Math.min(fit.width, fit.height) < o.minSide) throw new ScreenCaptureError('NO_FRAME', '공유 화면이 너무 작아 분석할 수 없습니다.');
    if (isBlankFrame(video)) throw new ScreenCaptureError('BLANK_FRAME', '공유 화면이 아직 검은 화면입니다. 화면이 보인 뒤 다시 시도해 주세요.');
    const canvas = document.createElement('canvas');
    try {
      const encode = async (width, height, quality) => {
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) throw new ScreenCaptureError('ENCODE_FAILED', '이 브라우저는 화면 캡처(canvas)를 지원하지 않습니다.');
        ctx.drawImage(video, 0, 0, width, height); // 지금 프레임(같은 프레임을 품질만 바꿔 다시 인코딩할 수 있게 매번 다시 그린다)
        return canvasToJpeg(canvas, quality);
      };
      const out = await encodeWithinBudget(encode, fit, o);
      const base64 = out.base64 || await blobToBase64(out.blob);
      return { base64, mime: 'image/jpeg', width: out.width, height: out.height, bytes: out.size, quality: out.quality, source };
    } finally {
      canvas.width = 0; // 캔버스 메모리 즉시 반환
      canvas.height = 0;
    }
  } finally {
    detachTempVideo(temp);
  }
}

/** 탭 단위 요청 id(취소용). 서버 패턴 [A-Za-z0-9_-]{8,64}. */
export function newClientRequestId() {
  const rnd = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '') : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `sa_${rnd}`.slice(0, 40);
}
