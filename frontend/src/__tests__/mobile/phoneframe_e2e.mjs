// m. 호스트 데스크톱 휴대폰 폭 프레임 E2E(Playwright 데스크톱 컨텍스트). 번들 미포함 테스트 전용.
//   실행(frontend 디렉토리): node src/__tests__/mobile/phoneframe_e2e.mjs
//   env : MOBILE(기본 https://m.studybridge.co.kr), APEX(기본 https://studybridge.co.kr), BROWSERS(chromium,webkit), OUT,
//         RESOLVE_PORT=4180 → chromium 이 m./apex 호스트를 127.0.0.1:<port>(serve-dist)로 해석(배포 전 로컬 번들 검증, http)
//   계약: 데스크톱(마우스·넓은 창)에서 m. → 430px 프레임 안에 모바일 레이아웃(햄버거, ≤768 미디어쿼리),
//         프레임 이동/뒤로가기 → 바깥 주소 동기화, 새로고침·딥링크 유지, 'PC 화면으로 보기' → apex 같은 경로,
//         apex 데스크톱·m. 휴대전화 컨텍스트는 프레임 없음(기존 동작), 프레임 안 카메라 권한 위임(https 에서만).
import fs from 'node:fs';
import path from 'node:path';
import { pickBrowsers, loadCredentials, ensureDir, nowTag, REPO_ROOT, DEVICES, newMobileContext } from './lib.mjs';

const PORT = process.env.RESOLVE_PORT || '';
const MOBILE = process.env.MOBILE || (PORT ? `http://m.studybridge.co.kr:${PORT}` : 'https://m.studybridge.co.kr');
const APEX = process.env.APEX || (PORT ? `http://studybridge.co.kr:${PORT}` : 'https://studybridge.co.kr');
const OUT = ensureDir(process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `phoneframe_e2e_${nowTag()}`));
const creds = loadCredentials();
const browsers = pickBrowsers(process.env.BROWSERS || (PORT ? 'chromium' : 'chromium,webkit'));
const DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36';

const results = [];
let failCount = 0;
const record = (ctx, name, ok, detail = '') => {
  results.push({ ...ctx, check: name, ok, detail });
  if (ok === false) failCount += 1;
  console.log(`${ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'} [${ctx.browser}/${ctx.vp}] ${name}${detail ? ` — ${detail}` : ''}`);
};
const pathOf = (url) => { const u = new URL(url); return `${u.pathname}${u.search}`; };
const waitFor = async (fn, timeout = 10000) => { const end = Date.now() + timeout; while (Date.now() < end) { if (await fn()) return true; await new Promise((r) => setTimeout(r, 200)); } return false; };

