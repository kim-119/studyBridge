import React, { useEffect, useRef, useState } from 'react';
import { RotateCcw, X, ZoomIn, ZoomOut } from 'lucide-react';
import { useBackDismiss } from '../platform/useBackDismiss';
import './imageViewer.css';
import {
  INITIAL_ZOOM,
  MAX_SCALE,
  MIN_SCALE,
  ZOOM_STEP,
  followGesture,
  startGesture,
  transformOf,
  zoomTo,
} from './imageZoom';

function useBodyScrollLock(isLocked) {
  useEffect(() => {
    if (!isLocked) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isLocked]);
}

function pointOf(event) {
  return { x: event.clientX, y: event.clientY };
}

function usePinchZoom(resetKey) {
  const [zoom, setZoom] = useState(INITIAL_ZOOM);
  const zoomRef = useRef(INITIAL_ZOOM);
  const pointers = useRef(new Map());
  const gesture = useRef(null);

  const applyZoom = (nextZoom) => {
    zoomRef.current = nextZoom;
    setZoom(nextZoom);
  };

  useEffect(() => {
    pointers.current.clear();
    gesture.current = null;
    zoomRef.current = INITIAL_ZOOM;
    setZoom(INITIAL_ZOOM);
  }, [resetKey]);

  const restartGesture = () => {
    gesture.current = startGesture(Array.from(pointers.current.values()), zoomRef.current);
  };

  const onPointerDown = (event) => {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, pointOf(event));
    restartGesture();
  };

  const onPointerMove = (event) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, pointOf(event));
    applyZoom(followGesture(gesture.current, Array.from(pointers.current.values())));
  };

  const onPointerEnd = (event) => {
    pointers.current.delete(event.pointerId);
    restartGesture();
  };

  return {
    zoom,
    zoomBy: (delta) => applyZoom(zoomTo(zoomRef.current, zoomRef.current.scale + delta)),
    reset: () => applyZoom(INITIAL_ZOOM),
    gestureHandlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp: onPointerEnd,
      onPointerCancel: onPointerEnd,
    },
  };
}

export default function ImageViewer({ src, alt = '', onClose }) {
  const isOpen = Boolean(src);
  const { zoom, zoomBy, reset, gestureHandlers } = usePinchZoom(src);

  useBackDismiss(isOpen, onClose);
  useBodyScrollLock(isOpen);

  if (!isOpen) return null;

  return (
    <div className="mobile-image-viewer" role="dialog" aria-modal="true" aria-label="이미지 보기">
      <div className="mobile-image-viewer__stage" {...gestureHandlers}>
        <img
          className="mobile-image-viewer__image"
          src={src}
          alt={alt}
          draggable={false}
          style={{ transform: transformOf(zoom) }}
        />
      </div>

      <div className="mobile-image-viewer__toolbar">
        <button
          type="button"
          className="mobile-image-viewer__button"
          aria-label="축소"
          disabled={zoom.scale <= MIN_SCALE}
          onClick={() => zoomBy(-ZOOM_STEP)}
        >
          <ZoomOut size={20} />
        </button>
        <span className="mobile-image-viewer__scale">{Math.round(zoom.scale * 100)}%</span>
        <button
          type="button"
          className="mobile-image-viewer__button"
          aria-label="확대"
          disabled={zoom.scale >= MAX_SCALE}
          onClick={() => zoomBy(ZOOM_STEP)}
        >
          <ZoomIn size={20} />
        </button>
        <button
          type="button"
          className="mobile-image-viewer__button"
          aria-label="원래 크기"
          disabled={zoom.scale === MIN_SCALE}
          onClick={reset}
        >
          <RotateCcw size={20} />
        </button>
      </div>

      <button type="button" className="mobile-image-viewer__close" aria-label="이미지 닫기" onClick={onClose}>
        <X size={24} />
      </button>
    </div>
  );
}
