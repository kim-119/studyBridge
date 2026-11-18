import { useCallback, useEffect, useRef, useState } from 'react';
import { MEDIA_POLL_MS, createMediaLinkWatcher, subscribeMediaLinkEvents } from '../utils/mediaHealth';

const IDLE = { link: null, autoAttempts: 0 };

/**
 * OpenVidu 스트림(구독자=inbound, 내 송출자=outbound)의 전송 경로 단계(MEDIA_LINK). enabled=false 면 link=null.
 *  · 원격 타일은 아직 재생 전이거나 멈춘 동안만 켠다(재생 중엔 측정할 이유가 없다). 내 송출은 카메라가 켜진 동안 계속 본다.
 *  · autoAttempts = 지연(STUCK)으로 이미 자동 재연결한 횟수(영상이 다시 흐르면 0).
 *  · reconnect() 는 사용자 클릭용 — 그 스트림의 PeerConnection 만 다시 협상한다(세션 재생성 없음). busy = 재연결 진행 중.
 */
export function useMediaLinkHealth(streamManager, { enabled = true, direction = 'inbound' } = {}) {
  const [health, setHealth] = useState(IDLE);
  const [busy, setBusy] = useState(false);
  const watcherRef = useRef(null);

  useEffect(() => {
    if (!enabled || !streamManager || !streamManager.stream) {
      setHealth(IDLE);
      setBusy(false);
      return undefined;
    }
    const watcher = createMediaLinkWatcher(streamManager, {
      direction,
      onChange: (link, { autoAttempts }) => setHealth({ link, autoAttempts }),
      onBusy: setBusy,
    });
    watcherRef.current = watcher;
    watcher.tick();
    const timer = setInterval(() => watcher.tick(), MEDIA_POLL_MS);
    const unsubscribe = subscribeMediaLinkEvents(() => watcher.tick());
    return () => {
      clearInterval(timer);
      unsubscribe();
      watcher.dispose();
      if (watcherRef.current === watcher) watcherRef.current = null;
    };
  }, [streamManager, enabled, direction]);

  const reconnect = useCallback(() => watcherRef.current?.reconnect('user') ?? Promise.resolve(false), []);

  return { link: health.link, autoAttempts: health.autoAttempts, busy, reconnect };
}

export default useMediaLinkHealth;
