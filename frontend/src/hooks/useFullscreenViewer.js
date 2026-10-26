import { useCallback, useEffect, useRef, useState } from 'react';
import {
  FULLSCREEN_MODE, chooseFullscreenMode, exitDocumentFullscreen, fullscreenElementOf, hasHistoryMarker,
  isImmediateNativeExit, lockDocumentScroll, requestElementFullscreen, withHistoryMarker,
} from '../utils/fullscreenViewer';

const createHost = () => (typeof document !== 'undefined' ? document.createElement('div') : null);

/**
 * 전체화면 보기 상태(utils/fullscreenViewer 규칙). host = 전체화면으로 보여줄 DOM 요소(FullscreenFrame 이 내용을 렌더하는 곳).
 *  mode: null | 'native'(Fullscreen API) | 'css'(고정 레이어)
 *  · enter(): native 를 먼저 시도하고, 거부·미지원·WebView·진입 직후 해제면 CSS 로 바꾼다.
 *  · 종료 경로를 한곳에서 정리한다 — 버튼(exit)·Esc·브라우저/Android 뒤로가기·fullscreenchange(시스템 해제)·언마운트.
 *    CSS 모드는 진입 때 같은 URL 의 history 항목을 하나 쌓아(기존 state 보존) 뒤로가기가 '전체화면 닫기'가 되게 하고,
 *    다른 경로로 닫을 때는 그 항목을 되돌린다. history 조작은 이벤트 처리에서만 한다(StrictMode effect 이중 실행과 무관).
 */
export function useFullscreenViewer({ label = '전체화면 보기' } = {}) {
  const [host] = useState(createHost);
  const [mode, setModeState] = useState(null);
  const modeRef = useRef(null);
  const ctl = useRef({ enteredAt: null, exitRequested: false, pending: false, token: null, unlock: null });

  const setMode = useCallback((next, reason) => {
    const prev = modeRef.current;
    if (prev === next) return;
    modeRef.current = next;
    setModeState(next);
    console.info('[Fullscreen] mode', { label, from: prev, to: next, reason });
  }, [label]);

  const enterCss = useCallback((reason) => {
    const c = ctl.current;
    if (!c.unlock) c.unlock = lockDocumentScroll(document);
    if (!c.token) {
      const token = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
      try {
        window.history.pushState(withHistoryMarker(window.history.state, token), '');
        c.token = token;
      } catch (e) {
        c.token = null; // 뒤로가기 연동만 빠진다(닫기·Esc 는 그대로)
      }
    }
    setMode(FULLSCREEN_MODE.CSS, reason);
  }, [setMode]);

  /** CSS 모드 정리. popstate 로 닫힌 경우는 브라우저가 이미 항목을 꺼냈으므로 되돌리지 않는다. */
  const leaveCss = useCallback((reason) => {
    const c = ctl.current;
    if (c.unlock) { c.unlock(); c.unlock = null; }
    const token = c.token;
    c.token = null;
    if (token && reason !== 'popstate' && hasHistoryMarker(window.history.state, token)) {
      try { window.history.back(); } catch (e) { /* ignore */ }
    }
  }, []);

  const exit = useCallback((reason = 'user') => {
    const m = modeRef.current;
    if (m === FULLSCREEN_MODE.NATIVE) {
      ctl.current.exitRequested = true;
      exitDocumentFullscreen(document); // fullscreenchange 에서 상태 정리
      return;
    }
    if (m === FULLSCREEN_MODE.CSS) {
      leaveCss(reason);
      setMode(null, reason);
    }
  }, [leaveCss, setMode]);

  const enter = useCallback(async () => {
    const c = ctl.current;
    if (modeRef.current || c.pending || !host) return;
    const preferred = chooseFullscreenMode({
      el: host,
      doc: document,
      userAgent: typeof navigator !== 'undefined' ? navigator.userAgent : '',
      capacitor: typeof window !== 'undefined' ? window.Capacitor : null,
    });
    if (preferred === FULLSCREEN_MODE.NATIVE) {
      c.pending = true;
      c.exitRequested = false;
      c.enteredAt = performance.now();
      try {
        await requestElementFullscreen(host);
        if (modeRef.current) return; // fullscreenchange 처리기가 이미 정함(native 또는 즉시 해제 → css)
        if (fullscreenElementOf(document) === host) setMode(FULLSCREEN_MODE.NATIVE, 'api');
        else enterCss('native-not-entered');
        return;
      } catch (e) {
        console.warn('[Fullscreen] native rejected → css', { label, name: e?.name, message: e?.message });
      } finally {
        c.pending = false;
      }
      enterCss('native-rejected');
      return;
    }
    enterCss('css-preferred');
  }, [host, label, setMode, enterCss]);

  const toggle = useCallback(() => (modeRef.current ? exit('toggle') : enter()), [enter, exit]);

  // native: 진입·해제(Esc·Android 뒤로가기·시스템)를 fullscreenchange 로 받는다. 진입 직후 해제 = 환경이 막음 → CSS 로 대체.
  useEffect(() => {
    if (!host) return undefined;
    const onChange = () => {
      const c = ctl.current;
      if (fullscreenElementOf(document) === host) {
        if (modeRef.current !== FULLSCREEN_MODE.NATIVE) setMode(FULLSCREEN_MODE.NATIVE, 'fullscreenchange');
        return;
      }
      if (modeRef.current !== FULLSCREEN_MODE.NATIVE) return;
      if (isImmediateNativeExit({ enteredAt: c.enteredAt, now: performance.now(), exitRequested: c.exitRequested })) {
        enterCss('native-exited-immediately');
        return;
      }
      c.exitRequested = false;
      setMode(null, 'fullscreenchange');
    };
    document.addEventListener('fullscreenchange', onChange);
    document.addEventListener('webkitfullscreenchange', onChange);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      document.removeEventListener('webkitfullscreenchange', onChange);
    };
  }, [host, setMode, enterCss]);

  // CSS: Esc·뒤로가기로 닫기.
  useEffect(() => {
    if (mode !== FULLSCREEN_MODE.CSS) return undefined;
    const onPop = () => {
      const token = ctl.current.token;
      if (token && !hasHistoryMarker(window.history.state, token)) {
        leaveCss('popstate');
        setMode(null, 'popstate');
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape' && !e.defaultPrevented) exit('escape');
    };
    window.addEventListener('popstate', onPop);
    document.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('popstate', onPop);
      document.removeEventListener('keydown', onKey);
    };
  }, [mode, exit, leaveCss, setMode]);

  // 언마운트(공유 종료·퇴장): 열려 있던 전체화면을 닫고 스크롤·history 를 되돌린다.
  useEffect(() => () => {
    const m = modeRef.current;
    if (m === FULLSCREEN_MODE.CSS) leaveCss('unmount');
    if (m === FULLSCREEN_MODE.NATIVE && fullscreenElementOf(document) === host) {
      ctl.current.exitRequested = true;
      exitDocumentFullscreen(document);
    }
    modeRef.current = null;
  }, [host, leaveCss]);

  return { host, mode, isFullscreen: mode !== null, enter, exit, toggle };
}

export default useFullscreenViewer;
