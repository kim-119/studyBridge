// SEO 회귀 스모크(의존성 0, node 단독). 번들에 포함되지 않는다.
//
//  정적 검사(빌드 산출물):  node src/__tests__/seo/seo.smoke.mjs --dist <dist 디렉토리>
//  HTTP 검사(운영):          node src/__tests__/seo/seo.smoke.mjs --http
//  HTTP 검사(로컬 nginx):    node src/__tests__/seo/seo.smoke.mjs --http --connect 127.0.0.1:18089 --insecure-http
//    --connect 를 주면 TCP 는 그 주소로, Host 헤더는 실제 호스트명으로 보낸다(로컬 nginx 에서 운영 설정을 그대로 검증).
//
//  계약: frontend/index.html · public/robots.txt · public/sitemap.xml · ops/nginx/studybridge-seo.conf
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import https from 'node:https';

const APEX = 'studybridge.co.kr';
const M = 'm.studybridge.co.kr';
const PUBLIC_PATHS = ['/', '/app', '/login', '/register'];
const UA = {
  desktop: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36',
  iphone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1',
  android: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36',
  webview: 'Mozilla/5.0 (Linux; Android 14; Pixel 8; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/126.0 Mobile Safari/537.36',
  // 크롤러 UA 문자열 — HTTP 동작 테스트용일 뿐, 실제 크롤러 접근/색인 검증이 아니다.
  googlebotSmartphone: 'Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
  googlebotDesktop: 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
  bingbot: 'Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)',
  yeti: 'Mozilla/5.0 (compatible; Yeti/1.1; +https://naver.me/spd)',
};
const HTML_ACCEPT = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8';

const args = process.argv.slice(2);
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : undefined; };
let pass = 0; let fail = 0;
const check = (name, ok, detail = '') => {
  if (ok) { pass++; console.log(`PASS ${name}`); } else { fail++; console.log(`FAIL ${name}${detail ? ` — ${detail}` : ''}`); }
};

// ───────────── 정적 검사 ─────────────
function canonicalOf(html) {
  const m = html.match(/<link rel="canonical" href="([^"]+)"/g) || [];
  return m.map((t) => t.match(/href="([^"]+)"/)[1]);
}

function checkIndexHtml(html, label) {
  check(`${label} html lang=ko`, /<html lang="ko">/.test(html));
  const title = (html.match(/<title>([^<]*)<\/title>/) || [])[1] || '';
  check(`${label} 한국어 title`, title.includes('스터디브릿지') && title.includes('StudyBridge'), title);
  check(`${label} title 1개`, (html.match(/<title>/g) || []).length === 1);
  const desc = (html.match(/<meta name="description" content="([^"]+)"/) || [])[1] || '';
  check(`${label} meta description`, desc.length >= 40 && desc.includes('스터디브릿지'), desc);
  const naver = html.match(/<meta name="naver-site-verification" content="([^"]*)"/g) || [];
  check(`${label} 네이버 소유확인 태그 1개`, naver.length === 1
    && naver[0].includes('content="9b5325517c9f2885f9bb29533ff15f0f26b66b86"'), `count=${naver.length}`);
  check(`${label} 구글 TXT 값 HTML 미포함`, !html.includes('google-site-verification='));
  check(`${label} noindex meta 없음`, !/<meta[^>]+name="robots"[^>]+noindex/i.test(html));
  for (const p of ['og:title', 'og:description', 'og:site_name', 'og:url', 'og:type']) {
    check(`${label} ${p}`, new RegExp(`<meta property="${p}" content="[^"]+"`).test(html));
  }
  const ld = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)];
  check(`${label} JSON-LD 1개`, ld.length === 1, `count=${ld.length}`);
  try {
    const j = JSON.parse(ld[0][1]);
    check(`${label} JSON-LD WebSite`, j['@context'] === 'https://schema.org' && j['@type'] === 'WebSite');
    check(`${label} JSON-LD name/alternateName`, j.name === '스터디브릿지'
      && ['StudyBridge', 'Study Bridge', '스터디 브릿지'].every((n) => (j.alternateName || []).includes(n)));
    check(`${label} JSON-LD url`, j.url === `https://${APEX}/`);
  } catch (e) {
    check(`${label} JSON-LD 파싱`, false, e.message);
  }
  check(`${label} JS 없이 읽히는 본문(h1)`, /<div id="root">[\s\S]*<h1[^>]*>[^<]*스터디브릿지/.test(html));
}

