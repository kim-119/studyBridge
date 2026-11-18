// 자동재생 차단 감지 + 사용자 재시도.
//
// openvidu-browser 2.30 은 addVideoElement 에서 <video>.autoplay 만 켜고 play() 를 부르지 않는다. 브라우저가 소리 있는
// 자동재생을 막으면(사용자 동작 전 입장·iOS 등) 요소는 조용히 멈춰 있고 Promise 거부도 드러나지 않는다.
// → 직접 play() 를 불러 NotAllowedError 를 감지하고, 막힌 요소를 모아 두었다가 사용자가 누른 순간(사용자 활성화 안)에
//   한꺼번에 다시 재생한다. 소리를 끄고 재생하는 우회는 하지 않는다 — 원격 음성이 사용자 모르게 꺼지지 않게.

export const PLAYBACK_RESULT = Object.freeze({ PLAYING: 'playing', BLOCKED: 'blocked', FAILED: 'failed', SKIPPED: 'skipped' });

const blocked = new Set();
const listeners = new Set();
const notify = () => listeners.forEach((listener) => { try { listener(); } catch (e) { /* ignore */ } });

/**
 * el.play() 결과. NotAllowedError(자동재생 차단)면 막힌 요소로 기록, 재생되면 기록 해제.
 * 그 밖의 거부(AbortError: 재생 시작 전에 srcObject 가 바뀜 등)는 FAILED — 다음 미디어 이벤트에서 다시 시도하면 된다.
 */
export function requestPlayback(el) {
  if (!el || typeof el.play !== 'function' || !el.srcObject) return Promise.resolve(PLAYBACK_RESULT.SKIPPED);
  let pending;
  try {
    pending = el.play();
  } catch (error) {
    pending = Promise.reject(error);
  }
  return Promise.resolve(pending).then(
    () => {
      if (blocked.delete(el)) notify();
      return PLAYBACK_RESULT.PLAYING;
    },
    (error) => {
      if (error?.name !== 'NotAllowedError') return PLAYBACK_RESULT.FAILED;
      if (!blocked.has(el)) {
        blocked.add(el);
        notify();
      }
      return PLAYBACK_RESULT.BLOCKED;
    }
  );
}

/** 막힌 요소를 모두 다시 재생한다. 반드시 사용자 클릭 핸들러 안에서 바로 불러야 한다(play() 가 같은 사용자 활성화 안에서 호출되도록). */
export function retryBlockedPlayback() {
  return Promise.all([...blocked].map((el) => requestPlayback(el)));
}

export const isPlaybackBlocked = (el) => blocked.has(el);

/** 요소가 사라질 때(언마운트) 기록을 지운다. */
export function forgetPlayback(el) {
  if (blocked.delete(el)) notify();
}

/** 막힌 요소 목록이 바뀔 때마다 listener 호출. 반환값 = 구독 해제. */
export function subscribePlaybackBlocked(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
