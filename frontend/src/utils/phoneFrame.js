// m.studybridge.co.kr 를 데스크톱 PC(마우스·넓은 창)에서 열 때 모바일 웹 화면을 보여주는 휴대폰 폭 프레임.
//  · 모바일 UI 는 viewport(≤768px) 기반 반응형이라 넓은 데스크톱 창에서는 데스크톱 레이아웃이 나온다.
//    → 같은 앱을 휴대폰 폭 iframe 으로 띄워 iframe 의 viewport 를 휴대폰 폭으로 만든다(CSS/번들 중복 없음).
//  · 대상 아님(기존 동작 그대로): apex/www 호스트, 휴대전화·태블릿(터치 우선 포인터), 이미 좁은 창, 검색 로봇, iframe 내부.
//  · 프레임 안 앱의 주소/제목은 바깥 주소창에 그대로 반영한다(새로고침·주소 복사 시 같은 화면).

export const PHONE_FRAME_WIDTH = 430;
export const PHONE_FRAME_HOST_CLASS = 'sb-phone-frame-host';
const MOBILE_MAX_WIDTH = 768; // index.css @media (max-width: 768px) · useIsMobile 과 같은 기준
const BOT_UA = /bot|crawl|spider|slurp|yeti|daum|facebookexternalhit|lighthouse/i;

export const isMobileWebHost = (hostname) => /^m\./i.test(hostname || '');

export function shouldUsePhoneFrame(win) {
  try {
    if (!isMobileWebHost(win.location.hostname)) return false;
    if (win.self !== win.top) return false;
    if (BOT_UA.test(win.navigator?.userAgent || '')) return false;
    if (typeof win.matchMedia !== 'function') return false;
    // 마우스(정밀 포인터+hover) 가 주 입력인 기기만 = 데스크톱/노트북. 휴대전화 가로 모드·태블릿은 제외.
    if (!win.matchMedia('(hover: hover) and (pointer: fine)').matches) return false;
    return !win.matchMedia(`(max-width: ${MOBILE_MAX_WIDTH}px)`).matches;
  } catch {
    return false;
  }
}

// apex 같은 경로(데스크톱 화면으로 보기). m.studybridge.co.kr → studybridge.co.kr
export const desktopUrlFor = (loc) => `${loc.protocol}//${loc.host.replace(/^m\./i, '')}${loc.pathname}${loc.search}${loc.hash}`;

export function mountPhoneFrame(win, doc) {
  const loc = win.location;
  doc.documentElement.classList.add(PHONE_FRAME_HOST_CLASS);
  doc.body.style.margin = '0';
  doc.body.style.overflow = 'hidden';

  const root = doc.getElementById('root');
  root.innerHTML = '';
  const stage = doc.createElement('div');
  stage.setAttribute('data-testid', 'phone-frame-stage');
  stage.style.cssText = 'position:fixed;inset:0;display:flex;justify-content:center;background:#E7ECE7;';

  const frame = doc.createElement('iframe');
  frame.src = `${loc.pathname}${loc.search}${loc.hash}`;
  frame.title = '스터디브릿지 모바일 웹';
  frame.setAttribute('data-testid', 'phone-frame');
  // 그룹스터디 카메라·마이크·화면공유·자동재생·전체화면·복사가 프레임 안에서도 동작하도록 같은 오리진에 위임
  frame.setAttribute('allow', 'camera; microphone; display-capture; autoplay; fullscreen; clipboard-read; clipboard-write; screen-wake-lock');
  frame.setAttribute('allowfullscreen', '');
  frame.style.cssText = `width:min(${PHONE_FRAME_WIDTH}px,100%);height:100%;border:0;display:block;background:#fff;box-shadow:0 0 0 1px rgba(0,0,0,0.06),0 12px 40px rgba(0,0,0,0.12);`;

  const toDesktop = doc.createElement('a');
  toDesktop.href = desktopUrlFor(loc);
  toDesktop.textContent = 'PC 화면으로 보기';
  toDesktop.setAttribute('data-testid', 'phone-frame-desktop-link');
  toDesktop.style.cssText = 'position:fixed;right:16px;bottom:16px;padding:8px 14px;border-radius:999px;background:#fff;color:#374151;font:600 13px/1.4 system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,0.12);';
  // 프레임 안에서 이동한 현재 경로(바깥 주소에 동기화됨)를 따라간다
  const refreshDesktopHref = () => { toDesktop.href = desktopUrlFor(loc); };
  toDesktop.addEventListener('mouseenter', refreshDesktopHref);
  toDesktop.addEventListener('focus', refreshDesktopHref);

  stage.appendChild(frame);
  root.appendChild(stage);
  root.appendChild(toDesktop);
}

// 프레임 안(같은 오리진의 우리 프레임 셸 안일 때만): 라우트 이동마다 바깥 주소·제목을 맞춘다.
export function syncPhoneFrameParent(win) {
  let parent;
  try {
    if (win.self === win.top) return;
    parent = win.parent;
    if (!parent.document.documentElement.classList.contains(PHONE_FRAME_HOST_CLASS)) return;
  } catch {
    return; // 다른 오리진에 임베드된 경우 등 — 아무것도 하지 않는다
  }
  const sync = () => {
    try {
      const url = `${win.location.pathname}${win.location.search}${win.location.hash}`;
      const current = `${parent.location.pathname}${parent.location.search}${parent.location.hash}`;
      if (url !== current) parent.history.replaceState(parent.history.state, '', url);
      if (win.document.title && parent.document.title !== win.document.title) parent.document.title = win.document.title;
    } catch { /* 바깥 동기화 실패는 앱 동작에 영향 없음 */ }
  };
  ['pushState', 'replaceState'].forEach((method) => {
    const original = win.history[method];
    win.history[method] = function patchedHistory(...args) {
      const result = original.apply(this, args);
      sync();
      return result;
    };
  });
  win.addEventListener('popstate', sync);
  win.addEventListener('hashchange', sync);
  const titleEl = win.document.querySelector('title');
  if (titleEl && typeof win.MutationObserver === 'function') {
    new win.MutationObserver(sync).observe(titleEl, { childList: true, characterData: true, subtree: true });
  }
  sync();
}
