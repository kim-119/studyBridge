// 공통 전체화면 보기 규칙(화면공유 스테이지, 이후 참가자 카메라 타일 확대에도 같은 규칙) — React 와 무관한 판단·DOM 헬퍼.
//
//  · 1순위: 브라우저 Fullscreen API(요소 전체화면). PC Chrome/Edge, Android Chrome, iPad Safari.
//  · 대체: CSS 전체화면 레이어(position:fixed + safe area + 스크롤 잠금 + 뒤로가기 항목). 다음 경우에 쓴다.
//    - 앱 WebView(Android System WebView·Capacitor): Capacitor 7 BridgeWebChromeClient.onShowCustomView 가
//      callback.onCustomViewHidden() 을 즉시 불러 requestFullscreen() 이 '성공' 직후 바로 풀린다 → 처음부터 CSS.
//    - iPhone Safari(요소 전체화면 없음 — video 전용 webkitEnterFullscreen 은 공유 선택·원본 크기 컨트롤이 사라져 쓰지 않는다)
//    - iframe 안(m. PC 폰 프레임 등, fullscreenEnabled=false)·요청 거부·진입 직후 곧바로 풀림(감지 시 자동 전환)
//  · 어느 모드든 같은 DOM 요소(같은 <video>·같은 OpenVidu Subscriber)를 그대로 보여준다 — 새 구독·새 Connection 없음.

export const FULLSCREEN_MODE = Object.freeze({ NATIVE: 'native', CSS: 'css' });

// native 진입이 받아들여진 뒤 이 시간 안에 (우리가 끄지 않았는데) 풀리면 환경이 전체화면을 막은 것으로 보고 CSS 로 바꾼다.
// 앱 WebView 의 해제는 onShowCustomView 안에서 곧바로 일어나 수십 ms 안이다. 길게 잡으면 진입 직후 Esc·뒤로가기로 나가려는
// 사용자를 CSS 레이어에 다시 가두게 되므로 짧게 둔다(WebView 는 UA 로 이미 CSS 를 고르고, 이 판정은 안전망).
export const NATIVE_EXIT_GRACE_MS = 500;

// 뒤로가기(Android 하드웨어 백·브라우저 뒤로)로 CSS 전체화면을 닫기 위한 history 항목 표식.
export const HISTORY_MARKER_KEY = 'sbFullscreenViewer';

export const fullscreenElementOf = (doc) => doc?.fullscreenElement || doc?.webkitFullscreenElement || null;

/** 앱 내장 WebView 여부: Capacitor 네이티브 플랫폼이거나 Android WebView UA('; wv)'). */
export function isEmbeddedWebView({ userAgent = '', capacitor = null } = {}) {
  try {
    if (capacitor && typeof capacitor.isNativePlatform === 'function' && capacitor.isNativePlatform()) return true;
  } catch (e) { /* ignore */ }
  return /;\s*wv\)/.test(String(userAgent));
}

/** 요소 전체화면 API 를 쓸 수 있는지(메서드 존재 + 문서가 허용 — iframe 의 allow 없음 등은 fullscreenEnabled=false). */
export function canRequestElementFullscreen(el, doc) {
  if (!el) return false;
  const hasMethod = typeof el.requestFullscreen === 'function' || typeof el.webkitRequestFullscreen === 'function';
  if (!hasMethod) return false;
  const enabled = doc?.fullscreenEnabled ?? doc?.webkitFullscreenEnabled;
  return enabled !== false;
}

/** 처음 시도할 모드. WebView 는 API 가 있어도 CSS(즉시 해제되므로), 그 밖에는 API 가 쓸 수 있으면 native. */
export function chooseFullscreenMode({ el, doc, userAgent, capacitor } = {}) {
  if (isEmbeddedWebView({ userAgent, capacitor })) return FULLSCREEN_MODE.CSS;
  return canRequestElementFullscreen(el, doc) ? FULLSCREEN_MODE.NATIVE : FULLSCREEN_MODE.CSS;
}

/** native 진입 직후 곧바로 풀렸는지(우리가 끈 게 아님) → CSS 로 대체해야 한다. */
export const isImmediateNativeExit = ({ enteredAt, now, exitRequested }) => !exitRequested && enteredAt !== null && enteredAt !== undefined && now - enteredAt < NATIVE_EXIT_GRACE_MS;

export function requestElementFullscreen(el) {
  if (typeof el?.requestFullscreen === 'function') return Promise.resolve(el.requestFullscreen({ navigationUI: 'hide' }));
  if (typeof el?.webkitRequestFullscreen === 'function') return Promise.resolve(el.webkitRequestFullscreen());
  return Promise.reject(Object.assign(new Error('Fullscreen API unsupported'), { name: 'NotSupportedError' }));
}

export function exitDocumentFullscreen(doc) {
  try {
    if (typeof doc?.exitFullscreen === 'function') return Promise.resolve(doc.exitFullscreen()).catch(() => {});
    if (typeof doc?.webkitExitFullscreen === 'function') doc.webkitExitFullscreen();
  } catch (e) { /* 이미 풀림 */ }
  return Promise.resolve();
}

/** 기존 history.state(React Router 의 idx·key·usr 포함)를 보존하면서 표식만 더한다 — 같은 URL, 라우터 인덱스 그대로. */
export const withHistoryMarker = (state, token) => ({ ...(state && typeof state === 'object' ? state : {}), [HISTORY_MARKER_KEY]: token });
export const hasHistoryMarker = (state, token) => !!state && typeof state === 'object' && state[HISTORY_MARKER_KEY] === token;

let scrollLocks = 0;
let savedScroll = null;

/** 문서 스크롤 잠금(중첩 안전). 반환값 = 해제 함수(여러 번 불러도 한 번만 해제). */
export function lockDocumentScroll(doc) {
  const html = doc?.documentElement;
  const body = doc?.body;
  if (!html || !body) return () => {};
  if (scrollLocks === 0) {
    savedScroll = { html: html.style.overflow, body: body.style.overflow, overscroll: body.style.overscrollBehavior };
    html.style.overflow = 'hidden';
    body.style.overflow = 'hidden';
    body.style.overscrollBehavior = 'none';
  }
  scrollLocks += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    scrollLocks = Math.max(0, scrollLocks - 1);
    if (scrollLocks === 0 && savedScroll) {
      html.style.overflow = savedScroll.html;
      body.style.overflow = savedScroll.body;
      body.style.overscrollBehavior = savedScroll.overscroll;
      savedScroll = null;
    }
  };
}

/** 전체화면(두 모드 공통) 호스트 스타일 — 안전 영역(노치·제스처 바)을 피하고 남은 높이를 내용이 채운다. */
export const FULLSCREEN_HOST_STYLE = Object.freeze({
  width: '100%',
  height: '100%',
  boxSizing: 'border-box',
  display: 'flex',
  flexDirection: 'column',
  backgroundColor: '#000',
  paddingTop: 'env(safe-area-inset-top, 0px)',
  paddingRight: 'env(safe-area-inset-right, 0px)',
  paddingBottom: 'env(safe-area-inset-bottom, 0px)',
  paddingLeft: 'env(safe-area-inset-left, 0px)',
});

/** CSS 모드 레이어(포털 대상의 직계 자식). 룸 루트(고정 오버레이, z 99999 맥락) 안에서 컨트롤바(96)·채팅 드로어(95) 위. */
export const CSS_LAYER_STYLE = Object.freeze({
  position: 'fixed',
  inset: '0',
  zIndex: '5000',
  display: 'flex',
  flexDirection: 'column',
  backgroundColor: '#000',
  overscrollBehavior: 'contain',
});
