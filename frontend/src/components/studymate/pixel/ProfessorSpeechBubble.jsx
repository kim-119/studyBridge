import React, { useState, useEffect } from 'react';

// 교수 sprite 머리 위 말풍선. agent_answer 도착 시 해당 교수 위에 답변을 띄운다.
//   · 말풍선은 preview(2줄)만 보여주는 "클릭 가능한 버튼"이다.
//   · 클릭하면 onExpand로 전체 답변(fullText)을 상위(Stage)의 상세 패널에 띄운다.
//   · 답변 데이터 배열에 push하지 않는 presentation 전용(전체 답변은 아래 채팅 스레드에도 존재).

// kind → 대상 관계 라벨(피드백/반박일 때 "→ 대상" 꼬리표). 시각 연출용.
const TARGET_LABEL = { theory: '이론 교수', book: '문헌 교수', ai: 'AI 교수', user: '사용자' };

export default function ProfessorSpeechBubble({ name, text, fullText, side = 'center', color, kind = 'answer', targetRole, onExpand }) {
  const [hidden, setHidden] = useState(false);

  // 새 답변(text 변경)이 오면 다시 표시 상태를 초기화한다.
  useEffect(() => { setHidden(false); }, [text]);

  const preview = String(text || '').trim();
  const full = String(fullText || '').trim() || preview; // fullText 없으면 preview로 fallback
  if (!preview || hidden) return null;

  const accent = color || '#2b2118';
  // 피드백/반박 말풍선에만 "→ 대상" 관계를 보인다(누가 누구에게 하는 말인지).
  const relLabel = (kind === 'feedback' || kind === 'rebuttal') && targetRole ? TARGET_LABEL[targetRole] : '';
  // preview가 잘려있거나(원문이 더 김) thinking류가 아니면 "전체보기"를 노출한다.
  const hasMore = full.length > preview.length;

  const expand = (e) => {
    e.stopPropagation();
    onExpand?.({ name, kind, targetRole, fullText: full, text: preview });
  };

  return (
    <button
      type="button"
      className={`prof-speech-bubble side-${side} kind-${kind || 'answer'}`}
      style={{ borderColor: accent }}
      onClick={expand}
      aria-label={`${name || '교수'} 전체 답변 보기`}
      title="전체 답변 보기"
    >
      <div className="prof-speech-head">
        <span className="prof-speech-name" style={{ color: accent }}>
          {name || '교수'}{relLabel && <span className="prof-speech-target"> → {relLabel}</span>}
        </span>
        <span
          className="prof-speech-close"
          role="button"
          tabIndex={-1}
          aria-label="말풍선 닫기"
          onClick={(e) => { e.stopPropagation(); setHidden(true); }}
        >
          ×
        </span>
      </div>
      <span className="prof-speech-text">{preview}</span>
      {hasMore && <em className="prof-speech-more-hint">전체보기</em>}
      <span className="prof-speech-tail" style={{ borderTopColor: accent }} aria-hidden="true" />
    </button>
  );
}
