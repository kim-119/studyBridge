import React from 'react';
import {
  NODE_COLOR, NODE_LABEL_KO, EDGE_STYLE, EDGE_RELATION_LABEL,
} from '../../utils/graph/graphTypes';

// 범례: 현재 visible 그래프에 실제 등장하는 노드 타입 + 관계(relationRole)를 표시.
//  · semanticRole(노드) / relationRole(간선) 두 축으로 의미를 설명한다(spec 22·90·91).
export default function GraphLegend({ presentTypes, presentEdgeTypes }) {
  const types = (presentTypes && presentTypes.length)
    ? presentTypes
    : ['question', 'agent', 'answer', 'concept'];
  const edgeTypes = (presentEdgeTypes && presentEdgeTypes.length) ? presentEdgeTypes : [];
  return (
    <div className="obsg-legend" aria-label="범례">
      <div className="obsg-legend-title">노드</div>
      {types.map((t) => (
        <div className="obsg-legend-row" key={t}>
          <span className="obsg-legend-dot" style={{ background: NODE_COLOR[t] || '#9ca3af' }} />
          <span>{NODE_LABEL_KO[t] || t}</span>
        </div>
      ))}
      {edgeTypes.length > 0 && (
        <>
          <div className="obsg-legend-title" style={{ marginTop: 6 }}>관계</div>
          {edgeTypes.map((t) => (
            <div className="obsg-legend-row" key={`e-${t}`}>
              <span className="obsg-legend-line" style={{ background: (EDGE_STYLE[t] || {}).color || '#94a3b8' }} />
              <span>[{EDGE_RELATION_LABEL[t] || t}]</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
