// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  FULLSCREEN_MODE, HISTORY_MARKER_KEY, NATIVE_EXIT_GRACE_MS, canRequestElementFullscreen, chooseFullscreenMode,
  fullscreenElementOf, hasHistoryMarker, isEmbeddedWebView, isImmediateNativeExit, lockDocumentScroll,
  requestElementFullscreen, withHistoryMarker,
} from '../fullscreenViewer.js';

const UA = {
  pcChrome: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36',
  androidChrome: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Mobile Safari/537.36',
  // 운영 OpenVidu 로그의 Capacitor 앱 접속(SM-S908E, "Android Browser 4.0 (like Chrome 129)") = Android System WebView
  androidWebView: 'Mozilla/5.0 (Linux; Android 14; SM-S908E Build/UP1A.231005.007; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/129.0.6668.70 Mobile Safari/537.36',
  iPhone: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.6.1 Mobile/15E148 Safari/604.1',
};
const el = (o = {}) => ({ requestFullscreen() { return Promise.resolve(); }, ...o });
const doc = (o = {}) => ({ fullscreenEnabled: true, ...o });

test('모드 선택: PC·Android Chrome 은 Fullscreen API, 앱 WebView·Capacitor·iPhone·iframe 차단·API 없음은 CSS 레이어', () => {
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc(), userAgent: UA.pcChrome }), FULLSCREEN_MODE.NATIVE);
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc(), userAgent: UA.androidChrome }), FULLSCREEN_MODE.NATIVE);
  // WebView 는 API 가 있어도 앱이 커스텀 뷰를 즉시 닫으므로 처음부터 CSS
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc(), userAgent: UA.androidWebView }), FULLSCREEN_MODE.CSS);
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc(), userAgent: UA.androidChrome, capacitor: { isNativePlatform: () => true } }), FULLSCREEN_MODE.CSS);
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc(), userAgent: UA.androidChrome, capacitor: { isNativePlatform: () => false } }), FULLSCREEN_MODE.NATIVE);
  // iPhone Safari: 요소 전체화면 메서드 없음
  assert.equal(chooseFullscreenMode({ el: {}, doc: {}, userAgent: UA.iPhone }), FULLSCREEN_MODE.CSS);
  // iPad 등 webkit 접두사만 있는 경우는 API 사용
  assert.equal(chooseFullscreenMode({ el: { webkitRequestFullscreen() {} }, doc: { webkitFullscreenEnabled: true }, userAgent: UA.pcChrome }), FULLSCREEN_MODE.NATIVE);
  // m. PC 폰 프레임(iframe, allow 없음) → fullscreenEnabled=false
  assert.equal(chooseFullscreenMode({ el: el(), doc: doc({ fullscreenEnabled: false }), userAgent: UA.pcChrome }), FULLSCREEN_MODE.CSS);
  assert.equal(canRequestElementFullscreen(null, doc()), false);
  assert.equal(isEmbeddedWebView({ userAgent: UA.androidWebView }), true);
  assert.equal(isEmbeddedWebView({ userAgent: UA.androidChrome }), false);
  assert.equal(isEmbeddedWebView({ userAgent: UA.pcChrome, capacitor: { isNativePlatform: () => { throw new Error('x'); } } }), false);
});

test('진입 직후 해제 판정: 우리가 끄지 않았는데 유예 안에 풀리면 CSS 로 대체, 사용자가 나중에 Esc 로 끈 것은 정상 종료', () => {
  assert.equal(isImmediateNativeExit({ enteredAt: 1000, now: 1000 + 50, exitRequested: false }), true);
  assert.equal(isImmediateNativeExit({ enteredAt: 1000, now: 1000 + NATIVE_EXIT_GRACE_MS + 1, exitRequested: false }), false);
  assert.equal(isImmediateNativeExit({ enteredAt: 1000, now: 1050, exitRequested: true }), false, '우리가 끈 것');
  assert.equal(isImmediateNativeExit({ enteredAt: null, now: 1050, exitRequested: false }), false);
});

