// 렌더 회귀 확인(운영 또는 로컬 nginx): React 마운트 후 정적 소개가 교체되고, 경로별 title 이 적용되는지.
//   node src/__tests__/seo/render.check.mjs http://studybridge.co.kr 127.0.0.1:18089
import { chromium, devices } from 'playwright';
const [base = 'https://studybridge.co.kr', map] = process.argv.slice(2);
const launchArgs = map ? [`--host-resolver-rules=MAP studybridge.co.kr ${map}, MAP m.studybridge.co.kr ${map}`] : [];
const browser = await chromium.launch({ args: launchArgs });
let fail = 0;
const cases = [
  ['desktop', {}, '/', '스터디브릿지(StudyBridge) | AI 기반 통합 학습 플랫폼'],
  ['desktop', {}, '/login', '로그인 | 스터디브릿지(StudyBridge)'],
  ['desktop', {}, '/app', 'Android 앱 다운로드 | 스터디브릿지(StudyBridge)'],
  ['iphone', devices['iPhone 13'], '/', '스터디브릿지(StudyBridge) | AI 기반 통합 학습 플랫폼', 'm.'],
];
for (const [name, dev, p, title, sub = ''] of cases) {
  const ctx = await browser.newContext({ ...dev, viewport: dev.viewport || { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  const resp = await page.goto(base.replace('//', `//${sub}`) + p, { waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  const r = await page.evaluate(() => ({
    title: document.title, url: location.href,
    staticIntro: !!document.querySelector('#root > div > h1') && document.querySelector('#root h1')?.textContent.includes('스터디브릿지 (StudyBridge)'),
    rootChildren: document.getElementById('root').children.length,
    canon: [...document.querySelectorAll('link[rel=canonical]')].map((l) => l.href),
  }));
  const ok = r.title === title && !r.staticIntro && r.rootChildren > 0 && errors.length === 0 && resp.status() === 200 && r.canon.length === 1;
  if (!ok) fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name} ${p} → ${r.url} title="${r.title}" canon=${r.canon} staticIntroLeft=${r.staticIntro} errors=${errors.length}`);
  await ctx.close();
}
await browser.close();
process.exit(fail ? 1 : 0);