function checkRobots(txt, label) {
  check(`${label} robots User-agent`, /^User-agent:\s*\*/m.test(txt));
  check(`${label} robots 전체 차단 없음`, !/^Disallow:\s*\/\s*$/m.test(txt));
  check(`${label} robots Sitemap 절대 URL`, new RegExp(`^Sitemap: https://${APEX.replace(/\./g, '\\.')}/sitemap\\.xml$`, 'm').test(txt));
}

function checkSitemap(xml, label) {
  check(`${label} sitemap XML 선언`, xml.startsWith('<?xml version="1.0" encoding="UTF-8"?>'));
  check(`${label} sitemap urlset ns`, /<urlset xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9">/.test(xml));
  const body = xml.replace(/<!--[\s\S]*?-->/g, '');
  const opens = (body.match(/<url>/g) || []).length;
  check(`${label} sitemap <url> 짝`, opens > 0 && opens === (body.match(/<\/url>/g) || []).length);
  const locs = [...body.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
  check(`${label} sitemap 공개 경로 일치`, JSON.stringify(locs) === JSON.stringify(PUBLIC_PATHS.map((p) => `https://${APEX}${p}`)), locs.join(' '));
  check(`${label} sitemap 모바일 URL 미포함`, !locs.some((l) => l.includes(`//${M}`)));
}

// ───────────── HTTP 검사 ─────────────
const connect = opt('--connect');
const plain = args.includes('--insecure-http');
function get(host, p, headers = {}) {
  return new Promise((resolve, reject) => {
    const [chost, cport] = connect ? connect.split(':') : [host, plain ? 80 : 443];
    const lib = plain ? http : https;
    const req = lib.request({
      host: chost, port: Number(cport), path: p, method: 'GET', servername: host,
      headers: { Host: host, 'Accept-Encoding': 'identity', ...headers },
    }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (c) => { body += c; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, body }));
    });
    req.on('error', reject);
    req.setTimeout(15000, () => req.destroy(new Error('timeout')));
    req.end();
  });
}
const doc = (ua) => ({ 'User-Agent': ua, Accept: HTML_ACCEPT });

