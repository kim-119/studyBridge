// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { PREVIEW_SWITCH_WAIT_MS, isTrackForSelectedCamera, waitForSelectedPreview } from '../cameraSelection.js';

const track = (deviceId, readyState = 'live') => ({ readyState, getSettings: () => ({ deviceId }) });

test('고른 카메라의 살아 있는 트랙만 handoff 대상', () => {
  assert.equal(isTrackForSelectedCamera(track('cam-b'), 'cam-b'), true);
  // 카메라를 B 로 바꿨는데 프리뷰는 아직 A(새 장치를 여는 중) → 넘기지 않는다
  assert.equal(isTrackForSelectedCamera(track('cam-a'), 'cam-b'), false);
  assert.equal(isTrackForSelectedCamera(track('cam-b', 'ended'), 'cam-b'), false);
  assert.equal(isTrackForSelectedCamera(null, 'cam-b'), false);
});

test('기본 카메라(선택 없음)는 살아 있는 트랙이면 된다', () => {
  assert.equal(isTrackForSelectedCamera(track('cam-a'), ''), true);
  assert.equal(isTrackForSelectedCamera(track('cam-a'), undefined), true);
  assert.equal(isTrackForSelectedCamera(track('cam-a', 'ended'), ''), false);
});

test('장치를 알 수 없으면 넘기지 않는다(스터디룸이 고른 카메라로 새로 연다)', () => {
  assert.equal(isTrackForSelectedCamera({ readyState: 'live' }, 'cam-b'), false);
  assert.equal(isTrackForSelectedCamera({ readyState: 'live', getSettings: () => { throw new Error('x'); } }, 'cam-b'), false);
});

// 가짜 시계: sleep 이 실제로 기다리지 않고 시간만 앞으로 민다.
const fakeClock = () => { let t = 0; return { now: () => t, sleep: async (ms) => { t += ms; } }; };

test('카메라 전환 직후 입장: 새 카메라 획득이 끝나면 그 트랙을 돌려준다(이전 카메라를 넘기지 않음)', async () => {
  const clock = fakeClock();
  const oldTrack = track('cam-a'); const newTrack = track('cam-b');
  const got = await waitForSelectedPreview({ getTrack: () => (clock.now() >= 1200 ? newTrack : oldTrack), selectedCamera: 'cam-b', isAcquiring: () => true, ...clock });
  assert.equal(got, newTrack);
  assert.ok(clock.now() >= 1200 && clock.now() < PREVIEW_SWITCH_WAIT_MS);
});

test('이미 고른 카메라면 기다리지 않는다 / 획득이 실패로 끝나거나 시간이 지나면 null(스터디룸이 직접 연다)', async () => {
  const c1 = fakeClock(); const ready = track('cam-b');
  assert.equal(await waitForSelectedPreview({ getTrack: () => ready, selectedCamera: 'cam-b', isAcquiring: () => true, ...c1 }), ready);
  assert.equal(c1.now(), 0);
  const c2 = fakeClock();
  assert.equal(await waitForSelectedPreview({ getTrack: () => track('cam-a'), selectedCamera: 'cam-b', isAcquiring: () => c2.now() < 300, ...c2 }), null);
  assert.ok(c2.now() < 1000);
  const c3 = fakeClock();
  assert.equal(await waitForSelectedPreview({ getTrack: () => track('cam-a'), selectedCamera: 'cam-b', isAcquiring: () => true, ...c3 }), null);
  assert.equal(c3.now(), PREVIEW_SWITCH_WAIT_MS);
});

// 넘기는 쪽(입장 준비)과 받는 쪽(스터디룸) 모두 같은 판정을 거쳐야 이전 카메라 트랙이 송출되지 않는다.
test('소스 가드: 입장 handoff 와 스터디룸 handoff 사용이 고른 카메라 판정을 거친다', () => {
  const src = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  const groupStudy = fs.readFileSync(path.join(src, 'pages/GroupStudy.jsx'), 'utf8');
  const studyRoom = fs.readFileSync(path.join(src, 'components/StudyRoom.jsx'), 'utf8');
  assert.match(groupStudy, /if \(isTrackForSelectedCamera\(vTrack, selectedCamera\)\) handoff = vTrack\.clone\(\);/);
  assert.doesNotMatch(groupStudy, /readyState === 'live'\) handoff = vTrack\.clone\(\)/);
  assert.match(studyRoom, /const hasHandoff = isTrackForSelectedCamera\(handoffVideoTrack, selectedCamera\);/);
  // 새 카메라를 여는 중(checking)일 때만 기다리고, 기다리는 동안 입장 버튼은 '카메라 준비 중…'
  assert.match(groupStudy, /if \(!isTrackForSelectedCamera\(vTrack, selectedCamera\) && cameraStatusRef\.current === 'checking'\)/);
  assert.match(groupStudy, /preparingCamera \? '카메라 준비 중…'/);
});
