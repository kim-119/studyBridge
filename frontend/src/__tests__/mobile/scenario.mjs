// 모바일 상호작용 시나리오 감사: 햄버거/모달/탭/패널/입력 포커스/키보드 근사/스크롤 끝/뒤로가기/새로고침 등 상태별 레이아웃 측정.
//  실행: node src/__tests__/mobile/scenario.mjs
//  env : BASE BROWSERS DEVICES OUT  (기본 chromium,webkit × iphone-se,android-360,iphone-14)
//  각 step: 스크린샷 + LAYOUT_PROBE(가로 overflow/이탈 요소) + 모달/드로어 뷰포트 초과 + fixed 하단 바 가림 검사.
import fs from 'node:fs';
import path from 'node:path';
import { pickDevices, pickBrowsers, loadCredentials, newMobileContext, login, LAYOUT_PROBE, ensureDir, nowTag, REPO_ROOT } from './lib.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:4173';
const OUT = process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `mobile_scenario_${nowTag()}`);
const browsers = pickBrowsers(process.env.BROWSERS);
const devices = pickDevices(process.env.DEVICES || 'iphone-se,android-360,iphone-14');
const creds = loadCredentials();
ensureDir(OUT);
const results = [];

// 모달/드로어/오버레이가 뷰포트를 넘는지 + 하단 fixed 바가 마지막 콘텐츠를 가리는지 (브라우저 안에서 실행)
const OVERLAY_PROBE = () => {
  const iw = window.innerWidth, ih = window.innerHeight;
  const out = { modalsOverflow: [], drawerOverflow: [], hiddenBottomPx: 0, focusedVisible: null };
  const inFixedOverlay = (el) => { let p = el; while (p && p !== document.body) { const cs = getComputedStyle(p); if (cs.position === 'fixed' && parseInt(cs.zIndex || '0', 10) >= 100) return true; p = p.parentElement; } return false; };
  const cands = [...document.querySelectorAll('[role=dialog], .modal-content, .gs-modal, .glass-panel, [class*=modal], [class*=drawer], nav, [class*=sheet]')];
  for (const el of cands) {
    const cs = getComputedStyle(el); if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    // .glass-panel 은 페이지 본문 카드로도 쓰인다 → fixed 오버레이(모달) 안에 있을 때만 모달 후보로 본다
    if (el.classList.contains('glass-panel') && !el.classList.contains('modal-content') && !inFixedOverlay(el)) continue;
    const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue;
    // 화면 밖으로 완전히 밀어 둔(닫힌) 드로어(translateX(110%) 등)는 숨김 상태 → 대상 아님
    if (r.left >= iw || r.right <= 0 || r.top >= ih || r.bottom <= 0) continue;
    const over = { right: Math.round(r.right - iw), left: Math.round(-r.left), bottom: Math.round(r.bottom - ih), top: Math.round(-r.top) };
    const scrollable = /(auto|scroll)/.test(cs.overflowY) || [...el.querySelectorAll('*')].some((c) => /(auto|scroll)/.test(getComputedStyle(c).overflowY));
    if (over.right > 2 || over.left > 2 || (over.bottom > 2 && cs.position === 'fixed') || (over.bottom > 2 && !scrollable && /dialog|modal/.test(el.className + el.getAttribute('role')))) {
      out.modalsOverflow.push({ sel: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : ''), ...over, w: Math.round(r.width), h: Math.round(r.height), scrollable });
    }
  }
  const a = document.activeElement;
  if (a && /INPUT|TEXTAREA/.test(a.tagName)) {
    const r = a.getBoundingClientRect();
    out.focusedVisible = r.top >= 0 && r.bottom <= ih;
    out.focusedRect = { top: Math.round(r.top), bottom: Math.round(r.bottom), ih };
  }
  return out;
};

const slug = (s) => s.replace(/[^a-z0-9가-힣_-]+/gi, '_');

