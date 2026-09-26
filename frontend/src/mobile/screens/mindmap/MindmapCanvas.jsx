import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Crosshair, Minus, Plus } from 'lucide-react';

const MIN_SCALE = 0.3;
const MAX_SCALE = 3;
const NODE_RADIUS = 18;

function clampScale(value) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

function distanceBetween(touches) {
  const dx = touches[0].clientX - touches[1].clientX;
  const dy = touches[0].clientY - touches[1].clientY;
  return Math.hypot(dx, dy);
}

/**
 * SVG 기반 마인드맵 캔버스. 드래그 팬 + 핀치/버튼 줌 + 노드 탭을 지원한다.
 * 노드 수가 많아도 DOM 을 늘리지 않도록 원/선만 그리고 라벨은 확대 시에만 렌더한다.
 */
export default function MindmapCanvas({ view, highlightIds, onSelectNode, focusNodeId }) {
  const containerRef = useRef(null);
  const [size, setSize] = useState({ width: 320, height: 420 });
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });

  const gestureRef = useRef(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return undefined;

    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  const fitToView = useCallback(() => {
    if (!view?.bounds || size.width === 0) return;

    const { minX, minY, maxX, maxY } = view.bounds;
    const graphWidth = Math.max(1, maxX - minX) + NODE_RADIUS * 4;
    const graphHeight = Math.max(1, maxY - minY) + NODE_RADIUS * 4;

    const scale = clampScale(Math.min(size.width / graphWidth, size.height / graphHeight));
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    setTransform({
      scale,
      x: size.width / 2 - centerX * scale,
      y: size.height / 2 - centerY * scale,
    });
  }, [view, size]);

  useEffect(() => {
    fitToView();
  }, [fitToView]);

  useEffect(() => {
    if (!focusNodeId || !view) return;

    const node = view.nodes.find((item) => item.id === focusNodeId);
    if (!node) return;

    setTransform((previous) => ({
      ...previous,
      x: size.width / 2 - node.x * previous.scale,
      y: size.height / 2 - node.y * previous.scale,
    }));
  }, [focusNodeId, view, size]);

  const handleTouchStart = (event) => {
    if (event.touches.length === 2) {
      gestureRef.current = {
        mode: 'pinch',
        distance: distanceBetween(event.touches),
        scale: transform.scale,
      };
      return;
    }

    gestureRef.current = {
      mode: 'pan',
      startX: event.touches[0].clientX,
      startY: event.touches[0].clientY,
      originX: transform.x,
      originY: transform.y,
    };
  };

  const handleTouchMove = (event) => {
    const gesture = gestureRef.current;
    if (!gesture) return;

    if (gesture.mode === 'pinch' && event.touches.length === 2) {
      const ratio = distanceBetween(event.touches) / (gesture.distance || 1);
      setTransform((previous) => ({ ...previous, scale: clampScale(gesture.scale * ratio) }));
      return;
    }

    if (gesture.mode === 'pan' && event.touches.length === 1) {
      setTransform((previous) => ({
        ...previous,
        x: gesture.originX + (event.touches[0].clientX - gesture.startX),
        y: gesture.originY + (event.touches[0].clientY - gesture.startY),
      }));
    }
  };

  const handleTouchEnd = () => {
    gestureRef.current = null;
  };

  const zoomBy = (factor) => {
    setTransform((previous) => {
      const scale = clampScale(previous.scale * factor);
      const centerX = size.width / 2;
      const centerY = size.height / 2;

      return {
        scale,
        x: centerX - ((centerX - previous.x) / previous.scale) * scale,
        y: centerY - ((centerY - previous.y) / previous.scale) * scale,
      };
    });
  };

  if (!view) return null;

  const showLabels = transform.scale >= 0.75;

  return (
    <div className="mobile-mindmap" ref={containerRef}>
      <svg
        className="mobile-mindmap__canvas"
        width={size.width}
        height={size.height}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.scale})`}>
          {view.edges.map((edge) => (
            <line
              key={edge.id}
              x1={edge.from.x}
              y1={edge.from.y}
              x2={edge.to.x}
              y2={edge.to.y}
              className="mobile-mindmap__edge"
            />
          ))}

          {view.nodes.map((node) => {
            const isHighlighted = highlightIds?.has(node.id);

            return (
              <g key={node.id} onClick={() => onSelectNode(node)} className="mobile-mindmap__node">
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={isHighlighted ? NODE_RADIUS + 4 : NODE_RADIUS}
                  fill={node.color}
                  stroke={isHighlighted ? '#111827' : 'rgba(17,24,39,0.25)'}
                  strokeWidth={isHighlighted ? 3 : 1}
                />

                {showLabels && (
                  <text x={node.x} y={node.y + NODE_RADIUS + 14} className="mobile-mindmap__label">
                    {node.label.length > 12 ? `${node.label.slice(0, 12)}…` : node.label}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      <div className="mobile-mindmap__controls">
        <button type="button" aria-label="확대" onClick={() => zoomBy(1.25)}>
          <Plus size={18} />
        </button>
        <button type="button" aria-label="축소" onClick={() => zoomBy(0.8)}>
          <Minus size={18} />
        </button>
        <button type="button" aria-label="전체 보기" onClick={fitToView}>
          <Crosshair size={18} />
        </button>
      </div>
    </div>
  );
}
