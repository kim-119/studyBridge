// 단일 라우트 이탈 요소 진단(조상 체인/인라인 style/outerHTML). 실행: ROUTE=/studymate DEVICE=iphone-se BROWSER=chromium node src/__tests__/mobile/inspect.mjs
import { pickBrowsers, pickDevices, loadCredentials, newMobileContext, login, LAYOUT_PROBE } from './lib.mjs';
const BASE = process.env.BASE || 'http://127.0.0.1:4173';
const route = process.env.ROUTE || '/';
const [b] = pickBrowsers(process.env.BROWSER || 'chromium');
const [dev] = pickDevices(process.env.DEVICE || 'iphone-se');
const browser = await b.type.launch(); const ctx = await newMobileContext(browser, dev); const page = await ctx.newPage();
if (process.env.NOAUTH !== '1') await login(page, BASE, loadCredentials());
await page.goto(BASE + route, { waitUntil: 'load' }); await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {}); await page.waitForTimeout(1200);
if (process.env.ACTION) await page.evaluate(process.env.ACTION); // 간단한 상태 조작(JS 문자열)
if (process.env.ACTION) await page.waitForTimeout(800);
const probe = await page.evaluate(LAYOUT_PROBE);
console.log(`route=${route} ${dev.name} ${b.name} iw=${probe.iw} sw=${probe.sw} horiz=${probe.horiz} offenders=${probe.offenders.length} clipped=${probe.clippedCount} small=${probe.smallTargetCount} zoom=${probe.zoomInputCount}`);
const detail = await page.evaluate(() => {
  const iw = window.innerWidth; const out = [];
  const desc = (p) => p.tagName.toLowerCase() + (p.className && typeof p.className === 'string' ? '.' + p.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + `[l${Math.round(p.getBoundingClientRect().left)} w${Math.round(p.getBoundingClientRect().width)} ${getComputedStyle(p).position} ox:${getComputedStyle(p).overflowX}]`;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect(); if (!r.width && !r.height) continue;
    if (r.right - iw > 2 || -r.left > 2) {
      const chain = []; let p = el; for (let i = 0; i < 6 && p && p !== document.body; i++) { chain.push(desc(p)); p = p.parentElement; }
      out.push({ chain: chain.join(' < '), style: (el.getAttribute('style') || '').slice(0, 160), html: el.outerHTML.replace(/\s+/g, ' ').slice(0, 140) });
    }
  }
  const wide = [...document.querySelectorAll('body *')].filter((el) => { const cs = getComputedStyle(el); const mw = parseFloat(cs.minWidth); return mw > iw || parseFloat(cs.width) > iw + 2; }).slice(0, 6).map(desc);
  return { out: out.slice(0, 10), wide };
});
for (const o of detail.out) console.log('RAW-OFFENDER', o.chain, '\n   style:', o.style, '\n   html:', o.html);
console.log('MIN/FIXED-WIDTH > viewport:', detail.wide);
console.log('clipped:', JSON.stringify(probe.clipped.slice(0, 5)));
console.log('smallTargets:', JSON.stringify(probe.smallTargets.slice(0, 6)));
console.log('zoomInputs:', JSON.stringify(probe.zoomInputs.slice(0, 6)));
console.log('fixed/sticky:', JSON.stringify(probe.fixedEls));
await browser.close();
