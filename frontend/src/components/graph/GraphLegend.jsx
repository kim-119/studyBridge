import React from 'react';
import { NODE_COLOR, NODE_LABEL_KO } from '../../utils/graph/graphTypes';

// 범례: 현재 visible 그래프에 실제 등장하는 노드 타입만 표시.
export default function GraphLegend({ presentTypes }) {
  const types = (presentTypes && presentTypes.length)
    ? presentTypes
    : ['question', 'agent', 'answer', 'concept'];
  return (
    <div className="obsg-legend" aria-label="범례">
      {types.map((t) => (
        <div className="obsg-legend-row" key={t}>
          <span className="obsg-legend-dot" style={{ background: NODE_COLOR[t] || '#9ca3af' }} />
          <span>{NODE_LABEL_KO[t] || t}</span>
        </div>
      ))}
    </div>
  );
}
