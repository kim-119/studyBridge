import { useLayoutEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { CSS_LAYER_STYLE, FULLSCREEN_HOST_STYLE, FULLSCREEN_MODE, fullscreenElementOf } from '../../utils/fullscreenViewer';

const HOST_STYLE_KEYS = Object.keys(FULLSCREEN_HOST_STYLE);

/**
 * 전체화면 보기 틀(hooks/useFullscreenViewer 와 짝). 내용(children)은 항상 viewer.host 하나에 렌더하고, 그 host 를
 *  · 평소: 제자리(자리표시 div 안) · native: 같은 자리에서 host 자체가 전체화면 요소 · CSS: portalTarget 의 고정 레이어로 옮긴다.
 *  host 노드를 옮길 뿐 React 는 다시 마운트하지 않는다 → 같은 <video> 요소·같은 OpenVidu Subscriber·같은 MediaStream 이 그대로다
 *  (재생 중인 요소를 appendChild 로 옮겨도 일시정지되지 않는다). 공통 틀이라 참가자 카메라 타일 확대에도 그대로 쓸 수 있다.
 *  · 전체화면 동안 자리표시는 직전 인라인 높이를 유지한다 — 뒤쪽 레이아웃이 당겨져 스크롤 위치가 잘리는 일 없이 그대로 복귀.
 *  · portalTarget: 스터디룸 루트(고정 오버레이). iOS WebKit 이 스크롤러 안 position:fixed 를 잘라내므로 스크롤러 밖에 둔다.
 */
export default function FullscreenFrame({ viewer, portalTarget = null, label = '전체화면 보기', testId = 'fullscreen-layer', children }) {
  const placeholderRef = useRef(null);
  const inlineHeightRef = useRef(0);
  const { host, mode } = viewer;

  useLayoutEffect(() => {
    const placeholder = placeholderRef.current;
    if (!host || !placeholder) return undefined;
    host.dataset.fullscreenMode = mode || '';
    HOST_STYLE_KEYS.forEach((k) => { host.style[k] = mode ? FULLSCREEN_HOST_STYLE[k] : ''; });
    if (!mode) {
      if (host.parentNode !== placeholder) placeholder.appendChild(host);
      return undefined;
    }
    // 이 시점엔 내용이 이미 전체화면 스타일로 바뀌었으므로 직전 인라인 측정값을 쓴다.
    placeholder.style.height = `${inlineHeightRef.current}px`;
    if (mode !== FULLSCREEN_MODE.CSS) return () => { placeholder.style.height = ''; };
    const layer = document.createElement('div');
    Object.assign(layer.style, CSS_LAYER_STYLE);
    layer.setAttribute('role', 'dialog');
    layer.setAttribute('aria-modal', 'true');
    layer.setAttribute('aria-label', label);
    layer.dataset.testid = testId;
    (portalTarget || document.body).appendChild(layer);
    layer.appendChild(host);
    return () => {
      placeholder.appendChild(host);
      placeholder.style.height = '';
      layer.remove();
    };
  }, [host, mode, portalTarget, label, testId]);

  // 인라인일 때의 높이(내용 margin 포함)를 계속 기록한다. native 는 브라우저가 host 를 top layer 로 먼저 옮긴 뒤에야
  // fullscreenchange → 상태 변경이 오므로, host 가 전체화면 요소인 동안의 측정(자리표시가 비어 0)은 버린다.
  useLayoutEffect(() => {
    const placeholder = placeholderRef.current;
    if (!placeholder || mode) return undefined;
    const measure = () => {
      if (host && fullscreenElementOf(document) === host) return;
      inlineHeightRef.current = placeholder.getBoundingClientRect().height;
    };
    measure();
    if (typeof ResizeObserver !== 'function') return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(placeholder);
    return () => ro.disconnect();
  }, [host, mode]);

  return (
    <>
      {/* flow-root: 내용의 margin 이 자리표시 밖으로 겹치지 않게 해(보이는 간격은 그대로) 잡아 둘 높이를 정확히 잰다. */}
      <div ref={placeholderRef} data-fullscreen-placeholder="true" style={{ display: 'flow-root' }} />
      {host ? createPortal(children, host) : children}
    </>
  );
}
