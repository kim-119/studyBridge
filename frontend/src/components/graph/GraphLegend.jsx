import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import {
  NODE_COLOR, NODE_LABEL_KO, EDGE_STYLE, EDGE_RELATION_LABEL,
} from '../../utils/graph/graphTypes';
import { TYPE_FILTER_KEY } from '../../utils/graph/graphFilters';

// 범례: 현재 visible 그래프에 실제 등장하는 노드 타입 + 관계(relationRole)를 표시.
//  · semanticRole(노드) / relationRole(간선) 두 축으로 의미를 설명한다(spec 22·90·91).
//  · 인터랙티브(spec 7): 행 hover → 해당 타입만 캔버스에서 강조(onHoverType),
//    노드 행 클릭 → 해당 타입 필터 on/off(onToggleFilter), 활성(숨김) 필터 개수 표시,
//    발표 모드/좁은 화면에서는 접을 수 있다.
export default function GraphLegend({
  presentTypes, presentEdgeTypes, filters, onToggleFilter, onHoverType,
  presentation = false, collapsed: collapsedProp, onToggleCollapsed,
}) {
  // 외부 제어(presentation 진입 시 접힘) + 내부 토글 둘 다 지원.
  const [localCollapsed, setLocalCollapsed] = useState(false);
  const collapsed = collapsedProp != null ? collapsedProp : localCollapsed;
  const toggleCollapsed = onToggleCollapsed || (() => setLocalCollapsed((v) => !v));

  const types = (presentTypes && presentTypes.length)
    ? presentTypes
    : ['question', 'agent', 'answer', 'concept'];
  const edgeTypes = (presentEdgeTypes && presentEdgeTypes.length) ? presentEdgeTypes : [];

  // 숨김(off) 상태인 토글 가능 타입 개수 = 활성 필터 수.
  const hiddenCount = filters
    ? types.reduce((acc, t) => {
      const key = TYPE_FILTER_KEY[t];
      return acc + (key && filters[key] === false ? 1 : 0);
    }, 0)
    : 0;

  const enter = (t) => onHoverType?.(t);
  const leave = () => onHoverType?.(null);

  return (
    <div className={`obsg-legend${presentation ? ' is-present' : ''}${collapsed ? ' is-collapsed' : ''}`} aria-label="범례">
      <button
        type="button"
        className="obsg-legend-toggle"
        onClick={toggleCollapsed}
        aria-expanded={!collapsed}
        title={collapsed ? '범례 펼치기' : '범례 접기'}
      >
        <span>범례{hiddenCount > 0 ? ` · 필터 ${hiddenCount}` : ''}</span>
        {collapsed ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
      </button>

      {!collapsed && (
        <div className="obsg-legend-body">
          <div className="obsg-legend-title">노드 (클릭: 표시/숨김)</div>
          {types.map((t) => {
            const key = TYPE_FILTER_KEY[t];
            const toggleable = !!key && !!onToggleFilter;
            const off = toggleable && filters && filters[key] === false;
            return (
              <button
                type="button"
                key={t}
                className={`obsg-legend-row${toggleable ? ' is-toggleable' : ''}${off ? ' is-off' : ''}`}
                onMouseEnter={() => enter(t)}
                onMouseLeave={leave}
                onFocus={() => enter(t)}
                onBlur={leave}
                onClick={() => toggleable && onToggleFilter(key)}
                disabled={!toggleable}
                title={toggleable ? `${NODE_LABEL_KO[t] || t} ${off ? '표시' : '숨기기'}` : (NODE_LABEL_KO[t] || t)}
                aria-pressed={toggleable ? !off : undefined}
              >
                <span className="obsg-legend-dot" style={{ background: NODE_COLOR[t] || '#9ca3af' }} />
                <span className="obsg-legend-label">{NODE_LABEL_KO[t] || t}</span>
              </button>
            );
          })}

          {edgeTypes.length > 0 && (
            <>
              <div className="obsg-legend-title" style={{ marginTop: 8 }}>관계</div>
              {edgeTypes.map((t) => (
                <div
                  className="obsg-legend-row is-edge"
                  key={`e-${t}`}
                  onMouseEnter={() => enter(t)}
                  onMouseLeave={leave}
                >
                  <span
                    className="obsg-legend-line"
                    style={{
                      background: (EDGE_STYLE[t] || {}).color || '#94a3b8',
                      ...(EDGE_STYLE[t] && EDGE_STYLE[t].dashed
                        ? { backgroundImage: 'repeating-linear-gradient(90deg, currentColor 0 3px, transparent 3px 6px)', color: (EDGE_STYLE[t] || {}).color }
                        : null),
                    }}
                  />
                  <span className="obsg-legend-label">[{EDGE_RELATION_LABEL[t] || t}]</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
