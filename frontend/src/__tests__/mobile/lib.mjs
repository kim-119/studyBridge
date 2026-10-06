// 모바일 웹 감사 공통 유틸(Playwright). 번들에 포함되지 않는 테스트 전용 모듈.
//  - 브라우저: chromium(Android Chrome 근사) / webkit(iOS Safari 근사). 실기기와 동일하다고 주장하지 않는다.
//  - 계정: MOBILE_E2E_EMAIL / MOBILE_E2E_PW 환경변수. 없으면 audit_reports 의 기존 E2E 픽스처 계정을 읽는다.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, webkit } from 'playwright';

export const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, '../../../..');

const UA_IOS = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const UA_ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36';

// 요구 뷰포트 6종(과제 명세) — w×h 는 CSS px, DPR 은 스크린샷 용량을 위해 1 로 고정(레이아웃 판정엔 영향 없음).
export const DEVICES = {
  'iphone-se':      { width: 375, height: 667, ua: UA_IOS, family: 'ios' },
  'iphone-14':      { width: 390, height: 844, ua: UA_IOS, family: 'ios' },
  'iphone-15-pro':  { width: 393, height: 852, ua: UA_IOS, family: 'ios' },
  'iphone-pro-max': { width: 430, height: 932, ua: UA_IOS, family: 'ios' },
  'android-360':    { width: 360, height: 780, ua: UA_ANDROID, family: 'android' },
  'pixel-412':      { width: 412, height: 915, ua: UA_ANDROID, family: 'android' },
};

export function pickDevices(spec) {
  const names = (spec || Object.keys(DEVICES).join(',')).split(',').map((s) => s.trim()).filter(Boolean);
  return names.map((n) => {
    if (DEVICES[n]) return { name: n, ...DEVICES[n] };
    const m = n.match(/^(\d+)x(\d+)$/);
    if (!m) throw new Error(`unknown device: ${n}`);
    return { name: n, width: Number(m[1]), height: Number(m[2]), ua: UA_ANDROID, family: 'android' };
  });
}

export function pickBrowsers(spec) {
  return (spec || 'chromium,webkit').split(',').map((s) => s.trim()).filter(Boolean).map((name) => {
    if (name === 'chromium') return { name, type: chromium };
    if (name === 'webkit') return { name, type: webkit };
    throw new Error(`unknown browser: ${name}`);
  });
}

export function loadCredentials() {
  if (process.env.MOBILE_E2E_EMAIL && process.env.MOBILE_E2E_PW) {
    return { email: process.env.MOBILE_E2E_EMAIL, password: process.env.MOBILE_E2E_PW };
  }
  const fixture = path.join(REPO_ROOT, 'audit_reports/learningmate_ec2_e2e_20260924T142154Z/tools/browser_race.js');
  if (fs.existsSync(fixture)) {
    const src = fs.readFileSync(fixture, 'utf8');
    const email = src.match(/const EMAIL = '([^']+)'/)?.[1];
    const password = src.match(/const PW = '([^']+)'/)?.[1];
    if (email && password) return { email, password };
  }
  throw new Error('MOBILE_E2E_EMAIL / MOBILE_E2E_PW 가 필요합니다');
}

export async function newMobileContext(browser, device, extra = {}) {
  return browser.newContext({
    viewport: { width: device.width, height: device.height },
    userAgent: device.ua,
    isMobile: true,
    hasTouch: true,
    deviceScaleFactor: 1,
    locale: 'ko-KR',
    ignoreHTTPSErrors: true,
    ...extra,
  });
}

export async function login(page, base, creds) {
  await page.goto(`${base}/login`, { waitUntil: 'load', timeout: 45000 });
  await page.fill('input[name=email]', creds.email);
  await page.fill('input[name=password]', creds.password);
  await Promise.all([
    page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 30000 }),
    page.click('button[type=submit]'),
  ]);
}

