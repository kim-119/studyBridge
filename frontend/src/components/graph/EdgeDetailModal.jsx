import React, { useEffect, useRef } from 'react';
import { relationLabelForEdgeType } from '../../utils/graph/graphTypes';

// ─────────────────────────────────────────────────────────────────────────────
// 간선(선/라벨) 클릭 시 전체 관계 설명을 보여주는 모달.
//  · 선 위에는 짧은 라벨([답변]·[반박]…)만, 전체 설명은 여기서 펼친다.
//  · click/tap 기준 동작(hover 비의존) → 모바일/태블릿 지원.
//  · 접근성: role=dialog, 진입 시 닫기 버튼 포커스, ESC/배경클릭/닫기버튼으로 닫힘.
// ─────────────────────────────────────────────────────────────────────────────
export default function EdgeDetailModal({ info, onClose }) {
  const closeRef = useRef(null);

  useEffect(() => {
    closeRef.current?.focus();
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); onClose(); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  if (!info) return null;
  const { shortLabel, fullLabel, relationType, fromLabel, toLabel } = info;
  const typeLabel = relationType ? relationLabelForEdgeType(relationType) : shortLabel;

  return (
    <div
      className="obsg-edge-detail-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="obsg-edge-detail-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`관계 설명: ${shortLabel}`}
      >
        <div className="obsg-edge-detail-header">
          <strong className="obsg-edge-detail-title">[{shortLabel}]</strong>
          <button
            ref={closeRef}
            type="button"
            className="obsg-edge-detail-close"
            onClick={onClose}
            aria-label="닫기"
          >
            닫기
          </button>
        </div>

        {(fromLabel || toLabel) && (
          <div className="obsg-edge-detail-route">
            <span>{fromLabel || '시작'}</span>
            <span className="obsg-edge-detail-arrow" aria-hidden="true">→</span>
            <span>{toLabel || '대상'}</span>
          </div>
        )}

        <p className="obsg-edge-detail-body">{fullLabel}</p>

        {relationType && (
          <span className="obsg-edge-detail-type">관계 유형: {typeLabel}</span>
        )}
      </div>
    </div>
  );
}
