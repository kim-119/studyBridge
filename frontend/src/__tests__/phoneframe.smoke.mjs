// 회귀 방지 smoke test (의존성 0, 러너 불필요)
//   실행:  node src/__tests__/phoneframe.smoke.mjs   (frontend 디렉토리에서)
//   목적:  m. 호스트 데스크톱 휴대폰 폭 프레임의 대상 판정(shouldUsePhoneFrame)·PC 화면 링크·바깥 주소 동기화를 검증한다.
import { shouldUsePhoneFrame, desktopUrlFor, syncPhoneFrameParent, PHONE_FRAME_HOST_CLASS } from '../utils/phoneFrame.js';

let pass = 0;
let fail = 0;
const check = (name, cond) => {
  if (cond) { pass += 1; console.log(`PASS ${name}`); } else { fail += 1; console.log(`FAIL ${name}`); }
};

const DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';
const fakeWin = ({ host = 'm.studybridge.co.kr', width = 1440, finePointer = true, framed = false, ua = DESKTOP_UA } = {}) => {
  const win = {
    location: { hostname: host, host, protocol: 'https:', pathname: '/groupstudy', search: '?a=1', hash: '' },
    navigator: { userAgent: ua },
    matchMedia: (q) => ({
      matches: q.includes('pointer: fine') ? finePointer : (q.includes('max-width: 768px') ? width <= 768 : false),
    }),
  };
  win.self = win;
  win.top = framed ? {} : win;
  return win;
};

check('m. + 데스크톱(마우스, 1440px) → 프레임', shouldUsePhoneFrame(fakeWin()) === true);
check('m. + 데스크톱 769px → 프레임', shouldUsePhoneFrame(fakeWin({ width: 769 })) === true);
check('m. + 데스크톱 좁은 창(768px) → 프레임 없음(이미 모바일 레이아웃)', shouldUsePhoneFrame(fakeWin({ width: 768 })) === false);
check('apex + 데스크톱 → 프레임 없음(PC 화면 불변)', shouldUsePhoneFrame(fakeWin({ host: 'studybridge.co.kr' })) === false);
check('www + 데스크톱 → 프레임 없음', shouldUsePhoneFrame(fakeWin({ host: 'www.studybridge.co.kr' })) === false);
check('m. + 휴대전화(터치 포인터) → 프레임 없음', shouldUsePhoneFrame(fakeWin({ width: 390, finePointer: false })) === false);
check('m. + 휴대전화 가로/태블릿(터치, 넓은 폭) → 프레임 없음', shouldUsePhoneFrame(fakeWin({ width: 932, finePointer: false })) === false);
check('m. + iframe 내부 → 프레임 없음(중첩 방지)', shouldUsePhoneFrame(fakeWin({ framed: true })) === false);
check('m. + 검색 로봇(Googlebot) → 프레임 없음', shouldUsePhoneFrame(fakeWin({ ua: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)' })) === false);
check('m. + 네이버 로봇(Yeti) → 프레임 없음', shouldUsePhoneFrame(fakeWin({ ua: 'Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)' })) === false);
check('matchMedia 없음 → 프레임 없음', shouldUsePhoneFrame({ ...fakeWin(), matchMedia: undefined }) === false);
check('location 접근 예외 → 프레임 없음', shouldUsePhoneFrame({ get location() { throw new Error('x'); } }) === false);

check('PC 화면 링크 = apex 같은 경로·쿼리', desktopUrlFor({ protocol: 'https:', host: 'm.studybridge.co.kr', pathname: '/groupstudy', search: '?a=1', hash: '#x' }) === 'https://studybridge.co.kr/groupstudy?a=1#x');

// ── 프레임 안 → 바깥 주소/제목 동기화 ─────────────────────────
const makeFramePair = (hostClass = PHONE_FRAME_HOST_CLASS) => {
  const calls = [];
  const parent = {
    location: { pathname: '/', search: '', hash: '' },
    history: { state: { k: 1 }, replaceState(state, _t, url) { calls.push(url); const u = new URL(url, 'https://m.studybridge.co.kr'); parent.location.pathname = u.pathname; parent.location.search = u.search; parent.location.hash = u.hash; } },
    document: { title: 'shell', documentElement: { classList: { contains: (c) => c === hostClass } } },
  };
  const listeners = {};
  const child = {
    location: { pathname: '/groupstudy', search: '', hash: '' },
    history: {
      pushState(_s, _t, url) { const u = new URL(url, 'https://m.studybridge.co.kr'); child.location.pathname = u.pathname; child.location.search = u.search; },
      replaceState(_s, _t, url) { const u = new URL(url, 'https://m.studybridge.co.kr'); child.location.pathname = u.pathname; child.location.search = u.search; },
    },
    document: { title: '스터디브릿지', querySelector: () => null },
    addEventListener: (ev, fn) => { listeners[ev] = fn; },
    parent,
  };
  child.self = child;
  child.top = parent;
  return { parent, child, calls, listeners };
};
{
  const { parent, child, calls } = makeFramePair();
  syncPhoneFrameParent(child);
  check('프레임 시작 시 바깥 주소 = 프레임 경로', parent.location.pathname === '/groupstudy' && calls.length === 1);
  check('바깥 제목 = 프레임 제목', parent.document.title === '스터디브릿지');
  child.history.pushState(null, '', '/archive?tab=PLANNER');
  check('pushState → 바깥 주소 동기화(쿼리 포함)', parent.location.pathname === '/archive' && parent.location.search === '?tab=PLANNER');
  check('바깥은 replaceState 만(히스토리 항목을 늘리지 않음)', calls.every((u) => typeof u === 'string') && calls.length === 2);
}
{
  const { parent, child, listeners } = makeFramePair();
  syncPhoneFrameParent(child);
  child.location.pathname = '/login';
  listeners.popstate();
  check('뒤로가기(popstate) → 바깥 주소 동기화', parent.location.pathname === '/login');
}
{
  const { parent, child, calls } = makeFramePair('other-class');
  syncPhoneFrameParent(child);
  check('우리 프레임 셸이 아니면 바깥을 건드리지 않음', calls.length === 0 && parent.location.pathname === '/');
}
{
  const child = { self: null, top: null };
  child.self = child; child.top = child;
  let threw = false;
  try { syncPhoneFrameParent(child); } catch { threw = true; }
  check('최상위(프레임 아님) → no-op', !threw);
}

console.log(`\nPHONEFRAME SMOKE pass=${pass} fail=${fail}`);
process.exit(fail ? 1 : 0);
