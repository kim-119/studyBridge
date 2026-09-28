import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Crosshair, Minus, Plus } from 'lucide-react';
import {
  centerOn,
  distanceBetween,
  fitTransform,
  hasMovedBeyondTap,
  midpointOf,
  pinchTransform,
  zoomAround,
} from './canvasTransform';

const NODE_RADIUS = 18;
const LABEL_MIN_SCALE = 0.75;
const LABEL_MAX_LENGTH = 12;
const ZOOM_STEP = 1.25;

function useLatest(value) {
  const ref = useRef(value);
  ref.current = value;
  return ref;
}

function useElementSize(elementRef) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return undefined;

    const observer = new ResizeObserver(([entry]) => {
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [elementRef]);

  return size;
}

function useTouchGestures(containerRef, transformRef, setTransform) {
  const gestureRef = useRef(null);
  const movedRef = useRef(false);

  const pointOf = useCallback(
    (touch) => {
      const rect = containerRef.current.getBoundingClientRect();
      return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
    },
    [containerRef]
  );

  const beginPan = useCallback(
    (touch) => {
      gestureRef.current = { mode: 'pan', origin: pointOf(touch), start: transformRef.current };
    },
    [pointOf, transformRef]
  );

  const beginPinch = useCallback(
    (touches) => {
      const first = pointOf(touches[0]);
      const second = pointOf(touches[1]);
      movedRef.current = true;
      gestureRef.current = {
        mode: 'pinch',
        start: transformRef.current,
        distance: distanceBetween(first, second) || 1,
        midpoint: midpointOf(first, second),
      };
    },
    [pointOf, transformRef]
  );

  const onTouchStart = (event) => {
    if (event.touches.length >= 2) {
      beginPinch(event.touches);
      return;
    }
    movedRef.current = false;
    beginPan(event.touches[0]);
  };

  const onTouchMove = (event) => {
    const gesture = gestureRef.current;
    if (!gesture) return;

    if (gesture.mode === 'pinch' && event.touches.length >= 2) {
      const first = pointOf(event.touches[0]);
      const second = pointOf(event.touches[1]);
      const ratio = distanceBetween(first, second) / gesture.distance;
      setTransform(pinchTransform(gesture.start, gesture.midpoint, midpointOf(first, second), ratio));
      return;
    }

    if (gesture.mode === 'pan' && event.touches.length === 1) {
      const point = pointOf(event.touches[0]);
      if (hasMovedBeyondTap(gesture.origin, point)) movedRef.current = true;
      setTransform({
        ...gesture.start,
        x: gesture.start.x + (point.x - gesture.origin.x),
        y: gesture.start.y + (point.y - gesture.origin.y),
      });
    }
  };

  const onTouchEnd = (event) => {
    if (event.touches.length === 1) {
      beginPan(event.touches[0]);
      return;
    }
    gestureRef.current = null;
  };

  const isTap = () => !movedRef.current;

  return { handlers: { onTouchStart, onTouchMove, onTouchEnd, onTouchCancel: onTouchEnd }, isTap };
}

function truncateLabel(label) {
  return label.length > LABEL_MAX_LENGTH ? `${label.slice(0, LABEL_MAX_LENGTH)}…` : label;
}

function MindmapEdges({ edges }) {
  return edges.map((edge) => (
    <line
      key={edge.id}
      x1={edge.from.x}
      y1={edge.from.y}
      x2={edge.to.x}
      y2={edge.to.y}
      className="mobile-mindmap__edge"
      style={{ stroke: edge.color }}
      strokeDasharray={edge.dashed ? '6 4' : undefined}
    />
  ));
}

function MindmapNodes({ nodes, highlightIds, showLabels, onTapNode }) {
  return nodes.map((node) => {
    const isHighlighted = highlightIds?.has(node.id);

    return (
      <g key={node.id} onClick={() => onTapNode(node)} className="mobile-mindmap__node">
        <circle
          cx={node.x}
          cy={node.y}
          r={isHighlighted ? NODE_RADIUS + 4 : NODE_RADIUS}
          fill={node.color}
          className={isHighlighted ? 'mobile-mindmap__dot is-highlighted' : 'mobile-mindmap__dot'}
        />
        {showLabels && (
          <text x={node.x} y={node.y + NODE_RADIUS + 14} className="mobile-mindmap__label">
            {truncateLabel(node.label)}
          </text>
        )}
      </g>
    );
  });
}

export default function MindmapCanvas({ view, fitKey, highlightIds, focusTarget, onSelectNode }) {
  const containerRef = useRef(null);
  const size = useElementSize(containerRef);
  const sizeRef = useLatest(size);
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const transformRef = useLatest(transform);
  const fittedKeyRef = useRef(null);
  const fitIdentity = fitKey ?? view;
  const gestures = useTouchGestures(containerRef, transformRef, setTransform);

  const fitToView = useCallback(() => {
    const currentSize = sizeRef.current;
    if (!view?.bounds || currentSize.width === 0) return;
    setTransform(fitTransform(view.bounds, currentSize, NODE_RADIUS * 2));
  }, [sizeRef, view]);

  useEffect(() => {
    if (!view || size.width === 0 || fittedKeyRef.current === fitIdentity) return;
    fittedKeyRef.current = fitIdentity;
    fitToView();
  }, [fitIdentity, fitToView, size.width, view]);

  useEffect(() => {
    if (!focusTarget || !view?.nodes) return;
    const node = view.nodes.find((item) => item.id === focusTarget.id);
    if (node) setTransform((previous) => centerOn(previous, node, sizeRef.current));
  }, [focusTarget, sizeRef, view]);

  const zoomBy = (factor) => {
    const center = { x: sizeRef.current.width / 2, y: sizeRef.current.height / 2 };
    setTransform((previous) => zoomAround(previous, center, previous.scale * factor));
  };

  const handleTapNode = (node) => {
    if (gestures.isTap()) onSelectNode(node);
  };

  if (!view) return null;

  return (
    <div className="mobile-mindmap" ref={containerRef}>
      <svg className="mobile-mindmap__canvas" width={size.width} height={size.height} {...gestures.handlers}>
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.scale})`}>
          <MindmapEdges edges={view.edges} />
          <MindmapNodes
            nodes={view.nodes}
            highlightIds={highlightIds}
            showLabels={transform.scale >= LABEL_MIN_SCALE}
            onTapNode={handleTapNode}
          />
        </g>
      </svg>

      <div className="mobile-mindmap__controls">
        <button type="button" aria-label="확대" onClick={() => zoomBy(ZOOM_STEP)}>
          <Plus size={18} />
        </button>
        <button type="button" aria-label="축소" onClick={() => zoomBy(1 / ZOOM_STEP)}>
          <Minus size={18} />
        </button>
        <button type="button" aria-label="전체 보기" onClick={fitToView}>
          <Crosshair size={18} />
        </button>
      </div>
    </div>
  );
}
