// 운영 E2E(실 브라우저): apex 모바일 UA 내비게이션 → m. 302 추적, m. 에서 로그인/인증 API/새로고침/딥링크/WS 핸드셰이크/로그아웃,
//  데스크톱 UA 는 apex 유지 + 데스크톱 네비 노출. 실행: node src/__tests__/mobile/prod_m_e2e.mjs
//  env: APEX, MOBILE, BROWSERS(chromium,webkit), OUT
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { pickBrowsers, DEVICES, loadCredentials, newMobileContext, ensureDir, nowTag, REPO_ROOT } from './lib.mjs';

const APEX = process.env.APEX || 'https://studybridge.co.kr';
const MOBILE = process.env.MOBILE || 'https://m.studybridge.co.kr';
const OUT = ensureDir(process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `prod_m_e2e_${nowTag()}`));
const creds = loadCredentials();
const results = [];
const rec = (browser, name, ok, detail = '') => { results.push({ browser, name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'} [${browser}] ${name}${detail ? ' :: ' + detail : ''}`); };

for (const b of pickBrowsers(process.env.BROWSERS)) {
  const dev = b.name === 'webkit' ? { name: 'iphone-14', ...DEVICES['iphone-14'] } : { name: 'pixel-412', ...DEVICES['pixel-412'] };
  const browser = await b.type.launch();
  const ctx = await newMobileContext(browser, dev);
  const page = await ctx.newPage();
  const shot = (n) => page.screenshot({ path: path.join(OUT, `${b.name}_${n}.png`) }).catch(() => {});
  try {
    // 1) apex 딥링크(쿼리 포함) → m. 으로 302, 경로/쿼리 보존
    await page.goto(`${APEX}/login?next=%2Fgroupstudy`, { waitUntil: 'load', timeout: 45000 });
    const u1 = new URL(page.url());
    rec(b.name, 'apex deep link → m. (path+query 보존)', u1.host === new URL(MOBILE).host && u1.pathname === '/login' && u1.search === '?next=%2Fgroupstudy', page.url());
    await shot('01_redirected_login');
    // 2) m. 에서 로그인 → 토큰/프로필 API(인증) 동작
    await page.fill('input[name=email]', creds.email);
    await page.fill('input[name=password]', creds.password);
    await Promise.all([page.waitForURL((u) => !u.pathname.endsWith('/login'), { timeout: 30000 }), page.click('button[type=submit]')]);
    rec(b.name, 'm. 로그인', new URL(page.url()).host === new URL(MOBILE).host, page.url());
    const auth = await page.evaluate(async () => {
      const token = localStorage.getItem('token'); const userId = localStorage.getItem('userId');
      const r = await fetch('/api/users/profile', { headers: { Authorization: `Bearer ${token}` } });
      return { status: r.status, hasToken: Boolean(token), hasRefresh: Boolean(localStorage.getItem('refreshToken')), origin: location.origin };
    });
    rec(b.name, 'm. 인증 API(GET /api/users/profile) 200 + 토큰 저장', auth.status === 200 && auth.hasToken && auth.hasRefresh, JSON.stringify(auth));
    // 3) refresh 토큰 플로우(POST /api/users/refresh 가 새 accessToken 반환)
    const refreshed = await page.evaluate(async () => {
      const r = await fetch('/api/users/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refreshToken: localStorage.getItem('refreshToken') }) });
      const j = await r.json().catch(() => ({})); return { status: r.status, hasAccess: Boolean(j.accessToken) };
    });
    rec(b.name, 'm. refresh 토큰 플로우', refreshed.status === 200 && refreshed.hasAccess, JSON.stringify(refreshed));
    // 4) 보호 라우트 진입 + 새로고침 후 라우트/로그인 유지
    await page.goto(`${MOBILE}/studymate`, { waitUntil: 'load' }); await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    await page.reload({ waitUntil: 'load' }); await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    rec(b.name, 'm. /studymate 새로고침 후 라우트·세션 유지', new URL(page.url()).pathname === '/studymate', page.url());
    await shot('02_studymate');
    // 5) 딥링크 직접 접속(자료 상세) — 모바일 PDF 뷰어 분기 렌더
    await page.goto(`${MOBILE}/archive/pdf/345`, { waitUntil: 'load' }); await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    const pdfMobile = await page.locator('.pdf-viewer-mobile').count();
    rec(b.name, 'm. 딥링크 /archive/pdf/345 + 모바일 PDF 뷰어', new URL(page.url()).pathname === '/archive/pdf/345' && pdfMobile === 1, `pdfMobile=${pdfMobile}`);
    await shot('03_archive_pdf');
    // 6) WebSocket(SockJS) 핸드셰이크: /ws-group/info 동일 오리진 + 실제 WS 업그레이드
    const ws = await page.evaluate(async () => {
      const info = await fetch('/ws-group/info').then((r) => r.status).catch((e) => 'ERR ' + e.message);
      const up = await new Promise((resolve) => { try { const s = new WebSocket(`wss://${location.host}/ws-group/000/${Math.random().toString(36).slice(2, 10)}/websocket`); const t = setTimeout(() => { try { s.close(); } catch {} resolve('timeout'); }, 8000); s.onopen = () => { clearTimeout(t); s.close(); resolve('open'); }; s.onerror = () => { clearTimeout(t); resolve('error'); }; } catch (e) { resolve('ERR ' + e.message); } });
      return { info, up };
    });
    rec(b.name, 'm. WebSocket(/ws-group) info 200 + wss 업그레이드 open', ws.info === 200 && ws.up === 'open', JSON.stringify(ws));
    // 7) SSE 스타일 요청이 m. 에서 302 없이 백엔드로 감(헤더 Accept: text/event-stream)
    const sse = await page.evaluate(async () => { const r = await fetch('/api/app/version', { headers: { Accept: 'text/event-stream' } }); return { status: r.status, redirected: r.redirected, url: r.url }; });
    // Spring 이 text/event-stream 을 못 내는 엔드포인트라 406 을 돌려주는 것 자체가 "리다이렉트 없이 백엔드에 도달" 의 증거
    rec(b.name, 'm. SSE-style fetch 리다이렉트 없음(백엔드 도달)', !sse.redirected && sse.status !== 302 && sse.url.startsWith(MOBILE), JSON.stringify(sse));
    // 8) 로그아웃
    await page.goto(`${MOBILE}/`, { waitUntil: 'load' });
    await page.click('header button[aria-label="메뉴 열기"]');
    await page.getByRole('button', { name: '로그아웃' }).click();
    await page.waitForTimeout(1500);
    const loggedOut = await page.evaluate(() => !localStorage.getItem('token'));
    rec(b.name, 'm. 로그아웃', loggedOut, page.url());
  } catch (e) { rec(b.name, 'E2E 흐름', false, String(e.message).split('\n')[0].slice(0, 160)); await shot('error'); }
  await ctx.close(); await browser.close();
}

// 데스크톱 UA: apex 유지 + 데스크톱 네비 노출
{
  const browser = await chromium.launch(); const ctx = await browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'ko-KR' }); const page = await ctx.newPage();
  await page.goto(`${APEX}/groupstudy?x=1`, { waitUntil: 'load', timeout: 45000 });
  const u = new URL(page.url());
  const navVisible = await page.locator('header nav.lg\\:flex').first().isVisible().catch(() => false);
  rec('desktop', 'apex 데스크톱 UA → apex 유지(리다이렉트 없음) + 데스크톱 네비', u.host === new URL(APEX).host && navVisible, page.url());
  await page.screenshot({ path: path.join(OUT, 'desktop_apex.png') }).catch(() => {});
  await browser.close();
}
fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
const fail = results.filter((r) => !r.ok).length;
fs.writeFileSync(path.join(OUT, 'summary.md'), ['# Production m. E2E', '', `- apex: ${APEX}  mobile: ${MOBILE}`, `- cases: ${results.length} fail: ${fail}`, '', '| browser | case | result | detail |', '|---|---|---|---|', ...results.map((r) => `| ${r.browser} | ${r.name} | ${r.ok ? 'PASS' : 'FAIL'} | ${r.detail.replace(/\|/g, '\\|').slice(0, 120)} |`)].join('\n'));
console.log(`\nPROD M E2E cases=${results.length} fail=${fail} out=${OUT}`);
process.exit(fail ? 1 : 0);
