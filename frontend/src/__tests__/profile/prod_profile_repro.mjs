// TASK B 재현: 운영(studybridge.co.kr) MyPage 에서 이름/전공 변경 저장 → PUT /api/users/profile 네트워크 증거 수집.
// 토큰은 절대 출력하지 않는다(Authorization 헤더는 존재 여부만 기록).
import { chromium, webkit } from 'playwright';
import { loadCredentials, login, newMobileContext, DEVICES } from '../mobile/lib.mjs';

const BASE = process.env.BASE || 'https://studybridge.co.kr';
const MODE = process.env.MODE || 'desktop'; // desktop | chromium393 | webkit393
const SCENARIO = process.env.SCENARIO || 'name'; // name | major | both
const ORIGINAL = { displayName: 'SRE오답', major: '컴퓨터공학' };
const creds = loadCredentials();

const engine = MODE === 'webkit393' ? webkit : chromium;
const browser = await engine.launch();
const device = { ...DEVICES['iphone-15-pro'] };
const context = MODE === 'desktop'
  ? await browser.newContext({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR', ignoreHTTPSErrors: true })
  : await newMobileContext(browser, device);
const page = await context.newPage();
const evidence = [];
const dialogs = [];
page.on('dialog', async (d) => { dialogs.push(d.message()); await d.accept(); });
page.on('request', (req) => {
  if (req.url().includes('/api/users/profile') && req.method() !== 'GET') {
    let body = null; try { body = JSON.parse(req.postData() || 'null'); } catch { body = req.postData(); }
    evidence.push({ phase: 'request', method: req.method(), url: req.url().replace(BASE, ''), authorization: !!req.headers()['authorization'], payloadKeys: body && typeof body === 'object' ? Object.keys(body) : null, payload: body && typeof body === 'object' ? Object.fromEntries(Object.entries(body).map(([k, v]) => [k, typeof v === 'string' && v.length > 60 ? `${v.slice(0, 40)}…(len ${v.length})` : v])) : body });
  }
});
page.on('response', async (res) => {
  if (res.url().includes('/api/users/profile') && res.request().method() !== 'GET') {
    let text = ''; try { text = await res.text(); } catch { /* ignore */ }
    evidence.push({ phase: 'response', status: res.status(), contentType: res.headers()['content-type'], body: text.slice(0, 300) });
  }
});

await login(page, BASE, creds);
await page.goto(`${BASE}/mypage`, { waitUntil: 'load' });
await page.getByRole('button', { name: '프로필 수정' }).first().click();
const inputs = page.locator('input.input-field');
const nameInput = inputs.nth(0);
const majorInput = inputs.nth(1);
const before = { name: await nameInput.inputValue(), major: await majorInput.inputValue() };
const target = { name: before.name, major: before.major };
if (SCENARIO === 'name' || SCENARIO === 'both') target.name = 'SRE오답B';
if (SCENARIO === 'major' || SCENARIO === 'both') target.major = '전산학';
await nameInput.fill(target.name);
await majorInput.fill(target.major);
await page.getByRole('button', { name: '저장' }).first().click();
await page.waitForTimeout(2500);
const afterSave = { headerName: await page.locator('h3').first().innerText().catch(() => null) };

// 복원: 저장이 실패했든 성공했든 원래 값으로 되돌린다(현재 DOM 상태에 따라 수정 버튼이 있으면 누른다).
const editBtn = page.getByRole('button', { name: '프로필 수정' }).first();
if (await editBtn.isVisible().catch(() => false)) await editBtn.click();
await nameInput.fill(ORIGINAL.displayName);
await majorInput.fill(ORIGINAL.major);
await page.getByRole('button', { name: '저장' }).first().click();
await page.waitForTimeout(2500);
await page.reload({ waitUntil: 'load' });
const restored = { name: await inputs.nth(0).inputValue(), major: await inputs.nth(1).inputValue() };
const overflow = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth }));
console.log(JSON.stringify({ mode: MODE, scenario: SCENARIO, before, target, dialogs, evidence, afterSave, restored, overflow }, null, 2));
await browser.close();
