// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mergeScreenAiShares, pickDefaultShare, validateQuestion, describeScreenAiError, pendingHint, streamIdOf, formatBytes,
} from '../screenAi.js';
import { fitWithin, encodeWithinBudget, pickRenderedVideo, liveVideoTrack, newClientRequestId, ScreenCaptureError, SCREEN_AI_CAPTURE } from '../screenAiCapture.js';

const sm = (streamId) => ({ stream: { streamId } });
const clientShares = [
  { connectionId: 'con_SA', userId: 1, name: '민지', isMine: false, isOwnUser: false, streamManager: sm('str_SA') },
  { connectionId: 'con_SB', userId: 2, name: '서준', isMine: false, isOwnUser: false, streamManager: sm('str_SB') },
];

test('화면 목록: 서버 이름·동의를 붙이고, 서버 목록에 아직 없는 남의 화면은 분석 불가(확인 중)', () => {
  const merged = mergeScreenAiShares(clientShares, [
    { connectionId: 'con_SA', streamId: 'str_SA', sharerName: '김민지', aiConsent: true, analyzable: true, isMine: false },
  ]);
  assert.equal(merged.length, 2);
  assert.deepEqual(merged.map((s) => s.index), [1, 2]);
  assert.equal(merged[0].name, '김민지');
  assert.equal(merged[0].analyzable, true);
  assert.equal(merged[0].streamId, 'str_SA');
  assert.equal(merged[1].known, false);
  assert.equal(merged[1].analyzable, false);
  assert.equal(merged[1].name, '서준');
});

test('화면 목록: 내 화면은 서버 확인 전에도 분석 가능, 서버 목록을 못 읽어도(null) 목록은 유지', () => {
  const mine = [{ connectionId: 'con_ME', userId: 9, name: '나', isMine: true, isOwnUser: true, streamManager: sm('str_ME') }];
  const merged = mergeScreenAiShares(mine, null);
  assert.equal(merged[0].analyzable, true);
  assert.equal(merged[0].isMine, true);
  assert.equal(mergeScreenAiShares([], null).length, 0);
});

test('기본 선택: 현재 선택 유지 → 스테이지 선택 → 분석 가능한 남의 화면 순', () => {
  const merged = mergeScreenAiShares(clientShares, [
    { connectionId: 'con_SA', analyzable: false, aiConsent: false },
    { connectionId: 'con_SB', analyzable: true, aiConsent: true },
  ]);
  assert.equal(pickDefaultShare(merged, 'con_SA', 'con_SB'), 'con_SA');
  assert.equal(pickDefaultShare(merged, 'con_GONE', 'con_SA'), 'con_SA');
  assert.equal(pickDefaultShare(merged, null, null), 'con_SB');
  assert.equal(pickDefaultShare([], 'con_SA', null), null);
});

test('질문 검증: 빈 질문·1000자 초과(코드 포인트 기준) 거부', () => {
  assert.equal(validateQuestion('   '), '질문을 입력해 주세요.');
  assert.equal(validateQuestion('지금 보이는 화면 요약해 줘.'), null);
  assert.match(validateQuestion('가'.repeat(1001)), /1000자/);
  assert.equal(validateQuestion('😀'.repeat(1000)), null);
});

test('오류 안내: 서버 계약 코드 → 종류/재시도/Retry-After', () => {
  const http = (status, data, headers = {}) => ({ response: { status, data, headers } });
  const consent = describeScreenAiError(http(403, { code: 'SHARER_CONSENT_REQUIRED', message: '공유자가 이 화면의 AI 분석을 허용하지 않았습니다.', retryable: false }));
  assert.equal(consent.kind, 'consent');
  assert.equal(consent.retryable, false);
  const busy = describeScreenAiError(http(429, { code: 'SCREEN_AI_BUSY', message: '지금 AI 화면 분석 요청이 많습니다.', retryable: true, retryAfterSeconds: 5 }));
  assert.equal(busy.kind, 'busy');
  assert.equal(busy.retryAfterSeconds, 5);
  assert.equal(describeScreenAiError(http(504, { code: 'SCREEN_AI_TIMEOUT', message: 'AI 분석 시간이 초과되었습니다.', retryable: true })).kind, 'timeout');
  assert.equal(describeScreenAiError(http(409, { code: 'SCREEN_STREAM_MISMATCH', message: '선택한 화면공유가 다시 시작되었습니다.' })).kind, 'gone');
  // 영어 원문은 노출하지 않는다
  assert.equal(describeScreenAiError(http(500, { message: 'Internal Server Error' })).message, 'AI 화면 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.');
  assert.equal(describeScreenAiError({ code: 'ECONNABORTED', message: 'timeout of 280000ms exceeded' }).kind, 'timeout');
  assert.equal(describeScreenAiError({ code: 'ERR_CANCELED', name: 'CanceledError' }).kind, 'cancelled');
  assert.equal(describeScreenAiError({ message: 'Network Error' }).kind, 'network');
  const cap = describeScreenAiError(new ScreenCaptureError('BLANK_FRAME', 'x'));
  assert.equal(cap.kind, 'capture');
  assert.match(cap.message, /검은 화면/);
});

