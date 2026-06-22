import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ROLE_NAMES } from './professorSprites';

const SHOW_MS = 12000;       // 자동 fade-out 까지(10~15초)
const RESUME_MS = 4000;      // hover 해제 후 남겨두는 시간
const FADE_MS = 320;         // fade-out 트랜지션

// stage 안 보조 UI. 기존 고정 안내 말풍선과 다르며, 새 대화가 있을 때만 표시된다.
//   · 10~15초 후 자동 fade-out, hover 시 유지.
//   · 답변 데이터 배열과 무관(presentation layer).
export default function MinuteRecapBubble({ recap, onDismiss }) {
  const [leaving, setLeaving] = useState(false);
  const timerRef = useRef(null);

  const clear = () => { if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null; } };
  const startTimer = useCallback((ms) => {
    clear();
    timerRef.current = setTimeout(() => {
      setLeaving(true);
      timerRef.current = setTimeout(() => { onDismiss?.(); }, FADE_MS);
    }, ms);
  }, [onDismiss]);

  // 새 recap(id 변경) → 다시 보이게 하고 타이머 재시작. unmount 시 타이머 정리.
  useEffect(() => {
    if (!recap) return undefined;
    setLeaving(false);
    startTimer(SHOW_MS);
    return clear;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recap?.id]);

  if (!recap) return null;
  const roleName = ROLE_NAMES[recap.role] || '교수';

  return (
    <div
      className={`minute-recap-bubble ${leaving ? 'is-leaving' : ''}`}
      role="status"
      aria-live="polite"
      onMouseEnter={clear}
      onMouseLeave={() => startTimer(RESUME_MS)}
    >
      <div className="minute-recap-head">
        <span className="minute-recap-role">🗒️ 방금 대화 요약 · {roleName}</span>
        <button
          type="button"
          className="minute-recap-close"
          aria-label="요약 닫기"
          onClick={() => { setLeaving(true); timerRef.current = setTimeout(() => onDismiss?.(), FADE_MS); }}
        >
          ×
        </button>
      </div>
      {recap.question ? <div className="minute-recap-q">Q. {recap.question}</div> : null}
      {recap.answer ? <div className="minute-recap-a">{recap.answer}</div> : null}
    </div>
  );
}