async function runHttp() {
  for (const p of PUBLIC_PATHS) {
    const r = await get(APEX, p, doc(UA.desktop));
    check(`apex ${p} 200`, r.status === 200, `status=${r.status}`);
    check(`apex ${p} X-Robots-Tag 없음`, !r.headers['x-robots-tag'], r.headers['x-robots-tag']);
    check(`apex ${p} canonical=자기 자신`, JSON.stringify(canonicalOf(r.body)) === JSON.stringify([`https://${APEX}${p}`]), canonicalOf(r.body).join(' '));
    check(`apex ${p} 모바일 alternate`, r.body.includes(`<link rel="alternate" media="only screen and (max-width: 640px)" href="https://${M}${p}" />`));
    if (p === '/') checkIndexHtml(r.body, 'apex /');

    const mr = await get(M, p, doc(UA.iphone));
    check(`m ${p} 200(리다이렉트 없음)`, mr.status === 200, `status=${mr.status} loc=${mr.headers.location || ''}`);
    check(`m ${p} canonical=apex 같은 경로`, JSON.stringify(canonicalOf(mr.body)) === JSON.stringify([`https://${APEX}${p}`]), canonicalOf(mr.body).join(' '));
    check(`m ${p} alternate 없음`, !mr.body.includes('rel="alternate"'));
    check(`m ${p} X-Robots-Tag 없음`, !mr.headers['x-robots-tag']);
    if (p === '/') checkIndexHtml(mr.body, 'm /');
  }

  const q = await get(APEX, '/?utm_source=x', doc(UA.desktop));
  check('apex /?query canonical=/ (쿼리 제거)', JSON.stringify(canonicalOf(q.body)) === JSON.stringify([`https://${APEX}/`]));

  for (const p of ['/planner', '/studymate', '/archive/pdf/1', '/no-such-page', '/index.html', '/forgot-password']) {
    for (const host of [APEX, M]) {
      const r = await get(host, p, doc(UA.desktop));
      check(`${host} ${p} noindex`, r.status === 200 && /noindex/.test(r.headers['x-robots-tag'] || ''), `status=${r.status} xrt=${r.headers['x-robots-tag']}`);
      check(`${host} ${p} canonical 없음`, canonicalOf(r.body).length === 0);
    }
  }

  // 주입 방지: 원시 경로가 HTML 에 반사되지 않는다.
  const inj = await get(APEX, '/%22%3E%3Cscript%3Ex%3C/script%3E', doc(UA.desktop));
  check('경로 반사 주입 없음', !inj.body.includes('<script>x') && canonicalOf(inj.body).length === 0);

  for (const host of [APEX, M]) {
    for (const [name, ua] of Object.entries(UA)) {
      const r = await get(host, '/robots.txt', { 'User-Agent': ua, Accept: HTML_ACCEPT });
      check(`${host} robots.txt 200 text/plain (${name})`, r.status === 200 && /^text\/plain/.test(r.headers['content-type'] || ''), `status=${r.status} ct=${r.headers['content-type']} loc=${r.headers.location || ''}`);
      if (name === 'desktop') checkRobots(r.body, `${host}`);
    }
    const s = await get(host, '/sitemap.xml', doc(UA.android));
    check(`${host} sitemap.xml 200 xml`, s.status === 200 && /xml/.test(s.headers['content-type'] || ''), `status=${s.status} ct=${s.headers['content-type']}`);
    if (s.status === 200) checkSitemap(s.body, host);
  }

  // 모바일 리다이렉트 계약(기존 동작 보존) + 루프 없음
  const redir = async (label, host, p, headers, expect) => {
    const r = await get(host, p, headers);
    const loc = r.headers.location || '';
    const ok = expect === 200 ? r.status === 200 : (r.status === 302 && loc === `https://${M}${p}`);
    check(label, ok, `status=${r.status} loc=${loc}`);
  };
  await redir('데스크톱 apex 200', APEX, '/', doc(UA.desktop), 200);
  await redir('iPhone apex → m. 302', APEX, '/login?next=1', doc(UA.iphone), 302);
  await redir('Android Chrome apex → m. 302', APEX, '/', { ...doc(UA.android), 'Sec-Fetch-Dest': 'document' }, 302);
  await redir('Android WebView(앱) apex 200 유지', APEX, '/', doc(UA.webview), 200);
  await redir('iPhone m. 200(루프 없음)', M, '/', doc(UA.iphone), 200);
  await redir('Googlebot Smartphone UA apex → m. 302(사용자와 동일)', APEX, '/', doc(UA.googlebotSmartphone), 302);
  await redir('Googlebot desktop UA apex 200', APEX, '/', doc(UA.googlebotDesktop), 200);
  await redir('bingbot UA apex 200', APEX, '/', doc(UA.bingbot), 200);
  await redir('Yeti UA apex 200', APEX, '/', doc(UA.yeti), 200);
  const api = await get(APEX, '/api/banners/main', { 'User-Agent': UA.iphone, Accept: 'application/json' });
  check('모바일 UA /api JSON 리다이렉트 없음', api.status !== 302 && !/noindex/.test(api.headers['x-robots-tag'] || ''), `status=${api.status}`);
}

if (opt('--dist')) {
  const d = opt('--dist');
  checkIndexHtml(fs.readFileSync(path.join(d, 'index.html'), 'utf8'), 'dist index.html');
  check('dist index.html seo 자리표시자 1개', (fs.readFileSync(path.join(d, 'index.html'), 'utf8').match(/<!--sb:seo-links-->/g) || []).length === 1);
  checkRobots(fs.readFileSync(path.join(d, 'robots.txt'), 'utf8'), 'dist');
  checkSitemap(fs.readFileSync(path.join(d, 'sitemap.xml'), 'utf8'), 'dist');
}
if (args.includes('--http')) await runHttp();
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