test('Fullscreen API 호출: 표준 → webkit 접두사 → 미지원은 거부(호출부가 CSS 로 전환)', async () => {
  let opts = null;
  await requestElementFullscreen({ requestFullscreen(o) { opts = o; return Promise.resolve(); } });
  assert.deepEqual(opts, { navigationUI: 'hide' });
  let wk = 0;
  await requestElementFullscreen({ webkitRequestFullscreen() { wk += 1; } });
  assert.equal(wk, 1);
  await assert.rejects(requestElementFullscreen({}), { name: 'NotSupportedError' });
  await assert.rejects(requestElementFullscreen({ requestFullscreen: () => Promise.reject(Object.assign(new Error('denied'), { name: 'TypeError' })) }), { name: 'TypeError' });
  assert.equal(fullscreenElementOf({ webkitFullscreenElement: 'x' }), 'x');
  assert.equal(fullscreenElementOf(null), null);
});

test('뒤로가기 항목: 라우터 state(idx·key·usr)를 보존하고 표식만 더한다', () => {
  const routerState = { usr: { from: '/groupstudy' }, key: 'abc', idx: 3 };
  const s = withHistoryMarker(routerState, 't1');
  assert.deepEqual(s, { ...routerState, [HISTORY_MARKER_KEY]: 't1' });
  assert.equal(hasHistoryMarker(s, 't1'), true);
  assert.equal(hasHistoryMarker(routerState, 't1'), false);
  assert.equal(hasHistoryMarker(s, 't2'), false);
  assert.deepEqual(withHistoryMarker(null, 't'), { [HISTORY_MARKER_KEY]: 't' });
});

test('스크롤 잠금: 중첩 안전, 마지막 해제에서 원래 값 복원, 해제 중복 호출 무시', () => {
  const d = { documentElement: { style: { overflow: '' } }, body: { style: { overflow: 'auto', overscrollBehavior: '' } } };
  const a = lockDocumentScroll(d);
  const b = lockDocumentScroll(d);
  assert.equal(d.body.style.overflow, 'hidden');
  a();
  a();
  assert.equal(d.body.style.overflow, 'hidden', '아직 다른 잠금이 있음');
  b();
  assert.deepEqual([d.documentElement.style.overflow, d.body.style.overflow, d.body.style.overscrollBehavior], ['', 'auto', '']);
  assert.equal(typeof lockDocumentScroll(null), 'function');
});

test('소스 가드: 화면공유 스테이지는 공통 전체화면 틀을 쓰고, 새 구독·Connection 을 만들지 않으며 모바일에서도 버튼 문구를 보인다', () => {
  const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const stage = fs.readFileSync(path.join(src, 'components/groupstudy/ScreenShareStage.jsx'), 'utf8');
  const frame = fs.readFileSync(path.join(src, 'components/groupstudy/FullscreenViewer.jsx'), 'utf8');
  const hook = fs.readFileSync(path.join(src, 'hooks/useFullscreenViewer.js'), 'utf8');
  const room = fs.readFileSync(path.join(src, 'components/StudyRoom.jsx'), 'utf8');
  assert.match(stage, /useFullscreenViewer\(/);
  assert.match(stage, /<FullscreenFrame viewer=\{viewer\} portalTarget=\{portalTarget\}/);
  assert.match(stage, /\{isFullscreen \? '전체화면 종료' : '전체화면 보기'\}/);
  assert.doesNotMatch(stage, /!isMobile && \(isFullscreen/);
  assert.doesNotMatch(stage, /webkitEnterFullscreen/);
  assert.match(room, /portalTarget=\{roomRootEl\}/);
  for (const code of [stage, frame, hook]) assert.doesNotMatch(code, /\.subscribe\(|initSession\(|getVideoToken|getScreenToken|addVideoElement\(document/);
});