// 페이지 내 레이아웃 결함 측정(브라우저 안에서 실행).
export const LAYOUT_PROBE = () => {
  const iw = window.innerWidth;
  const ih = window.innerHeight;
  const de = document.documentElement;
  const sw = Math.max(de.scrollWidth, document.body.scrollWidth);
  const visible = (el, cs) => cs.display !== 'none' && cs.visibility !== 'hidden' && cs.opacity !== '0';
  const sel = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const cls = (typeof el.className === 'string' ? el.className : '').trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    if (cls) s += '.' + cls;
    return s;
  };
  // 조상 중 overflow 가 visible 이 아닌 요소가 있으면 그 사각형으로 잘린다(의도된 가로 스크롤 컨테이너/overflow:hidden 장식).
  // 요소의 가시 영역(조상 clip 사각형과의 교집합)이 뷰포트 안이면 이탈로 보지 않는다 — 실제 사용자에게 보이는 이탈만 결함으로 센다.
  const visibleRect = (el) => {
    let r = el.getBoundingClientRect();
    let left = r.left, right = r.right;
    let p = el.parentElement;
    while (p && p !== document.body) {
      const cs = getComputedStyle(p);
      if (cs.overflowX !== 'visible' || cs.overflow === 'clip') {
        const pr = p.getBoundingClientRect();
        left = Math.max(left, pr.left); right = Math.min(right, pr.right);
      }
      p = p.parentElement;
    }
    return { left, right };
  };
  const offenders = [];
  const clipped = [];
  const smallTargets = [];
  const zoomInputs = [];
  const fixedEls = [];
  let inlineVh = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const vr = visibleRect(el);
    const over = Math.round(vr.right - iw);
    const under = Math.round(-vr.left);
    if ((over > 2 || under > 2) && vr.right > vr.left) {
      offenders.push({ sel: sel(el), over, under, w: Math.round(r.width), pos: cs.position, text: (el.textContent || '').trim().slice(0, 30) });
    }
    if (cs.position === 'fixed' || cs.position === 'sticky') {
      fixedEls.push({ sel: sel(el), pos: cs.position, top: Math.round(r.top), bottom: Math.round(ih - r.bottom), h: Math.round(r.height), w: Math.round(r.width) });
    }
    const style = el.getAttribute('style') || '';
    if (/100vh/.test(style)) inlineVh++;
    // 텍스트 잘림 후보: overflow hidden 인 요소의 내용이 더 넓은데 말줄임도 아님
    if (el.children.length === 0 && (el.textContent || '').trim().length > 0 && /hidden|clip/.test(cs.overflowX) && el.scrollWidth > el.clientWidth + 3 && cs.textOverflow !== 'ellipsis') {
      clipped.push({ sel: sel(el), sw: el.scrollWidth, cw: el.clientWidth, text: (el.textContent || '').trim().slice(0, 30) });
    }
    const tag = el.tagName;
    const interactive = tag === 'A' || tag === 'BUTTON' || tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA' || el.getAttribute('role') === 'button';
    if (interactive) {
      if ((tag !== 'INPUT' || !['checkbox', 'radio'].includes(el.type)) && (r.height < 32 || r.width < 32) && r.width > 0 && r.height > 0) {
        smallTargets.push({ sel: sel(el), w: Math.round(r.width), h: Math.round(r.height), text: (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 24) });
      }
      if ((tag === 'INPUT' && !['checkbox', 'radio', 'range', 'file', 'hidden'].includes(el.type)) || tag === 'SELECT' || tag === 'TEXTAREA') {
        const fs = parseFloat(cs.fontSize);
        if (fs < 16) zoomInputs.push({ sel: sel(el), fontSize: fs });
      }
    }
  }
  offenders.sort((a, b) => Math.max(b.over, b.under) - Math.max(a.over, a.under));
  return {
    iw, ih, sw, horiz: sw > iw + 1,
    offenders: offenders.slice(0, 12),
    clipped: clipped.slice(0, 10), clippedCount: clipped.length,
    smallTargets: smallTargets.slice(0, 8), smallTargetCount: smallTargets.length,
    zoomInputs: zoomInputs.slice(0, 8), zoomInputCount: zoomInputs.length,
    fixedEls: fixedEls.slice(0, 10), inlineVh,
    path: location.pathname, title: document.title,
  };
};

export function ensureDir(p) { fs.mkdirSync(p, { recursive: true }); return p; }
export const nowTag = () => new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
