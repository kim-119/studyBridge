import React, { useEffect, useRef, useState } from 'react';
import { FRAME_SIZE, SHEET_W, SHEET_H, getStateAnim, framePosition } from './professorSprites';

// prefers-reduced-motion 감지(모션 최소화 사용자에게는 프레임 순환을 멈춘다).
function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined;
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(!!mq.matches);
    update();
    // Safari 구버전 호환(addEventListener 없을 때 addListener).
    if (mq.addEventListener) mq.addEventListener('change', update);
    else if (mq.addListener) mq.addListener(update);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener('change', update);
      else if (mq.removeListener) mq.removeListener(update);
    };
  }, []);
  return reduced;
}

// 교수 1인 actor. img 전체 sheet가 아니라, div background-position 으로 frame 한 칸만 crop.
//   레이어 분리(transform 충돌 방지):
//     position-layer(좌표/스케일) > motion-layer(걷기/말하기 흔들림) > frame(sprite crop)
export default function PixelProfessorSprite({ role, name, tagline, sheet, side, pos, state, selected, onSelect }) {
  const anim = getStateAnim(state);
  const [frameIdx, setFrameIdx] = useState(0);
  const reducedMotion = usePrefersReducedMotion();
  const intervalRef = useRef(null);

  // 상태가 바뀌면 프레임 인덱스를 0으로 리셋하고 interval을 재설정한다.
  //   · interval=0/단일 프레임/reduced-motion 이면 정지(단일 프레임 표시).
  //   · unmount/상태 변경 시 반드시 clearInterval (StrictMode 이중 마운트 시에도 누수 없음).
  useEffect(() => {
    setFrameIdx(0);
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    const a = getStateAnim(state);
    if (reducedMotion || !a.interval || a.frames.length <= 1) return undefined;
    intervalRef.current = setInterval(() => {
      setFrameIdx((i) => (i + 1) % a.frames.length);
    }, a.interval);
    return () => {
      if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
    };
  }, [state, reducedMotion]);

  const frame = anim.frames[Math.min(frameIdx, anim.frames.length - 1)] || anim.frames[0];
  const frameStyle = {
    backgroundImage: `url("${sheet}")`,
    backgroundPosition: framePosition(frame),
    backgroundSize: `${SHEET_W}px ${SHEET_H}px`,
    width: `${FRAME_SIZE}px`,
    height: `${FRAME_SIZE}px`,
  };

  return (
    <button
      type="button"
      className={`professor-position-layer side-${side} ${selected ? 'is-selected' : ''}`}
      style={{ left: `${pos.left}%`, bottom: `${pos.bottom}px` }}
      onClick={(e) => { e.stopPropagation(); onSelect(role); }}
      aria-label={`${name} — ${tagline}`}
      aria-pressed={selected}
      title={`${name} · ${tagline}`}
    >
      <span className={`professor-motion-layer state-${state}`}>
        <span className="pixel-professor-frame" style={frameStyle} aria-hidden="true" />
      </span>
      <span className="pixel-professor-label" aria-hidden="true">
        <strong>{name}</strong>
        <em>{tagline}</em>
      </span>
    </button>
  );
}
