// 입장 준비 프리뷰 카메라 트랙 → 스터디룸 송출(handoff) 판정.
//
// 프리뷰는 새 카메라를 연 뒤에 이전 카메라를 끈다(전환 중에도 영상 유지). 그래서 카메라를 바꾼 직후 새 장치를 여는 중에는
// 프리뷰 트랙이 아직 이전 카메라다. 이때 입장하면서 그 트랙을 넘기면 마지막으로 고른 카메라 대신 이전 카메라가 송출된다.
// → 넘기는 쪽(입장 준비)과 받는 쪽(스터디룸) 모두 "지금 고른 카메라의 살아 있는 트랙"일 때만 handoff 를 쓴다.

/** track 이 selectedCamera(deviceId, '' = 기본 카메라) 의 살아 있는 트랙인지. 판정할 수 없으면 false(카메라를 새로 연다). */
export function isTrackForSelectedCamera(track, selectedCamera) {
  if (!track || track.readyState !== 'live') return false;
  if (!selectedCamera) return true;
  try {
    return track.getSettings?.().deviceId === selectedCamera;
  } catch (e) {
    return false;
  }
}

// 카메라를 바꾼 직후(새 장치를 여는 중)에 입장하면 그 획득을 기다렸다가 새 카메라 트랙을 넘긴다. 스터디룸이 같은 장치를 다시 열면
// 일부 장치는 정지 프레임만 주는 문제가 있어(handoff 를 쓰는 이유 — StudyRoom 'preview-handoff' 주석) 재획득보다 기다림이 안전하다.
export const PREVIEW_SWITCH_WAIT_MS = 5000;

/**
 * getTrack() 이 selectedCamera 의 살아 있는 트랙이 될 때까지 기다린다. 획득이 끝났는데(isAcquiring()=false) 아니거나
 * timeoutMs 가 지나면 null — 호출자는 handoff 없이 입장한다(스터디룸이 고른 카메라를 직접 연다).
 */
export async function waitForSelectedPreview({
  getTrack,
  selectedCamera,
  isAcquiring,
  timeoutMs = PREVIEW_SWITCH_WAIT_MS,
  intervalMs = 100,
  now = () => Date.now(),
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
}) {
  const startedAt = now();
  for (;;) {
    const track = getTrack();
    if (isTrackForSelectedCamera(track, selectedCamera)) return track;
    if (!isAcquiring() || now() - startedAt >= timeoutMs) return null;
    await sleep(intervalMs);
  }
}
