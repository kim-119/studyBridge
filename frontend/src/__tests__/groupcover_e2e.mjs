// 그룹 생성 대표 이미지 E2E(Playwright, 모바일 Chromium/WebKit). 번들 미포함 테스트 전용.
//   실행(frontend 디렉토리): BASE=https://m.studybridge.co.kr node src/__tests__/groupcover_e2e.mjs
//   env : BASE, DEVICES(기본 android-360,iphone-14,iphone-pro-max), BROWSERS, CASES(default,preset,upload,none), OUT,
//         LEGACY=1 → 수정 전 번들(프리셋 testid 없음)에서 버그 재현만(프리셋 선택 → image 파트 없음 → 기본 아이콘)
//   계약: 생성 폼 미리보기 = POST /api/groups image 파트 = 응답 coverImageUrl = 목록 카드 = 상세 모달 = 수정 모달.
//         preset 은 asset 원본과 S3 저장본의 sha256 이 같아야 한다. 각 케이스가 만든 그룹은 끝에 DELETE 로 지운다.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { pickBrowsers, pickDevices, newMobileContext, login, loadCredentials, ensureDir, nowTag, REPO_ROOT } from './mobile/lib.mjs';

const BASE = process.env.BASE || 'http://127.0.0.1:4180';
const OUT = ensureDir(process.env.OUT || path.join(REPO_ROOT, 'audit_reports', `groupcover_e2e_${nowTag()}`));
const LEGACY = process.env.LEGACY === '1';
const CASES = (process.env.CASES || (LEGACY ? 'preset' : 'default,preset,upload,none')).split(',');
const devices = pickDevices(process.env.DEVICES || 'android-360,iphone-14,iphone-pro-max');
const browsers = pickBrowsers(process.env.BROWSERS);
const creds = loadCredentials();
const PRESET_DIR = path.join(path.dirname(new URL(import.meta.url).pathname), '../components/groupstudy/presets');
const sha = (buf) => crypto.createHash('sha256').update(buf).digest('hex');
const PRESET_SHA = Object.fromEntries(['notes', 'writing', 'team'].map((id) => [id, sha(fs.readFileSync(path.join(PRESET_DIR, `cover-${id}.jpg`)))]));

// 사용자 업로드용 PNG(64×48 단색, 외부 의존 없이 zlib 로 인코딩)
const UPLOAD_PATH = path.join(OUT, 'e2e-user-upload.png');
if (!fs.existsSync(UPLOAD_PATH)) {
  const W = 64; const H = 48;
  const chunk = (type, data) => {
    const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
    const td = Buffer.concat([Buffer.from(type, 'latin1'), data]);
    const crc = Buffer.alloc(4); crc.writeUInt32BE(zlib.crc32(td) >>> 0);
    return Buffer.concat([len, td, crc]);
  };
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4); ihdr[8] = 8; ihdr[9] = 2;
  const raw = Buffer.alloc((W * 3 + 1) * H);
  for (let y = 0; y < H; y += 1) for (let x = 0; x < W; x += 1) raw.set([230, 80 + x, 40 + y], y * (W * 3 + 1) + 1 + x * 3);
  fs.writeFileSync(UPLOAD_PATH, Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]));
}
const UPLOAD_SHA = sha(fs.readFileSync(UPLOAD_PATH));

const results = [];
let failCount = 0;
const record = (ctx, name, ok, detail = '') => {
  results.push({ ...ctx, check: name, ok, detail });
  if (ok === false) failCount += 1;
  console.log(`${ok === null ? 'SKIP' : ok ? 'PASS' : 'FAIL'} [${ctx.browser}/${ctx.device}/${ctx.kase}] ${name}${detail ? ` — ${detail}` : ''}`);
};

async function fetchBytes(url) {
  const res = await fetch(url);
  return { status: res.status, type: res.headers.get('content-type'), buf: Buffer.from(await res.arrayBuffer()) };
}

