// <video> 의 "실제 재생" 판정 — React 불리언(onPlaying 을 받았는지)이 아니라 HTMLVideoElement·MediaStreamTrack 상태를 직접 읽는다.
//
// 배경(캠스터디 '카메라 연결 중…' 잔존): 원격 구독자의 mediaStream 은 첫 재생 직후에야 채워져 타일의 stream prop 이
// null → MediaStream 으로 바뀐다. 그때 "스트림이 바뀌면 재생 상태 초기화" 를 하면, openvidu-browser 의 addVideoElement 는
// srcObject 가 이미 같으면 다시 넣지 않아 playing 이벤트가 다시 오지 않으므로 재생 중인 영상 위에 오버레이가 영구히 남았다.
// 판정을 요소 상태에서 다시 읽으면 스트림 참조 교체·리렌더·이벤트 누락과 무관하게 실제 상태가 나온다.

export const VIDEO_PLAYBACK = Object.freeze({
  WAITING: 'waiting', // 프레임이 아직 없음(연결·로딩 중)
  PLAYING: 'playing', // 프레임을 그리는 중
  STALLED: 'stalled', // 트랙은 살아 있으나 새 프레임이 오지 않음(트랙 mute 또는 프레임 콜백 끊김)
  ENDED: 'ended', // 트랙 종료(장치 분리·권한 회수·연결 종료)
  BLOCKED: 'blocked', // 브라우저가 자동재생을 막아 멈춰 있음(play() 가 NotAllowedError) — 사용자가 눌러야 재생된다
});

// requestVideoFrameCallback 기준 이 시간 동안 새 프레임이 없으면 멈춘 것으로 본다(카메라는 정지 장면에서도 프레임을 계속 보낸다).
export const VIDEO_STALL_MS = 4000;

/**
 * 끊김 판정용 프레임 시계. 탭이 숨겨진 동안은 프레임 콜백이 멈추므로 그 시간을 '프레임 없음'으로 세지 않는다.
 *  · 숨김 → 표시: 마지막 프레임 시각을 숨겨진 시간만큼 뒤로 민다. 숨기기 직전까지 프레임이 오고 있었다면 복귀 직후
 *    STALLED 가 되지 않고(오탐 제거), 복귀 뒤 VIDEO_STALL_MS 동안 새 프레임이 없으면 그때 STALLED(실제 정지는 그대로 드러남).
 *    숨기기 전에 이미 끊겨 있었다면 밀어도 VIDEO_STALL_MS 를 넘으므로 복귀 직후에도 STALLED 로 남는다.
 */
export function createFrameClock() {
  let lastFrameAt = null;
  let hiddenAt = null;
  return {
    get lastFrameAt() { return lastFrameAt; },
    frame(now) { lastFrameAt = now; },
    reset() { lastFrameAt = null; hiddenAt = null; },
    hide(now) { if (hiddenAt === null) hiddenAt = now; },
    show(now) {
      if (hiddenAt !== null && lastFrameAt !== null) lastFrameAt += Math.max(0, now - hiddenAt);
      hiddenAt = null;
    },
  };
}

/** 요소에 연결된 MediaStream 의 첫 영상 트랙. 없거나 읽을 수 없으면 null. */
export function currentVideoTrack(el) {
  try {
    return el?.srcObject?.getVideoTracks?.()[0] || null;
  } catch (e) {
    return null;
  }
}

/** 로그용 요소·트랙 상태(개인정보 없음). */
export function snapshotVideo(el) {
  const t = currentVideoTrack(el);
  return {
    srcObject: !!el?.srcObject,
    readyState: el?.readyState ?? null,
    paused: el?.paused ?? null,
    ended: el?.ended ?? null,
    w: el?.videoWidth || 0,
    h: el?.videoHeight || 0,
    track: t ? { readyState: t.readyState, muted: !!t.muted, enabled: t.enabled !== false } : null,
  };
}

/**
 * @param el HTMLVideoElement(readyState·paused·ended·videoWidth·srcObject)
 * @param lastFrameAt requestVideoFrameCallback 로 본 마지막 새 프레임 시각(ms). 미지원·첫 프레임 전이면 null(요소 상태로만 판정)
 * @param now 현재 시각(ms, lastFrameAt 과 같은 시계)
 * @param hidden 문서가 숨겨져 있는지(숨긴 탭은 프레임 콜백이 멈추므로 끊김 판정을 하지 않는다)
 * @param blocked 이 요소의 play() 가 자동재생 정책으로 거부됐는지(utils/mediaAutoplay)
 */
export function evaluateVideoPlayback(el, { lastFrameAt = null, now = 0, hidden = false, blocked = false } = {}) {
  const track = currentVideoTrack(el);
  if (!track) return VIDEO_PLAYBACK.WAITING;
  if (track.readyState === 'ended') return VIDEO_PLAYBACK.ENDED;
  const rendering = el.readyState >= 2 && !el.paused && !el.ended && el.videoWidth > 0;
  if (!rendering) return blocked ? VIDEO_PLAYBACK.BLOCKED : VIDEO_PLAYBACK.WAITING;
  if (track.muted) return VIDEO_PLAYBACK.STALLED;
  if (lastFrameAt != null && !hidden && now - lastFrameAt > VIDEO_STALL_MS) return VIDEO_PLAYBACK.STALLED;
  return VIDEO_PLAYBACK.PLAYING;
}