for (const b of browsers) {
  const browser = await b.type.launch(b.name === 'chromium' ? { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] } : {});
  for (const dev of devices) {
    const ctx = await newMobileContext(browser, dev, b.name === 'chromium' ? { permissions: ['camera', 'microphone'] } : {});
    const page = await ctx.newPage();
    page.on('dialog', (d) => d.accept());
    const errs = []; page.on('pageerror', (e) => errs.push(String(e.message).slice(0, 140)));
    const dir = ensureDir(path.join(OUT, b.name, dev.name));
    let n = 0;
    const go = (p) => page.goto(`${BASE}${p}`, { waitUntil: 'load', timeout: 45000 });
    const clickText = async (t, i = 0) => { const l = page.getByText(t, { exact: false }).nth(i); await l.waitFor({ timeout: 6000 }); await l.click(); };
    const STEP_FILTER = process.env.STEPS ? new RegExp(process.env.STEPS) : null; // 예: STEPS=groupstudy → 그룹 흐름만
    async function step(name, fn, opts = {}) {
      n++; const id = `${String(n).padStart(2, '0')}_${slug(name)}`;
      if (STEP_FILTER && !STEP_FILTER.test(name)) return;
      let stepErr = null;
      try { await fn(); await page.waitForLoadState('networkidle', { timeout: 6000 }).catch(() => {}); await page.waitForTimeout(opts.wait ?? 900); }
      catch (e) { stepErr = String(e.message).split('\n')[0].slice(0, 140); }
      await page.screenshot({ path: path.join(dir, id + '.png') }).catch(() => {});
      if (opts.full) await page.screenshot({ path: path.join(dir, id + '.full.png'), fullPage: true }).catch(() => {});
      const layout = await page.evaluate(LAYOUT_PROBE).catch(() => null);
      const overlay = await page.evaluate(OVERLAY_PROBE).catch(() => null);
      const e = errs.splice(0).filter((x) => !/ResizeObserver|favicon/i.test(x));
      const rec = { browser: b.name, device: dev.name, vp: `${dev.width}x${dev.height}`, step: id, url: page.url().replace(BASE, ''), stepErr, horiz: layout?.horiz, sw: layout?.sw, iw: layout?.iw, offenders: layout?.offenders || [], modalsOverflow: overlay?.modalsOverflow || [], focusedVisible: overlay?.focusedVisible, focusedRect: overlay?.focusedRect, errors: e.slice(0, 3), screenshot: path.relative(OUT, path.join(dir, id + '.png')) };
      results.push(rec);
      const flag = rec.horiz ? `HORIZ ${rec.sw}/${rec.iw}` : rec.offenders.length ? 'OFFENDER' : rec.modalsOverflow.length ? 'MODAL-OVERFLOW' : rec.focusedVisible === false ? 'FOCUS-HIDDEN' : 'ok';
      console.log(`[${b.name}/${dev.name}] ${id} ${rec.url} ${flag}${rec.offenders.length ? ' | ' + rec.offenders.slice(0, 2).map((o) => `${o.sel}(+${o.over}/-${o.under},w${o.w})`).join('; ') : ''}${rec.modalsOverflow.length ? ' | ' + rec.modalsOverflow.slice(0, 2).map((m) => `${m.sel}(r${m.right},b${m.bottom})`).join('; ') : ''}${stepErr ? ' | STEP-ERR ' + stepErr : ''}${e.length ? ' | ERR ' + e[0] : ''}`);
    }
    // 키보드 표시 근사: 뷰포트 높이를 45% 로 줄인 뒤 포커스된 입력창이 보이는지 측정
    const withKeyboard = async (fn) => { await page.setViewportSize({ width: dev.width, height: Math.round(dev.height * 0.45) }); try { await fn(); } finally { /* 복원은 다음 step 전 */ } };
    const restoreVp = () => page.setViewportSize({ width: dev.width, height: dev.height });

    // ── 공개 화면 ──
    await step('landing', async () => { await go('/'); }, { full: true });
    await step('landing_menu_open', async () => { await page.click('header button[aria-label="메뉴 열기"]'); });
    await step('landing_menu_close', async () => { await page.click('header button[aria-label="메뉴 닫기"]'); });
    await step('landing_scroll_bottom', async () => { await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight)); });
    await step('login_empty_submit', async () => { await go('/login'); await page.click('button[type=submit]'); });
    await step('login_wrong_pw', async () => { await page.fill('input[name=email]', 'nobody@example.com'); await page.fill('input[name=password]', 'wrongpassword1!'); await page.click('button[type=submit]'); await page.waitForTimeout(1500); });
    await step('login_focus_keyboard', async () => { await withKeyboard(async () => { await page.click('input[name=password]'); }); });
    await step('register_full', async () => { await restoreVp(); await go('/register'); }, { full: true });
    await step('register_validation', async () => { await page.fill('input[name=email]', 'bad'); await page.fill('input[name=displayName]', 'x'); await page.fill('input[name=password]', 'short'); await page.fill('input[name=passwordConfirm]', 'mismatch'); for (const c of await page.locator('input[type=checkbox]').all()) await c.check().catch(() => {}); await page.click('button[type=submit]', { timeout: 5000, force: true }).catch(() => {}); });
    await step('register_long_text', async () => { await page.fill('input[name=email]', 'averyveryveryverylongemailaddress.for.mobile.testing@studybridge-example-domain.test'); await page.fill('input[name=major]', '컴퓨터공학과 인공지능융합전공 소프트웨어학부 데이터사이언스'); });
    await step('forgot_password', async () => { await go('/forgot-password'); }, { full: true });
    await step('app_download', async () => { await go('/app'); }, { full: true });

    // ── 로그인 ──
    let authed = true;
    try { await login(page, BASE, creds); } catch (e) { authed = false; console.log('LOGIN FAILED', e.message); }
    if (authed) {
      await step('home_authed', async () => { await go('/'); }, { full: true });
      await step('home_menu_authed', async () => { await page.click('header button[aria-label="메뉴 열기"]'); });
      await step('home_menu_scrolled', async () => { await page.evaluate(() => { const nav = document.querySelector('header nav.overflow-y-auto'); if (nav) nav.scrollTop = 9999; }); });
      // 학습메이트
      await step('studymate', async () => { await go('/studymate'); });
      await step('studymate_left_open', async () => { await page.locator('.pane-toggle-left').click(); });
      await step('studymate_room_selected', async () => { await page.locator('.dt-agent-card').first().click(); });
      await step('studymate_chat_full', async () => {}, { full: true });
      await step('studymate_input_focus', async () => { const inp = page.locator('.chat-input-premium input, .chat-input-premium textarea').first(); await inp.click(); await page.keyboard.type('모바일 테스트 질문입니다. 아주 긴 문장을 입력해서 입력창이 어떻게 늘어나는지 확인합니다.'); });
      await step('studymate_input_keyboard', async () => { await withKeyboard(async () => { await page.locator('.chat-input-premium input, .chat-input-premium textarea').first().click(); }); });
      await step('studymate_professor_tab', async () => { await restoreVp(); await page.getByText('교수님들과 대화', { exact: true }).click(); });
      await step('studymate_professor_full', async () => {}, { full: true });
      await step('studymate_mindmap_tab', async () => { await page.getByText('마인드맵', { exact: true }).last().click(); });
      await step('studymate_right_open', async () => { await page.locator('.pane-toggle-right').click(); });
      await step('studymate_backdrop_close', async () => { await page.locator('.pane-backdrop').click({ position: { x: 20, y: 120 }, timeout: 5000 }); });
      await step('studymate_back_nav', async () => { await page.goBack(); });
      // 학습메이트(질문 중심)
      await step('learning_mate', async () => { await go('/learning-mate'); }, { full: true });
      await step('learning_mate_input', async () => { const inp = page.locator('textarea, input[type=text]').first(); await inp.click(); await page.keyboard.type('재귀 함수란 무엇인가요? 예시와 함께 자세히 설명해 주세요. 긴 질문 입력 테스트입니다.'); });
      await step('learning_mate_keyboard', async () => { await withKeyboard(async () => { await page.locator('textarea, input[type=text]').first().click(); }); });
      // 그룹스터디
      // 임시 그룹 픽스처: 계정이 방장인 그룹을 API 로 만들어 '스터디 입장' 흐름을 재현하고, 룸 단계가 끝나면 삭제한다
      let fixtureGroupId = null;
      await step('groupstudy_fixture_create', async () => {
        await restoreVp(); await go('/groupstudy');
        fixtureGroupId = await page.evaluate(async () => {
          const fd = new FormData(); const d = new Date(); const end = new Date(d.getTime() + 30 * 86400000);
          const iso = (x) => x.toISOString().slice(0, 10);
          for (const [k, v] of Object.entries({ title: 'MOBILE-AUDIT-TMP ' + Date.now(), hashtags: 'mobile,audit', description: '모바일 감사 임시 그룹(자동 삭제)', startDate: iso(d), endDate: iso(end), capacity: 2, isPublic: true, studyType: 'GENERAL', targetStudyMinutes: 240, joinQuestionEnabled: false, nicknameRuleEnabled: false })) fd.append(k, String(v));
          const r = await fetch('/api/groups', { method: 'POST', headers: { Authorization: 'Bearer ' + localStorage.getItem('token') }, body: fd });
          const j = await r.json().catch(() => ({})); return r.ok ? (j.id || j.groupId || null) : null;
        });
        if (!fixtureGroupId) throw new Error('fixture group create failed');
        await go('/groupstudy');
      });
      await step('groupstudy_list', async () => { await restoreVp(); await go('/groupstudy'); }, { full: true });
      await step('groupstudy_detail_modal', async () => { await page.locator('.gs-card-badges').first().click(); }, { full: true });
      await step('groupstudy_detail_scrolled', async () => { await page.evaluate(() => { const m = [...document.querySelectorAll('div')].find((d) => getComputedStyle(d).overflowY === 'auto' && d.closest('[style*="z-index: 1000"]')); if (m) m.scrollTop = 9999; }); });
      await step('groupstudy_enter_prejoin', async () => {
        await page.keyboard.press('Escape').catch(() => {}); await page.mouse.click(5, 5).catch(() => {}); await page.waitForTimeout(400);
        const cards = page.locator('.gs-card-badges'); const count = await cards.count(); let found = false;
        for (let i = 0; i < count && !found; i++) {
          await cards.nth(i).click(); await page.waitForTimeout(700);
          const btn = page.locator('button', { hasText: '스터디 입장' });
          if (await btn.count()) { await btn.first().click(); found = true; }
          else { await page.keyboard.press('Escape').catch(() => {}); await page.mouse.click(5, 5); await page.waitForTimeout(400); }
        }
        if (!found) throw new Error('joined group not found');
      }, { full: true, wait: 1500 });
      await step('groupstudy_enter_room', async () => { const enter = page.locator('button', { hasText: /^\s*입장\s*$/ }).last(); await enter.click({ timeout: 6000 }); await page.waitForTimeout(800); const ok = page.locator('button', { hasText: /^확인$/ }); if (await ok.count()) await ok.first().click(); await page.waitForTimeout(5000); }, { full: true });
      await step('groupstudy_room_chat', async () => { await page.locator('.room-mobile-controlbar button[aria-label="채팅"]').click({ timeout: 5000 }); }, { full: true });
      await step('groupstudy_room_chat_input', async () => { const inp = page.locator('.room-chat-input input, .room-chat-input textarea, input[placeholder*="메시지"]').first(); await inp.click({ timeout: 5000 }); await page.keyboard.type('그룹 채팅 모바일 입력 테스트 메시지'); });
      await step('groupstudy_room_chat_keyboard', async () => { await withKeyboard(async () => { await page.locator('.room-chat-input input, .room-chat-input textarea, input[placeholder*="메시지"]').first().click({ timeout: 5000 }); }); });
      await step('groupstudy_room_chat_close', async () => { await restoreVp(); await page.locator('.room-mobile-controlbar button[aria-label="채팅"]').click({ timeout: 5000 }); });
      await step('groupstudy_room_manage', async () => { await page.locator('.room-dock div[style*="cursor"]').first().click({ timeout: 5000 }); }, { full: true });
      await step('groupstudy_fixture_delete', async () => {
        if (!fixtureGroupId) return;
        await go('/groupstudy');
        const st = await page.evaluate(async (id) => (await fetch(`/api/groups/${id}`, { method: 'DELETE', headers: { Authorization: 'Bearer ' + localStorage.getItem('token') } })).status, fixtureGroupId);
        if (st >= 300) throw new Error('fixture delete status ' + st);
      });
      await step('groupstudy_create_modal', async () => { await go('/groupstudy'); await page.locator('.gs-create-btn').first().click(); }, { full: true });
      await step('groupstudy_create_modal_keyboard', async () => { await withKeyboard(async () => { await page.locator('input[placeholder*="스터디 이름"]').first().click({ timeout: 5000 }); }); });
      // 자료보관함
      await step('archive', async () => { await restoreVp(); await go('/archive'); }, { full: true });
      await step('archive_planner_tab', async () => { await page.locator('.archive-tab', { hasText: '플래너' }).click(); }, { full: true });
      await step('archive_journal_tab', async () => { await clickText('학습일지'); }, { full: true });
      await step('archive_pdf_detail', async () => { await go('/archive/pdf/345'); }, { full: true });
      await step('archive_summary', async () => { await clickText('요약'); }, { full: true });
      await step('archive_quiz', async () => { await clickText('퀴즈/문제 생성'); }, { full: true });
      await step('archive_roadmap', async () => { await clickText('주차별 로드맵'); }, { full: true });
      await step('archive_memo', async () => { await clickText('메모'); }, { full: true });
      await step('archive_chat', async () => { await clickText('AI 질문'); }, { full: true });
      await step('archive_chat_keyboard', async () => { await withKeyboard(async () => { await page.locator('textarea, input[type=text]').last().click({ timeout: 5000 }); }); });
      // 오답노트
      await step('review_notes', async () => { await restoreVp(); await go('/review-notes'); }, { full: true });
      await step('review_retry', async () => { await clickText('다시 풀기', 1); }, { full: true });
      await step('review_similar', async () => { await go('/review-notes'); await clickText('유사문제 풀기', 1); }, { full: true });
      await step('review_explain', async () => { await go('/review-notes'); await clickText('AI 해설', 1); await page.locator('button:has-text("오답 2")').first().click({ timeout: 4000 }); }, { full: true });
      // 지식공유
      await step('knowledge', async () => { await go('/knowledge'); }, { full: true });
      await step('knowledge_detail', async () => { await page.locator('a[href^="/knowledge/"], [class*=kn-card]').first().click(); }, { full: true });
      await step('knowledge_detail_refresh', async () => { await page.reload({ waitUntil: 'load' }); });
      // 리포트/주간일정/플래너/마인드맵/마이페이지
      await step('study_report', async () => { await go('/study-report'); }, { full: true });
      await step('weekly_schedule', async () => { await go('/weekly-schedule'); }, { full: true });
      await step('weekly_week_view', async () => { await page.locator('button', { hasText: /^주$/ }).first().click(); }, { full: true });
      await step('planner', async () => { await go('/planner'); }, { full: true });
      await step('planner_first_item', async () => { await page.locator('[class*=planner-card], [class*=planner-item], .planner-list button, .planner-list a').first().click({ timeout: 5000 }); }, { full: true });
      await step('mindmap', async () => { await go('/mindmap'); });
      await step('mindmap_room', async () => { await page.locator('.mindmap-aside button').first().click({ timeout: 5000 }); });
      await step('mypage', async () => { await go('/mypage'); }, { full: true });
      await step('mypage_security', async () => { await clickText('비밀번호 및 보안'); }, { full: true });
      await step('deep_link_refresh', async () => { await go('/archive/pdf/345'); await page.reload({ waitUntil: 'load' }); });
      await step('logout', async () => { await go('/'); await page.click('header button[aria-label="메뉴 열기"]'); await page.getByRole('button', { name: '로그아웃' }).click(); await page.waitForTimeout(1500); });
    } else {
      results.push({ browser: b.name, device: dev.name, step: 'LOGIN', blocked: true });
    }
    await ctx.close();
  }
  await browser.close();
}
fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify({ base: BASE, generatedAt: new Date().toISOString(), results }, null, 2));
const fails = results.filter((r) => r.horiz || (r.offenders && r.offenders.length) || (r.modalsOverflow && r.modalsOverflow.length) || r.focusedVisible === false);
const lines = [`# Mobile interaction scenario audit`, '', `- base: ${BASE}`, `- cases: ${results.length}`, `- FAIL(horiz/offender/modal-overflow/focus-hidden): ${fails.length}`, `- step errors(selector 미존재 등, 레이아웃 판정과 별개): ${results.filter((r) => r.stepErr).length}`, '', '| browser | device | step | url | horiz | offenders | modal overflow | focus visible | step err |', '|---|---|---|---|---|---|---|---|---|'];
for (const r of results) lines.push(`| ${r.browser} | ${r.device} | ${r.step} | ${r.url || ''} | ${r.horiz ? `**${r.sw}/${r.iw}**` : 'no'} | ${(r.offenders || []).length ? '**' + r.offenders.slice(0, 2).map((o) => `${o.sel}(+${o.over}/-${o.under})`).join('; ') + '**' : '-'} | ${(r.modalsOverflow || []).length ? '**' + r.modalsOverflow.slice(0, 2).map((m) => `${m.sel}(r${m.right},b${m.bottom})`).join('; ') + '**' : '-'} | ${r.focusedVisible === undefined || r.focusedVisible === null ? '-' : r.focusedVisible} | ${r.stepErr || '-'} |`);
fs.writeFileSync(path.join(OUT, 'summary.md'), lines.join('\n'));
console.log(`\nSCENARIO RESULT cases=${results.length} fail=${fails.length} out=${OUT}`);
process.exit(fails.length ? 1 : 0);
