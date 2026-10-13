# nginx — studybridge.co.kr(데스크톱) + m.studybridge.co.kr(모바일 웹)

운영 EC2 nginx 설정의 원본 사본. 두 호스트는 **같은 정적 릴리즈(`/var/www/studybridge/current`)·같은 Spring(`/api`)·
같은 WebSocket/OpenVidu 프록시**를 쓴다. 모바일 전용 React 코드/번들은 없다(동일 SPA 의 반응형 presentation 계층).

| 파일 | 설치 위치 | 역할 |
|---|---|---|
| `studybridge-mobile-ua.conf` | `/etc/nginx/conf.d/studybridge-mobile-ua.conf` | `$sb_ua_mobile`(휴대전화 UA, WebView 제외) + `$sb_mobile_redirect`(apex·GET·모바일·문서 내비게이션일 때만 1) map |
| `studybridge-site-common.conf` | `/etc/nginx/snippets/studybridge-site-common.conf` | 443 서버 블록 공통부(/api, /ws-group, /openvidu, /assets, index.html, Android 다운로드, SPA 폴백 + 모바일 302) |
| `studybridge-seo.conf` | `/etc/nginx/conf.d/studybridge-seo.conf` | SEO map: 공개 경로 허용목록(`$sb_seo_path`) → 경로별 canonical/모바일 alternate(`$sb_seo_links`, index.html 의 `<!--sb:seo-links-->` 에 sub_filter) + 비공개 SPA 문서 `X-Robots-Tag: noindex` |
| `studybridge-sites.conf` | `/etc/nginx/sites-available/studybridge` | 80/443 서버 블록(default 차단, www→apex 301, apex, m.) |

## 리다이렉트 계약
- 휴대전화 브라우저(Android Chrome / iPhone Safari …)가 `https://studybridge.co.kr/<path>?<qs>` 를 **문서로** 열면
  `302 https://m.studybridge.co.kr/<path>?<qs>` (경로·쿼리 보존, 임시 리다이렉트 → 브라우저 캐시 없음).
- 제외: `/api/`, `/ws-group`, `/openvidu/`, `/assets/`, `/downloads/android/`, `/api/app/`(별도 location) +
  fetch/XHR/SSE/WebSocket(Accept 에 text/html 없음·Sec-Fetch-Dest ≠ document) + GET 외 메서드 + Android WebView(`; wv)`, Capacitor 앱).
- `m.` → apex 리다이렉트는 없다(루프 불가). 데스크톱이 `m.` 을 열어도 그대로 서빙된다.
- 포스터 QR(`https://studybridge.co.kr/`)은 그대로 유효하다.

## 설치/변경 절차(운영)
```bash
TS=$(date +%Y%m%d-%H%M%S)
sudo cp /etc/nginx/sites-available/studybridge /etc/nginx/sites-available/studybridge.bak-$TS
sudo cp ops/nginx/studybridge-mobile-ua.conf   /etc/nginx/conf.d/studybridge-mobile-ua.conf
sudo cp ops/nginx/studybridge-seo.conf         /etc/nginx/conf.d/studybridge-seo.conf
sudo cp ops/nginx/studybridge-site-common.conf /etc/nginx/snippets/studybridge-site-common.conf
sudo cp ops/nginx/studybridge-sites.conf       /etc/nginx/sites-available/studybridge
sudo nginx -t && sudo systemctl reload nginx
cd frontend && node src/__tests__/mobile/redirect.mjs      # 계약 검증(운영)
node src/__tests__/seo/seo.smoke.mjs --http                # SEO 계약 검증(운영)
```

## 인증서
`/etc/letsencrypt/live/www.studybridge.co.kr` 하나에 SAN 3개(apex, www, m.). 갱신은 기존 certbot.timer(nginx authenticator) 그대로.
처음 확장 시: `sudo certbot certonly --nginx --cert-name www.studybridge.co.kr -d studybridge.co.kr -d www.studybridge.co.kr -d m.studybridge.co.kr --expand`

## 롤백
```bash
sudo cp /etc/nginx/sites-available/studybridge.bak-<TS> /etc/nginx/sites-available/studybridge
sudo rm -f /etc/nginx/conf.d/studybridge-mobile-ua.conf /etc/nginx/snippets/studybridge-site-common.conf
sudo nginx -t && sudo systemctl reload nginx
```
(리다이렉트만 끄려면 `conf.d/studybridge-mobile-ua.conf` 의 `$sb_mobile_redirect` map 에서 `1` 을 내는 두 줄을 주석 처리하고 reload.)
인증서는 되돌릴 필요가 없다(SAN 이 늘어난 것뿐, apex/www 는 그대로 유효).

## SEO(검색엔진) 계약
- 공개·색인 허용 경로: `/`, `/app`, `/login`, `/register` (`studybridge-seo.conf` `$sb_seo_path` = `frontend/public/sitemap.xml`).
- apex: `canonical=https://studybridge.co.kr<path>` + `alternate media="only screen and (max-width: 640px)" → https://m.studybridge.co.kr<path>`.
- m.: `canonical=https://studybridge.co.kr<path>` (같은 경로의 apex).
- 그 외 SPA 문서(로그인 필요 화면, 없는 경로의 200 폴백, `/index.html`): `X-Robots-Tag: noindex`, canonical 없음.
- `/robots.txt`, `/sitemap.xml` 은 별도 location(모바일 302 제외). 공개 경로를 추가하면 map·sitemap·`seo.smoke.mjs` PUBLIC_PATHS 를 함께 고친다.
- SEO 만 되돌리기: `sudo rm /etc/nginx/conf.d/studybridge-seo.conf` 만으로는 snippet 이 변수를 참조해 `nginx -t` 가 실패하므로, snippet 도 백업본으로 복원한다.
