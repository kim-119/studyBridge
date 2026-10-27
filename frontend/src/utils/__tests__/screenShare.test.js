// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import { buildDisplayMediaHints, withDisplayMediaHints, describeCaptureSurface, resolveShareMode, SCREEN_SHARE_MODES, lockScreenResolution, findVideoSender, SCREEN_DEGRADATION_PREFERENCE, SCREEN_SHARE_LIMIT, screenShareLimitMessage, screenShareAvailability } from '../screenShare.js';

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

// RTCRtpSender 모사: getParameters 는 매번 새 객체(브라우저와 같음), setParameters 는 받은 값을 저장.
const fakeSender = (degradationPreference, { failSet = false } = {}) => {
  const st = { degradationPreference, sets: 0 };
  return {
    st,
    getParameters: () => ({ encodings: [{ active: true }], ...(st.degradationPreference ? { degradationPreference: st.degradationPreference } : {}) }),
    setParameters: async (p) => { if (failSet) throw new Error('InvalidModificationError'); st.sets++; st.degradationPreference = p.degradationPreference; },
  };
};

test('해상도 고정: 영상 모드에 openvidu 가 넣은 balanced 를 maintain-resolution 으로 덮는다', async () => {
  assert.equal(SCREEN_DEGRADATION_PREFERENCE, 'maintain-resolution');
  const s = fakeSender('balanced');
  assert.deepEqual(await lockScreenResolution(s), { applied: 'maintain-resolution', changed: true });
  assert.equal(s.st.sets, 1);
  // 값이 없을 때(설정 전)도 건다
  const none = fakeSender(undefined);
  assert.deepEqual(await lockScreenResolution(none), { applied: 'maintain-resolution', changed: true });
});

test('해상도 고정: 이미 maintain-resolution 이면 setParameters 를 부르지 않는다(주기 확인이 재협상·부하를 만들지 않음)', async () => {
  const s = fakeSender('maintain-resolution');
  assert.deepEqual(await lockScreenResolution(s), { applied: 'maintain-resolution', changed: false });
  assert.equal(s.st.sets, 0);
});

test('해상도 고정: 송신기 없음·미지원·실패는 예외 없이 applied=null', async () => {
  assert.deepEqual(await lockScreenResolution(null), { applied: null, changed: false });
  assert.deepEqual(await lockScreenResolution({}), { applied: null, changed: false });
  assert.deepEqual(await lockScreenResolution(fakeSender('balanced', { failSet: true })), { applied: null, changed: false });
});

test('findVideoSender: 화면공유 PC 의 영상 송신기만 고른다', () => {
  const v = { track: { kind: 'video' } }, a = { track: { kind: 'audio' } };
  assert.equal(findVideoSender({ getSenders: () => [a, v] }), v);
  assert.equal(findVideoSender({ getSenders: () => [a, { track: null }] }), null);
  assert.equal(findVideoSender(null), null);
  assert.equal(findVideoSender({ getSenders: () => { throw new Error('closed'); } }), null);
});

test('화면공유 슬롯(안내용): 다른 사람 공유만 세고 2개면 가득 참, 서버 limit 우선', () => {
  const scr = (cid, userId) => [cid, { connectionId: cid, userId, kind: 'SCREEN' }];
  assert.equal(SCREEN_SHARE_LIMIT, 2);
  assert.deepEqual(screenShareAvailability([], 7), { used: 0, limit: 2, full: false });
  assert.deepEqual(screenShareAvailability([scr('con_a', 1)], 7), { used: 1, limit: 2, full: false });
  assert.deepEqual(screenShareAvailability([scr('con_a', 1), scr('con_b', 2)], 7), { used: 2, limit: 2, full: true });
  // 내 공유(이 탭·다른 기기)는 세지 않는다 — 사용자당 1개는 서버가 따로 판정
  assert.deepEqual(screenShareAvailability([scr('con_a', 1), scr('con_me', 7)], '7'), { used: 1, limit: 2, full: false });
  // 서버가 알려 준 한도 우선, 이상한 값이면 기본값
  assert.equal(screenShareAvailability([scr('con_a', 1), scr('con_b', 2)], 7, 3).full, false);
  assert.equal(screenShareAvailability([scr('con_a', 1), scr('con_b', 2)], 7, 0).limit, 2);
  assert.equal(screenShareAvailability(undefined, 7).used, 0);
  assert.equal(screenShareLimitMessage(), '현재 화면공유 가능 인원(최대 2명)이 모두 사용 중입니다.');
});
