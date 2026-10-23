import React, { useMemo, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { legendOf } from './mindmapModel';

export default function MindmapLegend({ view }) {
  const [isOpen, setOpen] = useState(false);
  const legend = useMemo(() => legendOf(view), [view]);

  if (!legend.nodeTypes.length) return null;

  return (
    <div className="mobile-mindmap-legend">
      <button type="button" className="mobile-mindmap-legend__toggle" aria-expanded={isOpen} onClick={() => setOpen(!isOpen)}>
        범례
        {isOpen ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {isOpen && (
        <div className="mobile-mindmap-legend__body">
          <ul className="mobile-mindmap-legend__list">
            {legend.nodeTypes.map((item) => (
              <li key={item.type}>
                <span className="mobile-mindmap-legend__dot" style={{ backgroundColor: item.color }} />
                {item.label}
              </li>
            ))}
          </ul>
          <ul className="mobile-mindmap-legend__list">
            {legend.edgeTypes.map((item) => (
              <li key={item.type}>
                <span
                  className={item.dashed ? 'mobile-mindmap-legend__line is-dashed' : 'mobile-mindmap-legend__line'}
                  style={{ borderTopColor: item.color }}
                />
                {item.label}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
