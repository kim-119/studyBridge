// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildDisplayMediaHints, withDisplayMediaHints, describeCaptureSurface, resolveShareMode, SCREEN_SHARE_MODES } from '../screenShare.js';

test('선택창 힌트: 자기 탭 제외 + 소리 요청 시에만 systemAudio', () => {
  assert.deepEqual(buildDisplayMediaHints({ withAudio: false }), { selfBrowserSurface: 'exclude', surfaceSwitching: 'include', monitorTypeSurfaces: 'include' });
  assert.equal(buildDisplayMediaHints({ withAudio: true }).systemAudio, 'include');
});

test('getDisplayMedia 래핑: OpenVidu 가 넘기는 {video:true,audio} 에 힌트가 더해지고, 끝나면 원래 함수로 복원', async () => {
  const calls = [];
  class MediaDevicesLike { getDisplayMedia(c) { calls.push(c); return Promise.resolve('stream'); } }
  const md = new MediaDevicesLike();
  const proto = MediaDevicesLike.prototype.getDisplayMedia;
  const r = await withDisplayMediaHints(md, buildDisplayMediaHints({ withAudio: true }), () => md.getDisplayMedia({ video: true, audio: true }));
  assert.equal(r, 'stream');
  assert.deepEqual(calls[0], { selfBrowserSurface: 'exclude', surfaceSwitching: 'include', monitorTypeSurfaces: 'include', systemAudio: 'include', video: true, audio: true });
  assert.equal(md.getDisplayMedia, proto); // 인스턴스 속성 제거 → 프로토타입 메서드 복원
  assert.equal(Object.prototype.hasOwnProperty.call(md, 'getDisplayMedia'), false);
});

test('래핑 중 예외(사용자 취소)여도 복원되고 예외는 그대로 전달', async () => {
  const own = () => Promise.reject(new Error('NotAllowedError'));
  const md = { getDisplayMedia: own };
  await assert.rejects(withDisplayMediaHints(md, { selfBrowserSurface: 'exclude' }, () => md.getDisplayMedia({ video: true })), /NotAllowedError/);
  assert.equal(md.getDisplayMedia, own); // 원래 인스턴스 속성으로 복원
});

test('getDisplayMedia 가 없는 브라우저(모바일)는 그대로 실행', async () => {
  assert.equal(await withDisplayMediaHints({}, {}, () => 42), 42);
  assert.equal(await withDisplayMediaHints(undefined, {}, () => 7), 7);
});

test('캡처 표면 안내: 전체 화면만 반복 화면 위험', () => {
  assert.deepEqual(describeCaptureSurface({ displaySurface: 'monitor', width: 1920, height: 1080, frameRate: 30 }), {
    surface: 'monitor', label: '전체 모니터', width: 1920, height: 1080, resolution: '1920×1080', frameRate: 30,
    recursionRisk: true, recursionPossible: true, previewPolicy: 'snapshot',
  });
  const tab = describeCaptureSurface({ displaySurface: 'browser', width: 1440, height: 810 });
  assert.equal(tab.recursionRisk, false);
  assert.equal(tab.previewPolicy, 'live');
  const win = describeCaptureSurface({ displaySurface: 'window' });
  assert.equal(win.label, '창');
  assert.equal(win.recursionPossible, true);
  assert.equal(win.previewPolicy, 'live');
  assert.equal(win.resolution, null);
  assert.equal(describeCaptureSurface(undefined).label, '화면');
});

test('공유 모드: 문서=detail(기본), 영상=motion', () => {
  assert.equal(resolveShareMode('nope'), 'document');
  assert.equal(SCREEN_SHARE_MODES[resolveShareMode('motion')].contentHint, 'motion');
  assert.equal(SCREEN_SHARE_MODES.document.contentHint, 'detail');
});
