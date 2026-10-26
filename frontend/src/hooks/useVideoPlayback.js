import { useEffect, useState } from 'react';
import { VIDEO_PLAYBACK, createFrameClock, currentVideoTrack, evaluateVideoPlayback } from '../utils/videoPlayback';
import { forgetPlayback, isPlaybackBlocked, requestPlayback, subscribePlaybackBlocked } from '../utils/mediaAutoplay';

// srcObject 교체(loadstart/emptied)부터 첫 프레임·일시정지·해상도 변경까지 — 요소 상태가 바뀔 수 있는 미디어 이벤트.
const MEDIA_EVENTS = ['loadstart', 'emptied', 'loadedmetadata', 'loadeddata', 'canplay', 'playing', 'pause', 'waiting', 'ended', 'resize'];
const TRACK_EVENTS = ['mute', 'unmute', 'ended'];

/**
 * <video> 의 실제 재생 상태(VIDEO_PLAYBACK). active=false(요소 없음)면 WAITING.
 *  · 이벤트가 올 때마다 요소·트랙 상태를 직접 다시 읽는다. mediaKey(스트림 교체·재연결) 가 바뀌어도 상태를 WAITING 으로 초기화하지
 *    않으므로, 이미 재생 중이라 playing 이벤트가 다시 오지 않는 요소를 '연결 중'으로 되돌리지 않는다.
 *  · requestVideoFrameCallback 지원 시 새 프레임 도착을 직접 확인한다(이벤트를 놓쳐도 프레임이 오면 PLAYING, 끊기면 STALLED).
 *    끊김은 이벤트가 없어 1초마다 다시 판정한다 — 오버레이를 시간으로 지우는 타이머가 아니라 '프레임 없음'을 감지하는 용도.
 *    탭이 숨겨진 시간은 끊김으로 세지 않는다(createFrameClock) — 탭 복귀 직후 첫 프레임 전의 STALLED 오탐 방지.
 *    미지원 브라우저는 timeupdate 로 재평가하고 멈춤은 트랙 mute 로만 판단한다.
 *  · 리스너는 이 effect 실행이 붙인 요소·트랙에만 걸고 cleanup 에서 뗀다 → 이전 요소·스트림의 늦은 이벤트가 새 상태를 덮지 못한다.
 *  · 멈춰 있는 요소는 직접 play() 를 불러 본다(openvidu 는 autoplay 만 켠다). 자동재생이 막히면 BLOCKED — 화면이 재생 버튼을 보여주고
 *    사용자가 누르면 retryBlockedPlayback 으로 다시 재생한다. 막힌 뒤에는 사용자 동작 전까지 다시 시도하지 않는다.
 */
export function useVideoPlayback(videoRef, active, mediaKey) {
  const [state, setState] = useState(VIDEO_PLAYBACK.WAITING);

  useEffect(() => {
    const v = videoRef.current;
    if (!active || !v) {
      setState(VIDEO_PLAYBACK.WAITING);
      return undefined;
    }
    let disposed = false;
    let last = null;
    let track = null;
    const clock = createFrameClock();
    if (document.hidden) clock.hide(performance.now());
    let frameHandle = null;
    let stallTimer = null;
    let playPending = false;

    const maybePlay = () => {
      if (disposed || playPending || !v.srcObject || !v.paused || v.ended || isPlaybackBlocked(v)) return;
      playPending = true;
      requestPlayback(v).finally(() => {
        playPending = false;
        evaluate();
      });
    };

    const evaluate = () => {
      if (disposed) return;
      const t = currentVideoTrack(v);
      if (t !== track) {
        if (track) TRACK_EVENTS.forEach((e) => track.removeEventListener(e, evaluate));
        track = t;
        clock.reset();
        if (document.hidden) clock.hide(performance.now());
        if (track) TRACK_EVENTS.forEach((e) => track.addEventListener(e, evaluate));
      }
      const next = evaluateVideoPlayback(v, { lastFrameAt: clock.lastFrameAt, now: performance.now(), hidden: document.hidden, blocked: isPlaybackBlocked(v) });
      if (next !== last) {
        last = next;
        setState(next);
      }
      maybePlay();
    };

    const watchFrames = typeof v.requestVideoFrameCallback === 'function';
    const onFrame = () => {
      if (disposed) return;
      clock.frame(performance.now());
      evaluate();
      frameHandle = v.requestVideoFrameCallback(onFrame);
    };
    const events = watchFrames ? MEDIA_EVENTS : [...MEDIA_EVENTS, 'timeupdate'];
    const onVisibility = () => {
      if (document.hidden) clock.hide(performance.now());
      else clock.show(performance.now());
      evaluate();
    };
    events.forEach((e) => v.addEventListener(e, evaluate));
    document.addEventListener('visibilitychange', onVisibility);
    const unsubscribeBlocked = subscribePlaybackBlocked(evaluate);
    if (watchFrames) {
      frameHandle = v.requestVideoFrameCallback(onFrame);
      stallTimer = setInterval(evaluate, 1000);
    }
    evaluate();

    return () => {
      disposed = true;
      events.forEach((e) => v.removeEventListener(e, evaluate));
      document.removeEventListener('visibilitychange', onVisibility);
      if (frameHandle != null) { try { v.cancelVideoFrameCallback(frameHandle); } catch (e) { /* ignore */ } }
      clearInterval(stallTimer);
      if (track) TRACK_EVENTS.forEach((e) => track.removeEventListener(e, evaluate));
      unsubscribeBlocked();
      forgetPlayback(v);
    };
  }, [videoRef, active, mediaKey]);

  return state;
}

export default useVideoPlayback;
