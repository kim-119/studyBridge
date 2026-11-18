// 감사 결과 비교/집계: BEFORE(기준) 와 AFTER(수정) results.json 을 읽어 결함 수·회귀를 표로 만든다.
//  실행: node src/__tests__/mobile/report.mjs --before <dir> --after <dir> [--scenario-before <dir> --scenario-after <dir>] --out <file.md>
import fs from 'node:fs';
import path from 'node:path';

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, arr) => { if (v.startsWith('--')) a.push([v.slice(2), arr[i + 1]]); return a; }, []));
const load = (dir) => (dir && fs.existsSync(path.join(dir, 'results.json')) ? JSON.parse(fs.readFileSync(path.join(dir, 'results.json'), 'utf8')) : null);
const key = (r) => `${r.browser}|${r.device}|${r.route || r.step}`;
const isFail = (r) => Boolean(r.error || r.horiz || (r.offenders && r.offenders.length) || (r.modalsOverflow && r.modalsOverflow.length));

function summarize(data, label) {
  if (!data) return { label, cases: 0, fail: 0, horiz: 0, offenders: 0, zoom: 0, small: 0, clipped: 0, errors: 0, byBrowser: {} };
  const rs = data.results;
  const s = { label, cases: rs.length, fail: rs.filter(isFail).length, horiz: rs.filter((r) => r.horiz).length, offenders: rs.filter((r) => r.offenders && r.offenders.length).length, zoom: rs.filter((r) => r.zoomInputCount > 0).length, small: rs.reduce((a, r) => a + (r.smallTargetCount || 0), 0), clipped: rs.filter((r) => r.clippedCount > 0).length, errors: rs.filter((r) => r.errors && r.errors.length).length, byBrowser: {} };
  for (const r of rs) { const b = s.byBrowser[r.browser] ||= { cases: 0, fail: 0 }; b.cases++; if (isFail(r)) b.fail++; }
  return s;
}
const before = load(args.before), after = load(args.after);
const sb = summarize(before, 'before'), sa = summarize(after, 'after');
const lines = ['# Mobile audit comparison', ''];
lines.push('| metric | before | after |', '|---|---|---|');
for (const k of ['cases', 'fail', 'horiz', 'offenders', 'zoom', 'clipped', 'small', 'errors']) lines.push(`| ${k} | ${sb[k]} | ${sa[k]} |`);
for (const b of new Set([...Object.keys(sb.byBrowser), ...Object.keys(sa.byBrowser)])) lines.push(`| ${b} fail/cases | ${sb.byBrowser[b]?.fail ?? '-'} / ${sb.byBrowser[b]?.cases ?? '-'} | ${sa.byBrowser[b]?.fail ?? '-'} / ${sa.byBrowser[b]?.cases ?? '-'} |`);
if (before && after) {
  const bm = new Map(before.results.map((r) => [key(r), r]));
  const regress = after.results.filter((r) => isFail(r) && !(bm.get(key(r)) && isFail(bm.get(key(r)))));
  const fixed = before.results.filter((r) => isFail(r) && after.results.find((x) => key(x) === key(r)) && !isFail(after.results.find((x) => key(x) === key(r))));
  lines.push('', `- regressions (after FAIL, before OK): ${regress.length}`, `- fixed (before FAIL, after OK): ${fixed.length}`);
  for (const r of regress) lines.push(`  - REGRESSION ${key(r)} ${r.error || ''} ${r.horiz ? 'horiz' : ''} ${(r.offenders || []).slice(0, 2).map((o) => o.sel).join(',')}`);
  const remaining = after.results.filter(isFail);
  lines.push(`- remaining FAIL after: ${remaining.length}`);
  for (const r of remaining) lines.push(`  - ${key(r)}: ${r.error || ''}${r.horiz ? ` horiz ${r.sw}/${r.iw}` : ''} ${(r.offenders || []).slice(0, 2).map((o) => `${o.sel}(+${o.over}/-${o.under})`).join('; ')} ${(r.modalsOverflow || []).slice(0, 2).map((m) => `${m.sel}(r${m.right},b${m.bottom})`).join('; ')}`);
}
const md = lines.join('\n');
if (args.out) fs.writeFileSync(args.out, md);
console.log(md);
