// m.studybridge.co.kr 라우팅/리다이렉트 계약 검증(HTTP 레벨, Playwright 불필요).
//  실행: node src/__tests__/mobile/redirect.mjs            (운영 https://studybridge.co.kr)
//  env : APEX, MOBILE, RESOLVE(예: 127.0.0.1 — 로컬 nginx 를 직접 때릴 때 Host 헤더만 바꿔 검사)
//  계약:
//   · 데스크톱 UA 문서 요청 apex → 200 (리다이렉트 없음)
//   · Android Chrome / iPhone Safari UA 문서 요청 apex → 302 Location=https://m.<path><query>
//   · Android WebView(Capacitor) UA → 200 (앱은 apex 유지)
//   · /api/, /ws-group, /openvidu/, /assets/, /downloads/android/ 는 모바일 UA 라도 302(m.) 아님
//   · XHR/fetch 스타일(Accept: application/json / text/event-stream, Sec-Fetch-Dest: empty) 은 302 아님
//   · m. 호스트는 어떤 UA 에서도 apex 로 되돌리지 않음(루프 없음), m. 에서 /api 가 동작
import https from 'node:https';

const APEX = process.env.APEX || 'https://studybridge.co.kr';
const MOBILE = process.env.MOBILE || 'https://m.studybridge.co.kr';
const RESOLVE = process.env.RESOLVE || '';
const UA = {
  desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36',
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  iphoneOld: 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1',
  webview: 'Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/UP1A; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/125.0.0.0 Mobile Safari/537.36',
  ipad: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
  curl: 'curl/8.5.0',
};
const DOC = { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Sec-Fetch-Dest': 'document', 'Sec-Fetch-Mode': 'navigate' };
const DOC_NO_SEC = { Accept: 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8' };
const XHR = { Accept: 'application/json, text/plain, */*', 'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors' };
const SSE = { Accept: 'text/event-stream', 'Sec-Fetch-Dest': 'empty' };

function req(url, ua, headers = {}, method = 'GET') {
  const u = new URL(url);
  return new Promise((resolve, reject) => {
    const r = https.request({ host: RESOLVE || u.hostname, servername: u.hostname, port: 443, path: u.pathname + u.search, method, rejectUnauthorized: !RESOLVE, headers: { Host: u.hostname, 'User-Agent': ua, ...headers } }, (res) => {
      let body = ''; res.setEncoding('utf8'); res.on('data', (c) => { if (body.length < 2000) body += c; }); res.on('end', () => resolve({ status: res.statusCode, location: res.headers.location || '', body }));
    });
    r.setTimeout(15000, () => { r.destroy(new Error('timeout')); });
    r.on('error', reject); r.end();
  });
}

const cases = [];
const expect = (name, fn) => cases.push({ name, fn });
const mobileHost = new URL(MOBILE).host;

for (const [k, ua] of Object.entries({ desktop: UA.desktop, ipad: UA.ipad, webview: UA.webview, curl: UA.curl })) {
  expect(`apex / ${k} UA → 200 (no redirect)`, async () => { const r = await req(`${APEX}/`, ua, DOC); return r.status === 200 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
}
for (const [k, ua] of Object.entries({ android: UA.android, iphone: UA.iphone })) {
  expect(`apex / ${k} UA → 302 ${MOBILE}/`, async () => { const r = await req(`${APEX}/`, ua, DOC); return r.status === 302 && r.location === `${MOBILE}/` ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex deep link ${k} → path+query 보존`, async () => { const r = await req(`${APEX}/groupstudy?id=123&tab=chat`, ua, DOC); return r.status === 302 && r.location === `${MOBILE}/groupstudy?id=123&tab=chat` ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /archive/pdf/345 ${k} → 302 보존`, async () => { const r = await req(`${APEX}/archive/pdf/345`, ua, DOC); return r.status === 302 && r.location === `${MOBILE}/archive/pdf/345` ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /api/app/version ${k} XHR → not m. redirect`, async () => { const r = await req(`${APEX}/api/app/version`, ua, XHR); return r.status !== 302 || !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /api/app/version ${k} even with document Accept → not m. redirect`, async () => { const r = await req(`${APEX}/api/app/version`, ua, DOC); return r.status !== 302 || !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /api/users/login ${k} POST → not m. redirect`, async () => { const r = await req(`${APEX}/api/users/login`, ua, { ...XHR, 'Content-Type': 'application/json' }, 'POST'); return r.status !== 302 ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex SSE-style fetch ${k} → not m. redirect`, async () => { const r = await req(`${APEX}/api/app/version`, ua, SSE); return r.status !== 302 || !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /ws-group/info ${k} → not m. redirect`, async () => { const r = await req(`${APEX}/ws-group/info`, ua, XHR); return r.status !== 302 || !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /openvidu/ ${k} → not m. redirect`, async () => { const r = await req(`${APEX}/openvidu/api/config`, ua, DOC); return r.status !== 302 || !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /downloads/android/StudyBridge-latest.apk ${k} → not m. redirect`, async () => { const r = await req(`${APEX}/downloads/android/StudyBridge-latest.apk`, ua, DOC); return !r.location.includes(mobileHost) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex /assets/ ${k} → not m. redirect`, async () => { const r = await req(`${APEX}/assets/nonexistent.js`, ua, { Accept: '*/*', 'Sec-Fetch-Dest': 'script' }); return r.status === 404 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
  expect(`apex root fetch(XHR accept) ${k} → 200 html, no redirect`, async () => { const r = await req(`${APEX}/`, ua, XHR); return r.status === 200 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
  expect(`mobile host / ${k} → 200 (loop 없음)`, async () => { const r = await req(`${MOBILE}/`, ua, DOC); return r.status === 200 && !r.location && /<div id="root">/.test(r.body) ? null : `status=${r.status} loc=${r.location}`; });
  expect(`mobile host /groupstudy ${k} → 200 SPA fallback`, async () => { const r = await req(`${MOBILE}/groupstudy?x=1`, ua, DOC); return r.status === 200 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
  expect(`mobile host /api/app/version ${k} → Spring 응답(200/404 JSON)`, async () => { const r = await req(`${MOBILE}/api/app/version`, ua, XHR); return [200, 404].includes(r.status) && /\{/.test(r.body) ? null : `status=${r.status} body=${r.body.slice(0, 80)}`; });
}
expect('apex / iPhone(Safari 15, Sec-Fetch 없음) → 302 (Accept 폴백)', async () => { const r = await req(`${APEX}/`, UA.iphoneOld, DOC_NO_SEC); return r.status === 302 && r.location === `${MOBILE}/` ? null : `status=${r.status} loc=${r.location}`; });
expect('mobile host / desktop UA → 200 (데스크톱이 m. 을 열어도 되돌리지 않음)', async () => { const r = await req(`${MOBILE}/`, UA.desktop, DOC); return r.status === 200 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
expect('mobile host /index.html iPhone → 200', async () => { const r = await req(`${MOBILE}/index.html`, UA.iphone, DOC); return r.status === 200 && !r.location ? null : `status=${r.status} loc=${r.location}`; });
expect('apex /index.html iPhone → 302 m.', async () => { const r = await req(`${APEX}/index.html`, UA.iphone, DOC); return r.status === 302 && r.location === `${MOBILE}/index.html` ? null : `status=${r.status} loc=${r.location}`; });
expect('apex HEAD iPhone → no redirect (GET 만 대상)', async () => { const r = await req(`${APEX}/`, UA.iphone, DOC, 'HEAD'); return r.status === 200 ? null : `status=${r.status} loc=${r.location}`; });

let pass = 0, fail = 0;
for (const c of cases) {
  let msg;
  try { msg = await c.fn(); } catch (e) { msg = 'ERR ' + e.message; }
  if (msg) { fail++; console.log(`FAIL ${c.name} :: ${msg}`); } else { pass++; console.log(`PASS ${c.name}`); }
}
console.log(`\nREDIRECT RESULT pass=${pass} fail=${fail} apex=${APEX} mobile=${MOBILE}${RESOLVE ? ' resolve=' + RESOLVE : ''}`);
process.exit(fail ? 1 : 0);
