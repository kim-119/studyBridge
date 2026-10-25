// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import { VIDEO_PLAYBACK, VIDEO_STALL_MS, currentVideoTrack, evaluateVideoPlayback } from '../videoPlayback.js';

const track = (o = {}) => ({ kind: 'video', readyState: 'live', muted: false, ...o });
const stream = (t) => ({ getVideoTracks: () => (t ? [t] : []) });
// 재생 중인 <video> 모사(readyState 4 = HAVE_ENOUGH_DATA)
const video = (o = {}, t = track()) => ({ readyState: 4, paused: false, ended: false, videoWidth: 640, videoHeight: 480, srcObject: stream(t), ...o });

test('실제로 프레임을 그리는 요소는 PLAYING — React 상태나 이벤트 수신 여부와 무관', () => {
  assert.equal(evaluateVideoPlayback(video()), VIDEO_PLAYBACK.PLAYING);
  // 스트림 참조가 바뀌어도 같은 요소가 계속 재생 중이면 그대로 PLAYING(초기화로 '연결 중'에 되돌아가지 않음)
  assert.equal(evaluateVideoPlayback(video({}, track({ id: 'same-track' }))), VIDEO_PLAYBACK.PLAYING);
});

test('아직 프레임이 없거나 멈춘 요소는 WAITING', () => {
  assert.equal(evaluateVideoPlayback(null), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(video({ srcObject: null })), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(video({ srcObject: stream(null) })), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(video({ readyState: 1 })), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(video({ videoWidth: 0 })), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(video({ paused: true })), VIDEO_PLAYBACK.WAITING);
});

test('실제 장애: 트랙 종료 = ENDED, 트랙 mute(프레임 공급 중단) = STALLED', () => {
  assert.equal(evaluateVideoPlayback(video({}, track({ readyState: 'ended' }))), VIDEO_PLAYBACK.ENDED);
  assert.equal(evaluateVideoPlayback(video({ readyState: 0 }, track({ readyState: 'ended' }))), VIDEO_PLAYBACK.ENDED);
  assert.equal(evaluateVideoPlayback(video({}, track({ muted: true }))), VIDEO_PLAYBACK.STALLED);
});

test('requestVideoFrameCallback 로 본 마지막 프레임이 오래되면 STALLED, 탭이 숨겨져 있으면(프레임 콜백 정지) 판정 보류', () => {
  const v = video();
  assert.equal(evaluateVideoPlayback(v, { lastFrameAt: 1000, now: 1000 + VIDEO_STALL_MS - 1 }), VIDEO_PLAYBACK.PLAYING);
  assert.equal(evaluateVideoPlayback(v, { lastFrameAt: 1000, now: 1000 + VIDEO_STALL_MS + 1 }), VIDEO_PLAYBACK.STALLED);
  assert.equal(evaluateVideoPlayback(v, { lastFrameAt: 1000, now: 1000 + VIDEO_STALL_MS + 1, hidden: true }), VIDEO_PLAYBACK.PLAYING);
  // 프레임 콜백 미지원(또는 첫 프레임 전) = 요소 상태로만 판정
  assert.equal(evaluateVideoPlayback(v, { lastFrameAt: null, now: 999999 }), VIDEO_PLAYBACK.PLAYING);
});

test('currentVideoTrack: srcObject 의 첫 영상 트랙, 없거나 예외면 null', () => {
  const t = track();
  assert.equal(currentVideoTrack(video({}, t)), t);
  assert.equal(currentVideoTrack({ srcObject: null }), null);
  assert.equal(currentVideoTrack({ srcObject: { getVideoTracks: () => { throw new Error('x'); } } }), null);
  assert.equal(currentVideoTrack(null), null);
});
