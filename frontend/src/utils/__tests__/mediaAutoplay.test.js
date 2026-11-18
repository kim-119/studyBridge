// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  PLAYBACK_RESULT, forgetPlayback, isPlaybackBlocked, requestPlayback, retryBlockedPlayback, subscribePlaybackBlocked,
} from '../mediaAutoplay.js';
import { VIDEO_PLAYBACK, evaluateVideoPlayback } from '../videoPlayback.js';

const domError = (name) => Object.assign(new Error(name), { name });
// play() 동작을 바꿀 수 있는 <video> 모사. policy: 'allow' | 'block' | 'abort' | 'throw'
const media = (policy = 'block') => {
  const el = { srcObject: {}, paused: true, ended: false, calls: 0, policy };
  el.play = () => {
    el.calls += 1;
    if (el.policy === 'throw') throw domError('NotAllowedError');
    if (el.policy === 'allow') { el.paused = false; return Promise.resolve(); }
    return Promise.reject(domError(el.policy === 'abort' ? 'AbortError' : 'NotAllowedError'));
  };
  return el;
};

test('자동재생 차단(NotAllowedError)을 감지해 막힌 요소로 기록하고 구독자에게 알린다', async () => {
  const el = media('block');
  let notified = 0;
  const off = subscribePlaybackBlocked(() => { notified += 1; });
  assert.equal(await requestPlayback(el), PLAYBACK_RESULT.BLOCKED);
  assert.equal(isPlaybackBlocked(el), true);
  assert.equal(notified, 1);
  // 다시 막혀도 중복 알림 없음
  assert.equal(await requestPlayback(el), PLAYBACK_RESULT.BLOCKED);
  assert.equal(notified, 1);
  off();
  forgetPlayback(el);
});

test('사용자 재시도: 막힌 요소를 모두 같은 클릭 안에서(동기) 다시 재생하고, 재생되면 기록 해제', async () => {
  const a = media('block');
  const b = media('block');
  await requestPlayback(a);
  await requestPlayback(b);
  a.policy = 'allow';
  b.policy = 'allow';
  const before = [a.calls, b.calls];
  const pending = retryBlockedPlayback();
  // await 전에 이미 play() 가 불렸다 = 클릭 핸들러의 사용자 활성화 안에서 호출됨
  assert.deepEqual([a.calls, b.calls], [before[0] + 1, before[1] + 1]);
  assert.deepEqual(await pending, [PLAYBACK_RESULT.PLAYING, PLAYBACK_RESULT.PLAYING]);
  assert.equal(isPlaybackBlocked(a), false);
  assert.equal(isPlaybackBlocked(b), false);
  assert.equal(a.paused, false);
});

test('자동재생 차단이 아닌 거부(AbortError)·동기 예외·srcObject 없음', async () => {
  const aborted = media('abort');
  assert.equal(await requestPlayback(aborted), PLAYBACK_RESULT.FAILED);
  assert.equal(isPlaybackBlocked(aborted), false); // 다음 미디어 이벤트에서 다시 시도
  const thrower = media('throw');
  assert.equal(await requestPlayback(thrower), PLAYBACK_RESULT.BLOCKED); // 구형 브라우저: play() 가 Promise 대신 예외
  forgetPlayback(thrower);
  assert.equal(isPlaybackBlocked(thrower), false);
  const empty = media('allow');
  empty.srcObject = null;
  assert.equal(await requestPlayback(empty), PLAYBACK_RESULT.SKIPPED);
  assert.equal(empty.calls, 0);
});

test('판정: 막혀서 멈춘 요소는 BLOCKED(연결 중과 구분), 실제로 재생 중이면 PLAYING', () => {
  const t = { kind: 'video', readyState: 'live', muted: false };
  const el = (o) => ({ readyState: 4, paused: false, ended: false, videoWidth: 640, srcObject: { getVideoTracks: () => [t] }, ...o });
  assert.equal(evaluateVideoPlayback(el({ paused: true }), { blocked: true }), VIDEO_PLAYBACK.BLOCKED);
  assert.equal(evaluateVideoPlayback(el({ paused: true, readyState: 0 }), { blocked: true }), VIDEO_PLAYBACK.BLOCKED);
  assert.equal(evaluateVideoPlayback(el({ paused: true }), { blocked: false }), VIDEO_PLAYBACK.WAITING);
  assert.equal(evaluateVideoPlayback(el({}), { blocked: true }), VIDEO_PLAYBACK.PLAYING);
  // 트랙이 끝났으면 차단 여부와 무관하게 ENDED(연결 끊김 안내가 우선)
  const ended = { ...el({ paused: true }), srcObject: { getVideoTracks: () => [{ ...t, readyState: 'ended' }] } };
  assert.equal(evaluateVideoPlayback(ended, { blocked: true }), VIDEO_PLAYBACK.ENDED);
});

// 화면 연결: 막힌 영상 타일·소리 전용 타일 모두 사용자가 누르는 재생 버튼이 있고, 소리를 끄고 재생하는 우회가 없다.
test('소스 가드: 재생 버튼 → retryBlockedPlayback, 원격 소리를 몰래 음소거하지 않음', () => {
  const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const studyRoom = fs.readFileSync(path.join(src, 'components/StudyRoom.jsx'), 'utf8');
  const sink = fs.readFileSync(path.join(src, 'components/groupstudy/RemoteAudioSink.jsx'), 'utf8');
  const hook = fs.readFileSync(path.join(src, 'hooks/useVideoPlayback.js'), 'utf8');
  // 막힘 오버레이의 버튼 = video-feed-play → retryBlockedPlayback (오버레이 객체가 버튼 testid·핸들러를 정한다)
  assert.match(studyRoom, /playback === VIDEO_PLAYBACK\.BLOCKED \? \{ text: '브라우저가 자동 재생을 막았어요', [^}]*onAction: \(\) => \{ retryBlockedPlayback\(\); \}, actionTestId: 'video-feed-play'/);
  assert.match(studyRoom, /data-testid=\{overlay\.actionTestId\} onClick=\{overlay\.onAction\}/);
  assert.match(sink, /data-testid="remote-audio-play" onClick=\{\(\) => \{ retryBlockedPlayback\(\); \}\}/);
  assert.match(hook, /requestPlayback\(v\)/);
  for (const code of [studyRoom, sink, hook]) assert.doesNotMatch(code, /\.muted = true/);
});