test('대기 안내: 캡처 → 분석 → 지연 → 혼잡 순', () => {
  assert.match(pendingHint('capturing', 0), /캡처/);
  assert.match(pendingHint('analyzing', 3), /분석하고/);
  assert.match(pendingHint('analyzing', 20), /오래/);
  assert.match(pendingHint('analyzing', 90), /혼잡/);
});

test('캡처 크기: 긴 변 1280 이하로 비율 유지 축소, 확대하지 않음', () => {
  assert.deepEqual(fitWithin(1920, 1080), { width: 1280, height: 720, scale: 1280 / 1920 });
  assert.deepEqual(fitWithin(1080, 2400).height, 1280);
  assert.equal(fitWithin(1080, 2400).width, 576);
  assert.deepEqual(fitWithin(800, 600), { width: 800, height: 600, scale: 1 });
  assert.equal(fitWithin(0, 600).width, 0);
});

test('인코딩 예산: 0.75 → 300KB 초과면 0.6 → 1MB 초과면 축소, 끝내 크면 TOO_LARGE', async () => {
  const calls = [];
  const sizes = (w, q) => (q === 0.75 ? 400 * 1024 : 250 * 1024) * (w / 1280);
  const enc = async (w, h, q) => { calls.push([w, h, q]); return { size: sizes(w, q) }; };
  const out = await encodeWithinBudget(enc, { width: 1280, height: 720 });
  assert.equal(out.quality, 0.6);
  assert.equal(out.width, 1280);
  assert.deepEqual(calls, [[1280, 720, 0.75], [1280, 720, 0.6]]);

  const small = await encodeWithinBudget(async () => ({ size: 80 * 1024 }), { width: 1280, height: 720 });
  assert.equal(small.quality, SCREEN_AI_CAPTURE.quality);

  const shrink = [];
  const big = await encodeWithinBudget(async (w, h, q) => { shrink.push(w); return { size: w >= 1280 ? 2 * 1024 * 1024 : 700 * 1024 }; }, { width: 1280, height: 720 });
  assert.equal(big.width, 960);
  assert.ok(shrink.includes(960));

  await assert.rejects(encodeWithinBudget(async () => ({ size: 5 * 1024 * 1024 }), { width: 1280, height: 720 }), (e) => e.code === 'TOO_LARGE');
});

test('기존 스트림 재사용: 스테이지 video(프레임 있음) 우선, 없으면 살아 있는 트랙', () => {
  const ready = { readyState: 4, videoWidth: 1280, videoHeight: 720, ended: false };
  const empty = { readyState: 0, videoWidth: 0, videoHeight: 0 };
  assert.equal(pickRenderedVideo({ videos: [{ video: empty }, { video: ready }] }), ready);
  assert.equal(pickRenderedVideo({ videos: [{ video: empty }] }), null);
  assert.equal(pickRenderedVideo(null), null);
  const track = { readyState: 'live' };
  assert.equal(liveVideoTrack({ stream: { getMediaStream: () => ({ getVideoTracks: () => [track] }) } }), track);
  assert.equal(liveVideoTrack({ stream: { getMediaStream: () => ({ getVideoTracks: () => [{ readyState: 'ended' }] }) } }), null);
  assert.equal(liveVideoTrack({ stream: { getMediaStream: () => { throw new Error('gone'); } } }), null);
});

test('요청 id 는 서버 패턴 [A-Za-z0-9_-]{8,64} 를 만족하고 매번 다르다', () => {
  const a = newClientRequestId();
  const b = newClientRequestId();
  assert.match(a, /^[A-Za-z0-9_-]{8,64}$/);
  assert.notEqual(a, b);
  assert.equal(streamIdOf(sm('x')), 'x');
  assert.equal(formatBytes(84 * 1024), '84KB');
});
