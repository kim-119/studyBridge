// 모바일 웹 라우트 전수 감사: chromium/webkit × 6 뷰포트 × 전체 사용자 라우트.
//  실행: node src/__tests__/mobile/audit.mjs
//  env : BASE(기본 http://127.0.0.1:4173) BROWSERS(chromium,webkit) DEVICES(이름,…) ROUTES(,구분) OUT(보고서 디렉토리)
//  결과: OUT/<browser>/<device>/<route>.png (뷰포트) + .full.png (전체), OUT/results.json, OUT/summary.md
//  판정: horiz(가로 스크롤) / offenders(뷰포트 이탈) 는 FAIL, 나머지(clipped/smallTargets/zoomInputs/inlineVh)는 WARN 지표.
import fs from 'node:fs';
import path from 'node:path';
import { DEVICES, pickDevices, pickBrowsers, loadCredentials, newMobileContext, login, LAYOUT_PROBE, ensureDir, nowTag, REPO_ROOT } from './lib.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:4173';
const OUT = process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `mobile_web_${nowTag()}`);
const PUBLIC_ROUTES = ['/', '/login', '/register', '/forgot-password', '/app'];
const PRIVATE_ROUTES = ['/studymate', '/learning-mate', '/groupstudy', '/archive', '/archive/pdf/345', '/review-notes', '/knowledge', '/study-report', '/weekly-schedule', '/planner', '/mindmap', '/obsidian', '/mypage'];
const ROUTES = process.env.ROUTES ? process.env.ROUTES.split(',') : [...PUBLIC_ROUTES, ...PRIVATE_ROUTES];
const browsers = pickBrowsers(process.env.BROWSERS);
const devices = pickDevices(process.env.DEVICES);
const creds = loadCredentials();
ensureDir(OUT);

const results = [];
const slug = (r) => (r === '/' ? 'root' : r.replace(/^\//, '').replace(/[\/:]/g, '_'));

for (const b of browsers) {
  const browser = await b.type.launch();
  for (const dev of devices) {
    const ctx = await newMobileContext(browser, dev);
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push('pageerror: ' + String(e.message).slice(0, 160)));
    page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text().slice(0, 160)); });
    const dir = ensureDir(path.join(OUT, b.name, dev.name));
    let loggedIn = false;
    let knowledgeDetail = null;
    const routes = [...ROUTES];
    for (let i = 0; i < routes.length; i++) {
      const route = routes[i];
      const needsAuth = !PUBLIC_ROUTES.includes(route);
      if (needsAuth && !loggedIn) {
        try { await login(page, BASE, creds); loggedIn = true; }
        catch (e) { results.push({ browser: b.name, device: dev.name, route, error: 'login failed: ' + String(e.message).slice(0, 120) }); continue; }
      }
      errors.length = 0;
      try {
        await page.goto(`${BASE}${route}`, { waitUntil: 'load', timeout: 45000 });
        await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
        await page.waitForTimeout(1200);
      } catch (e) {
        results.push({ browser: b.name, device: dev.name, route, error: String(e.message).slice(0, 120) });
        continue;
      }
      if (route === '/knowledge' && !knowledgeDetail) {
        knowledgeDetail = await page.evaluate(() => { const a = document.querySelector('a[href^="/knowledge/"]'); return a ? a.getAttribute('href') : null; }).catch(() => null);
        if (knowledgeDetail && !routes.includes(knowledgeDetail)) routes.splice(i + 1, 0, knowledgeDetail);
      }
      const info = await page.evaluate(LAYOUT_PROBE);
      const file = path.join(dir, slug(route));
      await page.screenshot({ path: file + '.png' }).catch(() => {});
      await page.screenshot({ path: file + '.full.png', fullPage: true }).catch(() => {});
      const filteredErrors = errors.filter((e) => !/ResizeObserver|favicon|net::ERR_|Failed to load resource/.test(e)).slice(0, 5);
      results.push({ browser: b.name, device: dev.name, vp: `${dev.width}x${dev.height}`, route, landed: info.path, ...info, errors: filteredErrors, screenshot: path.relative(OUT, file + '.png') });
      const flag = info.horiz ? `HORIZ sw=${info.sw}/${info.iw}` : (info.offenders.length ? 'OFFENDER' : 'ok');
      const off = info.offenders.length ? ' | ' + info.offenders.slice(0, 3).map((o) => `${o.sel}(+${o.over}/-${o.under},w${o.w},${o.pos})`).join(' ; ') : '';
      console.log(`[${b.name}/${dev.name}] ${route}${info.path !== route ? '→' + info.path : ''} ${flag}${off} | clip=${info.clippedCount} small=${info.smallTargetCount} zoom=${info.zoomInputCount} vh=${info.inlineVh}${filteredErrors.length ? ' | ERR ' + filteredErrors[0] : ''}`);
    }
    await ctx.close();
  }
  await browser.close();
}

fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: BASE, generatedAt: new Date().toISOString(), results }, null, 2));
const fails = results.filter((r) => r.error || r.horiz || (r.offenders && r.offenders.length));
const lines = [];
lines.push(`# Mobile web layout audit`, '', `- base: ${BASE}`, `- generated: ${new Date().toISOString()}`, `- browsers: ${browsers.map((b) => b.name).join(', ')}`, `- devices: ${devices.map((d) => `${d.name}(${d.width}x${d.height})`).join(', ')}`, `- cases: ${results.length}`, `- FAIL(horiz/offender/error): ${fails.length}`, '');
lines.push('| browser | device | route | landed | horiz | offenders | clipped | small | zoom<16 | inline100vh | errors |', '|---|---|---|---|---|---|---|---|---|---|---|');
for (const r of results) {
  if (r.error) { lines.push(`| ${r.browser} | ${r.device} | ${r.route} | ERROR | | ${r.error} | | | | | |`); continue; }
  lines.push(`| ${r.browser} | ${r.device} | ${r.route} | ${r.landed} | ${r.horiz ? `**${r.sw}/${r.iw}**` : 'no'} | ${r.offenders.length ? '**' + r.offenders.slice(0, 2).map((o) => `${o.sel}(+${o.over}/-${o.under})`).join('; ') + '**' : '-'} | ${r.clippedCount} | ${r.smallTargetCount} | ${r.zoomInputCount} | ${r.inlineVh} | ${r.errors.length ? r.errors[0].slice(0, 60) : '-'} |`);
}
fs.writeFileSync(path.join(OUT, 'summary.md'), lines.join('\n'));
console.log(`\nRESULT cases=${results.length} fail=${fails.length} out=${OUT}`);
process.exit(fails.length ? 1 : 0);
