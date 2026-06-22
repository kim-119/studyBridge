import React, { useState, useEffect } from 'react';

// 교수 sprite 머리 위 말풍선. agent_answer 도착 시 해당 교수 위에 답변을 띄운다.
//   · 긴 답변은 미리보기(2~3줄) + "더보기"로 접고, 펼치면 내부 스크롤로 전체를 본다.
//   · 답변 데이터 배열에 push하지 않는 presentation 전용(전체 답변은 아래 채팅 스레드에도 존재).
const PREVIEW_LEN = 120;

// kind → 대상 관계 라벨(피드백/반박일 때 "→ 대상" 꼬리표). 시각 연출용.
const TARGET_LABEL = { theory: '이론 교수', book: '문헌 교수', ai: 'AI 교수', user: '사용자' };

export default function ProfessorSpeechBubble({ name, text, side = 'center', color, kind = 'answer', targetRole }) {
  const [expanded, setExpanded] = useState(false);
  const [hidden, setHidden] = useState(false);

  // 새 답변(text 변경)이 오면 다시 펼침/표시 상태를 초기화한다.
  useEffect(() => { setExpanded(false); setHidden(false); }, [text]);

  const body = String(text || '').trim();
  if (!body || hidden) return null;

  const isLong = body.length > PREVIEW_LEN;
  const preview = isLong ? `${body.slice(0, PREVIEW_LEN).trimEnd()}…` : body;
  const accent = color || '#2b2118';
  // 피드백/반박 말풍선에만 "→ 대상" 관계를 보인다(누가 누구에게 하는 말인지).
  const relLabel = (kind === 'feedback' || kind === 'rebuttal') && targetRole ? TARGET_LABEL[targetRole] : '';

  return (
    <div
      className={`prof-speech-bubble side-${side} kind-${kind || 'answer'} ${expanded ? 'is-expanded' : ''}`}
      role="status"
      aria-live="polite"
      style={{ borderColor: accent }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="prof-speech-head">
        <span className="prof-speech-name" style={{ color: accent }}>
          {name || '교수'}{relLabel && <span className="prof-speech-target"> → {relLabel}</span>}
        </span>
        <button
          type="button"
          className="prof-speech-close"
          aria-label="말풍선 닫기"
          onClick={(e) => { e.stopPropagation(); setHidden(true); }}
        >
          ×
        </button>
      </div>
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
