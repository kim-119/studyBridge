import React, { useState, useEffect } from 'react';

// 교수 sprite 머리 위 말풍선. agent_answer 도착 시 해당 교수 위에 답변을 띄운다.
//   · 긴 답변은 미리보기(2~3줄) + "더보기"로 접고, 펼치면 내부 스크롤로 전체를 본다.
//   · 답변 데이터 배열에 push하지 않는 presentation 전용(전체 답변은 아래 채팅 스레드에도 존재).
const PREVIEW_LEN = 120;

export default function ProfessorSpeechBubble({ name, text, side = 'center', color }) {
  const [expanded, setExpanded] = useState(false);

  // 새 답변(text 변경)이 오면 다시 접힌 상태로 시작한다.
  useEffect(() => { setExpanded(false); }, [text]);

  const body = String(text || '').trim();
  if (!body) return null;

  const isLong = body.length > PREVIEW_LEN;
  const preview = isLong ? `${body.slice(0, PREVIEW_LEN).trimEnd()}…` : body;
  const accent = color || '#2b2118';

  return (
    <div
      className={`prof-speech-bubble side-${side} ${expanded ? 'is-expanded' : ''}`}
      role="status"
      aria-live="polite"
      style={{ borderColor: accent }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="prof-speech-name" style={{ color: accent }}>{name || '교수'}</div>
      <div className={`prof-speech-text ${expanded ? 'is-full' : ''}`}>
        {expanded ? body : preview}
      </div>
      {isLong && (
        <button
          type="button"
          className="prof-speech-more"
          onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
        >
          {expanded ? '접기' : '더보기'}
        </button>
      )}
      <span className="prof-speech-tail" style={{ borderTopColor: accent }} aria-hidden="true" />
    </div>
  );
}
