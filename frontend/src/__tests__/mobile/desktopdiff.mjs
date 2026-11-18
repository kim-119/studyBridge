// 데스크톱 회귀: 기준 빌드(PORT_A, 기본 4174) vs 수정 빌드(PORT_B, 기본 4173) 를 같은 라우트/데스크톱 뷰포트에서 캡처해 픽셀 차이 비율을 비교.
//  실행: node src/__tests__/mobile/desktopdiff.mjs   (env VPS=1366x768,1440x900,1920x1080 ROUTES=… OUT=…)
//  기대: 모든 라우트 diff 0.00%(데스크톱 불변). 시간/애니메이션 의존 요소는 캡처 전에 정지한다.
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { chromium } from 'playwright';
import { loadCredentials, login, HERE, REPO_ROOT, nowTag, ensureDir } from './lib.mjs';

const VPS = (process.env.VPS || '1366x768,1440x900,1920x1080').split(',').map((s) => s.split('x').map(Number));
const ROUTES = (process.env.ROUTES || '/,/login,/register,/studymate,/learning-mate,/groupstudy,/archive,/archive/pdf/345,/review-notes,/knowledge,/knowledge/26,/study-report,/weekly-schedule,/planner,/mindmap,/mypage,/app').split(',');
const PA = process.env.PORT_A || 4174, PB = process.env.PORT_B || 4173;
const OUT = ensureDir(process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `desktop_diff_${nowTag()}`));
const creds = loadCredentials();
const browser = await chromium.launch();
async function mk(base, w, h) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h }, locale: 'ko-KR', reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await login(page, base, creds);
  return page;
}
const rows = []; let nonzero = 0;
for (const [w, h] of VPS) {
  const A = await mk('http://127.0.0.1:' + PA, w, h), B = await mk('http://127.0.0.1:' + PB, w, h);
  for (const r of ROUTES) {
    const files = [];
    for (const [tag, page, port] of [['base', A, PA], ['new', B, PB]]) {
      await page.goto(`http://127.0.0.1:${port}${r}`, { waitUntil: 'load' });
      await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
      await page.waitForTimeout(1500);
      await page.addStyleTag({ content: '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }' }).catch(() => {});
      await page.waitForTimeout(300);
      const f = path.join(OUT, `${w}_${tag}_${r.replace(/\//g, '_') || '_root'}.png`); await page.screenshot({ path: f, fullPage: false }); files.push(f);
    }
    const d = execFileSync('python3', ['-I', path.join(HERE, 'pngdiff.py'), files[0], files[1]]).toString().trim();
    const pct = parseFloat((d.match(/([\d.]+)%/) || [0, '0'])[1]);
    if (pct > 0) nonzero++;
    rows.push(`| ${w}x${h} | ${r} | ${d} |`);
    console.log(`${w}x${h} ${r} ${d}`);
  }
  await A.context().close(); await B.context().close();
}
await browser.close();
fs.writeFileSync(path.join(OUT, 'summary.md'), ['# Desktop pixel diff (base vs new)', '', `- base: :${PA}  new: :${PB}`, `- cases: ${rows.length}  nonzero: ${nonzero}`, '', '| viewport | route | diff |', '|---|---|---|', ...rows].join('\n'));
console.log(`\nDESKTOP DIFF cases=${rows.length} nonzero=${nonzero} out=${OUT}`);