for (const b of browsers) {
  const launchArgs = b.name === 'chromium'
    ? ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', ...(PORT ? ['--host-resolver-rules=MAP m.studybridge.co.kr 127.0.0.1, MAP studybridge.co.kr 127.0.0.1'] : [])]
    : [];
  const browser = await b.type.launch({ args: launchArgs });
  for (const vp of [{ width: 1440, height: 900 }, { width: 1024, height: 768 }]) {
    const ctx = { browser: b.name, vp: `${vp.width}x${vp.height}` };
    const context = await browser.newContext({ viewport: vp, userAgent: b.name === 'chromium' ? DESKTOP_UA : undefined, locale: 'ko-KR', ignoreHTTPSErrors: true });
    if (b.name === 'chromium' && !PORT) await context.grantPermissions(['camera', 'microphone'], { origin: MOBILE });
    const page = await context.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push(`parent: ${e.message}`));
    const shot = (n) => page.screenshot({ path: path.join(OUT, `${b.name}_${vp.width}_${n}.png`) }).catch(() => {});
    try {
      // 1) m. 랜딩 → 프레임
      await page.goto(`${MOBILE}/`, { waitUntil: 'load', timeout: 45000 });
      const frameEl = page.locator('[data-testid=phone-frame]');
      await frameEl.waitFor({ timeout: 15000 });
      const box = await frameEl.boundingBox();
      record(ctx, '데스크톱 m. → 휴대폰 폭 프레임(430px, 가운데)', box && Math.round(box.width) === 430 && Math.abs(box.x + box.width / 2 - vp.width / 2) <= 1 && Math.round(box.height) === vp.height, JSON.stringify(box));
      const frame = await (await frameEl.elementHandle()).contentFrame();
      await frame.waitForSelector('header', { timeout: 20000 });
      const inner = await frame.evaluate(() => ({ w: window.innerWidth, mobileMq: window.matchMedia('(max-width: 768px)').matches }));
      record(ctx, '프레임 안 viewport ≤768(모바일 미디어쿼리 적용)', inner.mobileMq && inner.w <= 430, JSON.stringify(inner));
      record(ctx, '프레임 안 햄버거 버튼 표시(모바일 Navbar)', await frame.locator('header button[aria-label="메뉴 열기"]').isVisible());
      const parentHasApp = await page.evaluate(() => Boolean(document.querySelector('header')));
      record(ctx, '바깥 셸에는 앱을 렌더하지 않음(중복 마운트 없음)', !parentHasApp);
      await shot('1_landing');

      // 2) 햄버거 → 메뉴의 '로그인'(프레임 안) → 바깥 주소 동기화
      await frame.locator('header button[aria-label="메뉴 열기"]').click();
      await shot('2_menu');
      await frame.locator('header').getByRole('button', { name: '로그인', exact: true }).click();
      await frame.waitForSelector('input[name=email]', { timeout: 15000 });
      record(ctx, '프레임 안 이동 → 바깥 주소 /login', await waitFor(async () => pathOf(page.url()) === '/login'), pathOf(page.url()));
      await frame.fill('input[name=email]', creds.email);
      await frame.fill('input[name=password]', creds.password);
      await frame.click('button[type=submit]');
      const loggedIn = await waitFor(async () => !pathOf(frame.url()).startsWith('/login'), 30000);
      record(ctx, '프레임 안 로그인 성공 → 바깥 주소도 이동', loggedIn && pathOf(page.url()) === pathOf(frame.url()), `${pathOf(frame.url())} / ${pathOf(page.url())}`);

      // 3) 그룹스터디(목록) — 모바일 레이아웃 + 바깥 주소
      await frame.locator('header button[aria-label="메뉴 열기"]').click();
      await frame.locator('header nav.overflow-y-auto').getByText('그룹스터디', { exact: true }).click();
      await frame.waitForSelector('.gs-create-btn', { timeout: 20000 });
      await frame.waitForSelector('.glass-panel h3', { timeout: 10000 }).catch(() => {}); // 목록 로드(증거 스크린샷용)
      record(ctx, '메뉴 → 그룹스터디, 바깥 주소 /groupstudy', await waitFor(async () => pathOf(page.url()) === '/groupstudy'), pathOf(page.url()));
      const noHoriz = await frame.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
      record(ctx, '프레임 안 가로 overflow 없음', noHoriz);
      await shot('3_groupstudy');

      // 4) 뒤로가기 → 프레임·바깥 함께
      await page.goBack();
      record(ctx, '브라우저 뒤로가기 → 프레임 이전 화면 + 바깥 주소 동기화', await waitFor(async () => pathOf(page.url()) === pathOf(frame.url()) && pathOf(frame.url()) !== '/groupstudy'), `${pathOf(frame.url())} / ${pathOf(page.url())}`);
      await page.goForward();
      await waitFor(async () => pathOf(frame.url()) === '/groupstudy');

      // 5) 새로고침 → 같은 화면(프레임 src = 바깥 주소)
      await page.reload({ waitUntil: 'load' });
      const frame2 = await (await page.locator('[data-testid=phone-frame]').elementHandle()).contentFrame();
      await frame2.waitForSelector('.gs-create-btn', { timeout: 20000 }).catch(() => {});
      record(ctx, '새로고침 → 같은 화면 유지(/groupstudy, 로그인 유지)', pathOf(frame2.url()) === '/groupstudy' && await frame2.locator('.gs-create-btn').count() > 0, pathOf(frame2.url()));

      // 6) 프레임 안 카메라 권한 위임(https chromium 만)
      if (b.name === 'chromium' && !PORT) {
        const cam = await frame2.evaluate(async () => { try { const s = await navigator.mediaDevices.getUserMedia({ video: true, audio: true }); const n = s.getTracks().length; s.getTracks().forEach((t) => t.stop()); return `ok:${n}`; } catch (e) { return `err:${e.name}`; } });
        record(ctx, '프레임 안 getUserMedia(카메라+마이크) 동작', cam === 'ok:2', cam);
      } else {
        record(ctx, '프레임 안 getUserMedia(카메라+마이크) 동작', null, 'http 로컬/webkit 은 생략');
      }

      // 7) 'PC 화면으로 보기' → apex 같은 경로
      const link = page.locator('[data-testid=phone-frame-desktop-link]');
      await link.hover();
      const href = await link.getAttribute('href');
      record(ctx, "'PC 화면으로 보기' → apex 같은 경로", href === `${APEX}/groupstudy`, href);

      // 8) 딥링크(쿼리 포함)
      await page.goto(`${MOBILE}/login?from=e2e`, { waitUntil: 'load' });
      const src = await page.locator('[data-testid=phone-frame]').getAttribute('src');
      record(ctx, '딥링크 → 프레임 src 경로·쿼리 보존', src === '/login?from=e2e', src);

      record(ctx, 'pageerror 없음(바깥)', errs.length === 0, errs.slice(0, 2).join(' | '));
    } catch (e) {
      record(ctx, '실행', false, String(e.message).split('\n')[0].slice(0, 200));
      await shot('9_error');
    }
    await context.close();

    // 9) apex 데스크톱 → 프레임 없음(PC 화면 불변)
    const c2 = await browser.newContext({ viewport: vp, userAgent: b.name === 'chromium' ? DESKTOP_UA : undefined, ignoreHTTPSErrors: true });
    const p2 = await c2.newPage();
    await p2.goto(`${APEX}/`, { waitUntil: 'load', timeout: 45000 });
    await p2.waitForSelector('header', { timeout: 20000 });
    record(ctx, 'apex 데스크톱 → 프레임 없음 + 데스크톱 Navbar', await p2.locator('[data-testid=phone-frame]').count() === 0 && !(await p2.locator('header button[aria-label="메뉴 열기"]').isVisible()));
    await c2.close();
  }
  // 10) m. 휴대전화 컨텍스트 → 프레임 없음(기존 동작)
  const dev = { name: 'iphone-14', ...DEVICES['iphone-14'] };
  const c3 = await newMobileContext(browser, dev);
  const p3 = await c3.newPage();
  await p3.goto(`${MOBILE}/`, { waitUntil: 'load', timeout: 45000 });
  await p3.waitForSelector('header', { timeout: 20000 });
  record({ browser: b.name, vp: 'iphone-14' }, 'm. 휴대전화(터치) → 프레임 없음 + 모바일 Navbar', await p3.locator('[data-testid=phone-frame]').count() === 0 && await p3.locator('header button[aria-label="메뉴 열기"]').isVisible());
  await c3.close();
  await browser.close();
}

fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
console.log(`\nPHONEFRAME E2E checks=${results.length} fail=${failCount} mobile=${MOBILE} out=${OUT}`);
process.exit(failCount ? 1 : 0);