async function runCase(page, ctx) {
  const { kase } = ctx;
  const title = `COVER-E2E ${kase} ${ctx.browser}-${ctx.device} ${Date.now()}`;
  const shot = (n) => page.screenshot({ path: path.join(OUT, `${ctx.browser}_${ctx.device}_${kase}_${n}.png`) }).catch(() => {});
  let groupId = null;
  try {
    await page.goto(`${BASE}/groupstudy`, { waitUntil: 'load', timeout: 45000 });
    await page.locator('.gs-create-btn').first().click();
    await page.locator('input[placeholder="스터디 이름을 입력하세요"]').fill(title);
    await page.locator('textarea[placeholder="스터디 규칙, 공지 사항 등을 입력해주세요"]').fill('대표 이미지 E2E 임시 그룹(자동 삭제)');

    let expectPart; // { filename?, sha?, none? }
    if (LEGACY) {
      await page.getByText('편집', { exact: true }).click();
      await page.locator('div[style*="photo-1434030216411"]').first().click();
      await shot('1_modal');
      await page.getByText('완료', { exact: true }).click();
      expectPart = { legacy: true };
    } else {
      const preview = page.locator('[data-testid=create-cover-preview]');
      const initialSrc = await preview.locator('img').getAttribute('src').catch(() => null);
      record(ctx, '초기 미리보기 = 기본 이미지(notes)', /cover-notes/.test(initialSrc || '') && (await preview.getAttribute('data-cover-mode')) === 'preset', initialSrc || 'no img');
      if (kase !== 'default') {
        await page.getByText('편집', { exact: true }).click();
        const modalPreview = page.locator('[data-testid=cover-modal-preview]');
        if (kase === 'preset') {
          // stale 검증: 먼저 파일을 올린 뒤 프리셋으로 바꾼다 → 업로드 파일이 전송되면 안 된다
          await page.setInputFiles('#create-study-image', UPLOAD_PATH);
          await page.waitForTimeout(300);
          record(ctx, '업로드 직후 미리보기 = blob:', /^blob:/.test((await modalPreview.locator('img').getAttribute('src')) || ''));
          await page.locator('[data-testid=cover-option-team]').click();
          const src = await modalPreview.locator('img').getAttribute('src');
          record(ctx, '프리셋 선택 → 미리보기 cover-team', /cover-team/.test(src || ''), src);
          record(ctx, '프리셋 radio aria-checked', (await page.locator('[data-testid=cover-option-team]').getAttribute('aria-checked')) === 'true');
          expectPart = { filename: 'group-cover-team.jpg', sha: PRESET_SHA.team };
        } else if (kase === 'upload') {
          await page.locator('[data-testid=cover-option-writing]').click();
          await page.setInputFiles('#create-study-image', UPLOAD_PATH);
          await page.waitForTimeout(300);
          record(ctx, '업로드 → 미리보기 blob:, 프리셋 선택 해제', /^blob:/.test((await modalPreview.locator('img').getAttribute('src')) || '')
            && (await page.locator('[data-testid=cover-option-writing]').getAttribute('aria-checked')) === 'false');
          expectPart = { filename: path.basename(UPLOAD_PATH), sha: UPLOAD_SHA };
        } else if (kase === 'none') {
          await page.setInputFiles('#create-study-image', UPLOAD_PATH);
          await page.waitForTimeout(300);
          await page.locator('[data-testid=cover-option-none]').click();
          record(ctx, '이미지 없음 → 미리보기 기본 아이콘(img 없음)', (await modalPreview.locator('img').count()) === 0
            && (await modalPreview.locator('[role=img]').count()) === 1);
          expectPart = { none: true };
        }
        await shot('1_modal');
        await page.getByText('완료', { exact: true }).click();
      } else {
        expectPart = { filename: 'group-cover-notes.jpg', sha: PRESET_SHA.notes };
      }
    }
    await shot('2_form');

    await page.evaluate(() => { window.__fdLog = []; });
    const reqPromise = page.waitForRequest((r) => r.method() === 'POST' && /\/api\/groups$/.test(new URL(r.url()).pathname), { timeout: 20000 });
    const resPromise = page.waitForResponse((r) => r.request().method() === 'POST' && /\/api\/groups$/.test(new URL(r.url()).pathname), { timeout: 30000 });
    await page.getByRole('button', { name: /스터디 만들기/ }).last().click();
    const req = await reqPromise;
    const body = (req.postDataBuffer() || Buffer.alloc(0)).toString('latin1');
    // multipart 본문은 파일이 있으면 엔진이 postData 를 노출하지 않는다 → FormData.append 계측(initScript)으로 판정
    const fdImage = (await page.evaluate(() => window.__fdLog || [])).filter((e) => e.k === 'image');
    const hasImagePart = fdImage.length > 0 || /name="image"/.test(body);
    const res = await resPromise;
    const json = await res.json().catch(() => ({}));
    groupId = json.id || null;
    record(ctx, 'POST /api/groups 2xx', res.status() >= 200 && res.status() < 300, `status=${res.status()} id=${groupId}`);

    if (expectPart.legacy) {
      record(ctx, '[LEGACY 재현] 프리셋 선택했는데 image 파트 없음', !hasImagePart, `bodyLen=${body.length}`);
      record(ctx, '[LEGACY 재현] 응답 coverImageUrl=null', !json.coverImageUrl);
    } else if (expectPart.none) {
      record(ctx, '요청에 image 파트 없음(업로드 후 없음 선택해도 stale 파일 미전송)', !hasImagePart, `bodyLen=${body.length} fd=${JSON.stringify(fdImage)}`);
      record(ctx, '응답 coverImageUrl=null', !json.coverImageUrl);
    } else {
      const part = fdImage[0] || null;
      const fnOk = fdImage.length === 1 && part.name === expectPart.filename;
      record(ctx, `요청 image 파트 = ${expectPart.filename} 1개`, fnOk, JSON.stringify(fdImage));
      record(ctx, '응답 coverImageUrl 존재(S3 presigned)', /^https:\/\/[^/]+amazonaws\.com\/(.+\/)?study-images\//.test(json.coverImageUrl || ''), (json.coverImageUrl || '').split('?')[0]);
      if (json.coverImageUrl) {
        const got = await fetchBytes(json.coverImageUrl);
        record(ctx, 'S3 저장본 sha256 = 선택한 원본', got.status === 200 && sha(got.buf) === expectPart.sha, `status=${got.status} type=${got.type} bytes=${got.buf.length}`);
      }
    }

    // 성공 알림 → 목록
    await page.getByRole('button', { name: '확인' }).last().click({ timeout: 10000 });
    await page.waitForTimeout(1500);
    const card = page.locator('.glass-panel', { has: page.locator('h3', { hasText: title }) }).first();
    await card.scrollIntoViewIfNeeded({ timeout: 10000 });
    const wantImage = !expectPart.none && !expectPart.legacy;
    const cardImg = card.locator(`img[alt="${title}"]`);
    const cardIcon = card.locator(`[role=img][aria-label="${title}"]`);
    if (wantImage) {
      const src = await cardImg.getAttribute('src', { timeout: 5000 }).catch(() => null);
      record(ctx, '목록 카드 = 이미지(S3)', !!src && /study-images\//.test(src), (src || 'none').split('?')[0]);
      const loaded = await page.waitForFunction((el) => el && el.complete && el.naturalWidth > 0, await cardImg.elementHandle(), { timeout: 15000 }).then(() => true).catch(() => false);
      record(ctx, '목록 카드 이미지 실제 로드', loaded);
      await shot('3_card');
    } else {
      await shot('3_card');
      record(ctx, '목록 카드 = 기본 아이콘', (await cardIcon.count()) === 1 && (await cardImg.count()) === 0);
    }

    // 상세 모달
    await card.click();
    await page.waitForTimeout(800);
    await shot('4_detail');
    const detailImg = page.locator('img[alt="Background"]');
    const detailIcon = page.locator('[role=img][aria-label="Background"]');
    if (wantImage) {
      const src = await detailImg.getAttribute('src', { timeout: 5000 }).catch(() => null);
      record(ctx, '상세 모달 = 같은 S3 이미지', !!src && /study-images\//.test(src) && src.split('?')[0] === (json.coverImageUrl || '').split('?')[0], (src || 'none').split('?')[0]);
    } else {
      record(ctx, '상세 모달 = 기본 아이콘', (await detailIcon.count()) >= 1 && (await detailImg.count()) === 0);
    }

    // 수정 모달(방장)
    if (!LEGACY) {
      await page.getByRole('button', { name: '스터디 설정 수정' }).click({ timeout: 5000 });
      const modal = page.locator('[data-testid=group-edit-modal]');
      await modal.waitFor({ timeout: 5000 });
      await shot('5_edit');
      const editImg = modal.locator('.gs-profile-avatar img');
      if (wantImage) {
        const src = await editImg.getAttribute('src', { timeout: 5000 }).catch(() => null);
        record(ctx, '수정 모달 = 같은 S3 이미지', !!src && src.split('?')[0] === (json.coverImageUrl || '').split('?')[0]);
      } else {
        record(ctx, '수정 모달 = 기본 아이콘', (await editImg.count()) === 0);
      }
      await modal.getByRole('button', { name: '취소' }).click();
    }
  } catch (e) {
    record(ctx, 'case 실행', false, String(e.message).split('\n')[0].slice(0, 200));
    await shot('9_error');
  } finally {
    if (groupId) {
      const st = await page.evaluate(async (id) => (await fetch(`/api/groups/${id}`, { method: 'DELETE', headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } })).status, groupId).catch((e) => String(e));
      record(ctx, `정리 DELETE /api/groups/${groupId}`, Number(st) >= 200 && Number(st) < 300, `status=${st}`);
    }
  }
}

for (const b of browsers) {
  const browser = await b.type.launch();
  for (const dev of devices) {
    const context = await newMobileContext(browser, dev);
    await context.addInitScript(() => {
      const orig = FormData.prototype.append;
      window.__fdLog = [];
      FormData.prototype.append = function append(k, v, ...rest) {
        try { if (typeof Blob !== 'undefined' && v instanceof Blob) window.__fdLog.push({ k, name: v.name, type: v.type, size: v.size }); } catch { /* 계측 실패는 무시 */ }
        return orig.call(this, k, v, ...rest);
      };
    });
    const page = await context.newPage();
    const errs = [];
    page.on('pageerror', (e) => errs.push(String(e.message)));
    await login(page, BASE, creds);
    for (const kase of CASES) {
      await runCase(page, { browser: b.name, device: dev.name, kase });
    }
    record({ browser: b.name, device: dev.name, kase: '-' }, 'pageerror 없음', errs.length === 0, errs.slice(0, 2).join(' | '));
    await context.close();
  }
  await browser.close();
}

fs.writeFileSync(path.join(OUT, 'results.json'), JSON.stringify(results, null, 2));
const nulls = results.filter((r) => r.ok === null).length;
console.log(`\nGROUPCOVER E2E checks=${results.length} fail=${failCount} skipped(null)=${nulls} base=${BASE} out=${OUT}`);
process.exit(failCount ? 1 : 0);
