import React, { useMemo, useState } from 'react';
import { labelForNodeType, colorForNode } from '../../utils/graph/graphTypes';

// 검색 패널: label/title/body/obsidianName/aliases/tags 인덱스 대상.
export default function GraphSearchPanel({ nodes, onPick, onClose }) {
  const [q, setQ] = useState('');

  const index = useMemo(() => nodes.map((n) => ({
    node: n,
    hay: [n.label, n.title, n.body, n.obsidianName, n.agentName, ...(n.aliases || []), ...(n.tags || [])]
      .join(' ').toLowerCase(),
  })), [nodes]);

  const results = useMemo(() => {
    const query = q.trim().toLowerCase();
    if (!query) return [];
    return index.filter((x) => x.hay.includes(query)).slice(0, 30).map((x) => x.node);
  }, [q, index]);

  return (
    <div className="obsg-search" role="search">
      <div style={{ display: 'flex', gap: 6 }}>
        {/* eslint-disable-next-line jsx-a11y/no-autofocus */}
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="노드 검색…"
          aria-label="노드 검색"
        />
        <button type="button" className="obsg-icon-btn" onClick={onClose} aria-label="검색 닫기">✕</button>
      </div>
      {q.trim() && (
        <div className="obsg-search-results">
          {results.length === 0 ? (
            <div style={{ padding: 8, fontSize: 12, color: '#64748b' }}>결과 없음</div>
          ) : results.map((n) => (
            <button type="button" key={n.id} className="obsg-link-item" onClick={() => onPick?.(n)}>
              <span className="obsg-legend-dot" style={{ background: colorForNode(n.type), display: 'inline-block', marginRight: 6 }} />
              <span style={{ color: '#94a3b8', fontSize: 10, marginRight: 6 }}>{labelForNodeType(n.type)}</span>
              {n.shortLabel || n.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
