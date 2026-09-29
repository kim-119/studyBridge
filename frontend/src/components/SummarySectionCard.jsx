import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

/**
 * 자료보관함 요약 세부 카드.
 *  - 제목 + 본문. 본문이 길면 접기/펼치기.
 *  - 흰 배경 / 둥근 카드 / 초록 포인트 스타일 유지.
 */
export default function SummarySectionCard({ title, content, accent = 'var(--color-primary)', collapseThreshold = 220 }) {
  const text = (content || '').toString();
  const isLong = text.length > collapseThreshold;
  const [expanded, setExpanded] = useState(!isLong);
  const shown = expanded ? text : `${text.slice(0, collapseThreshold)}…`;

  return (
    <div
      style={{
        backgroundColor: '#F9FAFB',
        padding: '16px 18px',
        borderRadius: '12px',
        border: '1px solid var(--color-border)',
        borderLeft: `4px solid ${accent}`,
      }}
    >
      {title && <h5 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-main)' }}>{title}</h5>}
      <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.7', color: 'var(--color-text-muted)', whiteSpace: 'pre-wrap' }}>
        {shown}
      </p>
      {isLong && (
        <button
          onClick={() => setExpanded((v) => !v)}
          style={{
            marginTop: '10px',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '4px',
            border: 'none',
            background: 'transparent',
            color: 'var(--color-primary)',
            fontSize: '13px',
            fontWeight: 600,
            cursor: 'pointer',
            padding: 0,
          }}
        >
          {expanded ? (<><ChevronUp size={14} /> 접기</>) : (<><ChevronDown size={14} /> 더 보기</>)}
        </button>
      )}
    </div>
  );
}
