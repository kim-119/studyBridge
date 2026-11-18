// 그룹 초대/기본 아이콘/퀴즈 랭킹 탭/게시판 정렬/CTA 라우팅 — 실브라우저 E2E(운영 또는 로컬 preview).
//  실행: node src/__tests__/groupfeatures_e2e.mjs   env: BASE(기본 https://studybridge.co.kr) MOBILE=1(모바일 뷰포트) OUT
//  픽스처: 방장 = 기존 E2E 계정, 초대받는 사용자 = 즉석 가입(@studybridge.test). 끝에 그룹을 삭제한다.
import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';
import { loadCredentials, login, newMobileContext, DEVICES, LAYOUT_PROBE, ensureDir, nowTag, REPO_ROOT } from './mobile/lib.mjs';

const BASE = process.env.BASE || 'https://studybridge.co.kr';
const MOBILE = process.env.MOBILE === '1';
const OUT = ensureDir(process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `group_features_${MOBILE ? 'mobile' : 'desktop'}_${nowTag()}`));
const creds = loadCredentials();
const results = [];
const rec = (name, ok, detail = '') => { results.push({ name, ok, detail: String(detail) }); console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' :: ' + String(detail).slice(0, 160) : ''}`); };

const browser = await chromium.launch();
const mkCtx = async () => MOBILE
  ? newMobileContext(browser, { name: 'pixel-412', ...DEVICES['pixel-412'] })
  : browser.newContext({ viewport: { width: 1366, height: 768 }, locale: 'ko-KR', ignoreHTTPSErrors: true });
const api = (page, method, p, body) => page.evaluate(async ({ method, p, body }) => {
  const r = await fetch(p, { method, headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + localStorage.getItem('token') }, body: body ? JSON.stringify(body) : undefined });
  const t = await r.text(); let j = null; try { j = JSON.parse(t); } catch {} return { status: r.status, json: j };
}, { method, p, body });
const shot = (page, n) => page.screenshot({ path: path.join(OUT, `${n}.png`), fullPage: false }).catch(() => {});
const noHoriz = async (page) => { const r = await page.evaluate(LAYOUT_PROBE); return !r.horiz && r.offenders.length === 0; };

const ctxA = await mkCtx(); const A = await ctxA.newPage();
let groupId = null; let inviteUrl = null;
const ts = Date.now();
try {
  // 0) CTA: 비로그인 → /login
  await A.goto(`${BASE}/`, { waitUntil: 'load' });
  await A.getByRole('button', { name: '무료로 시작하기' }).click();
  await A.waitForURL((u) => /\/login$/.test(u.pathname), { timeout: 15000 }).catch(() => {});
  rec('CTA 비로그인 → /login', /\/login$/.test(new URL(A.url()).pathname), A.url());
  // 로그인(방장 A)
  await login(A, BASE, creds);
  // 1) CTA: 로그인 → /studymate
  await A.goto(`${BASE}/`, { waitUntil: 'load' }); await A.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await A.getByRole('button', { name: '무료로 시작하기' }).click();
  await A.waitForURL((u) => /\/studymate$/.test(u.pathname), { timeout: 15000 }).catch(() => {});
  rec('CTA 로그인 → /studymate', /\/studymate$/.test(new URL(A.url()).pathname), A.url());

  // 2) 게시판 정렬: 칩 클릭 → sort 파라미터 + 순서
  const reqs = []; A.on('request', (r) => { if (r.url().includes('/api/blogs')) reqs.push(r.url()); });
  await A.goto(`${BASE}/knowledge`, { waitUntil: 'load' }); await A.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await A.getByRole('tab', { name: '인기순' }).click(); await A.waitForTimeout(1200);
  await A.getByRole('tab', { name: '오래된순' }).click(); await A.waitForTimeout(1200);
  rec('게시판 정렬 칩 → ?sort=popular / oldest 요청', reqs.some((u) => u.includes('sort=popular')) && reqs.some((u) => u.includes('sort=oldest')), reqs.slice(-3).join(' | '));
  const oldest = await api(A, 'GET', '/api/blogs?sort=oldest'); const latest = await api(A, 'GET', '/api/blogs?sort=latest');
  rec('oldest/latest 역순 일치', oldest.status === 200 && latest.status === 200 && oldest.json[0]?.blogId === latest.json[latest.json.length - 1]?.blogId, `${oldest.json?.length} posts`);
  rec('게시판(정렬 칩 포함) 가로 overflow 없음', await noHoriz(A));
  await shot(A, '01_knowledge_sort');

  // 3) 비공개 CAM 그룹 생성(API) → 카드 기본 아이콘(CAM=Video) + '초대 전용' CTA
  groupId = await A.evaluate(async (ts) => {
    const fd = new FormData(); const d = new Date(); const end = new Date(d.getTime() + 30 * 86400000); const iso = (x) => x.toISOString().slice(0, 10);
    for (const [k, v] of Object.entries({ title: 'INVITE-UI-' + ts, hashtags: 'e2e', description: '초대 UI E2E 임시 그룹', startDate: iso(d), endDate: iso(end), capacity: 3, isPublic: false, studyType: 'CAM', targetStudyMinutes: 240, joinQuestionEnabled: false, nicknameRuleEnabled: false })) fd.append(k, String(v));
    const r = await fetch('/api/groups', { method: 'POST', headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }, body: fd }); const j = await r.json(); return r.ok ? j.id : null;
  }, ts);
  rec('비공개 CAM 그룹 생성(API)', Boolean(groupId), groupId);
  await A.goto(`${BASE}/groupstudy`, { waitUntil: 'load' }); await A.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await A.getByRole('button', { name: /비공개방/ }).first().click(); await A.waitForTimeout(600); // 기본 필터는 공개 스터디
  const card = A.locator('.glass-panel', { hasText: 'INVITE-UI-' + ts }).first();
  await card.waitFor({ timeout: 10000 });
  const camIcon = await card.locator('svg.lucide-video').count();
  rec('카드 기본 아이콘 = CAM(Video) + 외부 썸네일 없음', camIcon >= 1 && (await card.locator('img[src*="unsplash"]').count()) === 0, `video icons=${camIcon}`);
  await shot(A, '02_group_card_cam_icon');

  // 4) 방장 관리 콘솔 → 초대 패널 → 링크 생성/복사
  await card.locator('.gs-card-badges').click(); await A.waitForTimeout(600);
  await A.getByRole('button', { name: /스터디 입장/ }).first().click(); await A.waitForTimeout(1200);
  await A.getByText('방장 관리', { exact: false }).first().click().catch(() => {});
  await A.waitForTimeout(800);
  const panel = A.locator('.gs-invite-panel').first();
  await panel.waitFor({ timeout: 8000 });
  await panel.getByRole('button', { name: /초대 링크 생성/ }).click();
  const linkInput = panel.locator('input[aria-label="초대 링크"]');
  await linkInput.waitFor({ timeout: 8000 });
  inviteUrl = await linkInput.inputValue();
  rec('초대 링크 생성 (현재 오리진 + /groups/invite/{token})', inviteUrl.startsWith(`${BASE}/groups/invite/`) && inviteUrl.split('/').pop().length === 43, inviteUrl);
  await panel.getByRole('button', { name: '링크 복사' }).click(); await A.waitForTimeout(400);
  rec('복사 버튼 → 복사됨 표시', (await panel.getByText('복사됨').count()) === 1);
  rec('초대 패널 가로 overflow 없음', await noHoriz(A));
  await shot(A, '03_invite_panel');
  // 재생성 → 토큰 변경, 폐기 → 생성 버튼 복귀
  await panel.getByRole('button', { name: /링크 재생성/ }).click(); await A.waitForTimeout(1000);
  const inviteUrl2 = await linkInput.inputValue();
  rec('링크 재생성 → 새 토큰', inviteUrl2 !== inviteUrl && inviteUrl2.includes('/groups/invite/'));
  inviteUrl = inviteUrl2;

  // 5) 초대받는 사용자 B: 가입 → 초대 링크 열기(비로그인 → 로그인 복귀) → 참여
  const emailB = `grp.ui.b.${ts}@studybridge.test`, pwB = 'E2e!pass' + String(ts).slice(-4);
  const reg = await A.evaluate(async ({ emailB, pwB }) => (await fetch('/api/users/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: emailB, password: pwB, passwordConfirm: pwB, displayName: 'UI-B', major: 'E2E' }) })).status, { emailB, pwB });
  rec('B 계정 가입', [200, 201].includes(reg), reg);
  const ctxB = await mkCtx(); const B = await ctxB.newPage();
  await B.goto(inviteUrl, { waitUntil: 'load' });
  await B.waitForURL((u) => /\/login$/.test(u.pathname), { timeout: 15000 }).catch(() => {});
  rec('B 비로그인 초대 링크 → /login 리다이렉트', /\/login$/.test(new URL(B.url()).pathname), B.url());
  await B.fill('input[name=email]', emailB); await B.fill('input[name=password]', pwB);
  await Promise.all([B.waitForURL((u) => u.pathname.startsWith('/groups/invite/'), { timeout: 20000 }), B.click('button[type=submit]')]);
  rec('로그인 후 초대 페이지로 복귀', new URL(B.url()).pathname.startsWith('/groups/invite/'), B.url());
  await B.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await B.getByText('INVITE-UI-' + ts).waitFor({ timeout: 10000 });
  rec('초대 페이지 미리보기(그룹명·캠 스터디)', (await B.getByText('캠 스터디').count()) >= 1);
  rec('초대 페이지 가로 overflow 없음', await noHoriz(B));
  await shot(B, '04_invite_page');
  await B.getByRole('button', { name: '스터디 참여하기' }).click();
  await B.waitForURL((u) => /\/groupstudy$/.test(u.pathname), { timeout: 15000 });
  rec('B 참여 → /groupstudy', true, B.url());
  const members = await api(B, 'GET', `/api/groups/${groupId}/members`);
  rec('B 가 MEMBER 로 가입됨', members.status === 200 && members.json.some((m) => m.role === 'MEMBER'), JSON.stringify(members.json?.map((m) => m.role)));
  // B 가 다시 열면 '이미 참여 중'
  await B.goto(inviteUrl, { waitUntil: 'load' }); await B.getByText('이미 참여 중인 스터디입니다.').waitFor({ timeout: 10000 });
  rec('재방문 → 이미 참여 중 표시(멱등)', true);
  // B: 초대 생성 403 (서버 권한)
  const forb = await api(B, 'POST', `/api/groups/${groupId}/invitations`, {});
  rec('MEMBER 초대 생성 → 403(서버)', forb.status === 403, forb.status);
  const del = await api(B, 'DELETE', `/api/groups/${groupId}`);
  rec('MEMBER 그룹 삭제 → 403(서버)', del.status === 403, del.status);

  // 6) 스터디룸 '퀴즈 랭킹' 탭(B)
  await B.goto(`${BASE}/groupstudy`, { waitUntil: 'load' }); await B.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await B.getByRole('button', { name: /비공개방/ }).first().click(); await B.waitForTimeout(600);
  const cardB = B.locator('.glass-panel', { hasText: 'INVITE-UI-' + ts }).first(); await cardB.waitFor({ timeout: 10000 });
  await cardB.locator('.gs-card-badges').click(); await B.waitForTimeout(600);
  await B.getByRole('button', { name: /스터디 입장/ }).first().click(); await B.waitForTimeout(1200);
  B.on('dialog', (d) => d.accept());
  const enter = B.locator('button', { hasText: /^\s*입장\s*$/ }).last(); await enter.click({ timeout: 8000 }); await B.waitForTimeout(800);
  const ok = B.locator('button', { hasText: /^확인$/ }); if (await ok.count()) await ok.first().click();
  await B.waitForTimeout(4000);
  await B.locator('.room-dock div[title="실시간 퀴즈"]').first().click({ timeout: 8000 });
  await B.getByText('퀴즈 랭킹', { exact: true }).click({ timeout: 8000 });
  await B.locator('.gs-ranking-table tbody tr').first().waitFor({ timeout: 10000 });
  const rows = await B.locator('.gs-ranking-table tbody tr').count();
  const header = await B.locator('.gs-ranking-table thead').innerText();
  rec('퀴즈 랭킹 탭: 순위/닉네임/점수/정답률/정답 수 + 멤버 행', rows >= 2 && /순위/.test(header) && /정답률/.test(header) && /정답 수/.test(header), `rows=${rows}`);
  rec('랭킹 탭 가로 overflow 없음(표는 내부 스크롤)', await noHoriz(B));
  await shot(B, '05_ranking_tab');
  await ctxB.close();
} catch (e) {
  rec('E2E 흐름', false, String(e.message).split('\n')[0]);
  await shot(A, 'error');
} finally {
  if (groupId) { const d = await api(A, 'DELETE', `/api/groups/${groupId}`); rec('방장 그룹 삭제(정리) → 204', d.status === 204, d.status); }
  await ctxA.close(); await browser.close();
}
fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
const fail = results.filter((r) => !r.ok).length;
fs.writeFileSync(path.join(OUT, 'summary.md'), ['# Group features E2E', '', `- base: ${BASE} mobile: ${MOBILE}`, `- cases: ${results.length} fail: ${fail}`, '', '| case | result | detail |', '|---|---|---|', ...results.map((r) => `| ${r.name} | ${r.ok ? 'PASS' : 'FAIL'} | ${r.detail.replace(/\|/g, '\\|').slice(0, 120)} |`)].join('\n'));
console.log(`\nGROUP FEATURES E2E cases=${results.length} fail=${fail} out=${OUT}`);
process.exit(fail ? 1 : 0);
