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
import { EMPHASIS, edgeEmphasis, nodeEmphasis } from './mindmapSelection';

const NODE_RADIUS = 18;
const LABEL_MIN_SCALE = 0.75;
const LABEL_MAX_LENGTH = 12;
const ZOOM_STEP = 1.25;
const RELATION_LABEL_MAX_LENGTH = 10;
const MIN_TOUCH_TARGET_PX = 44;
const EDGE_WIDTH_BY_EMPHASIS = {
  [EMPHASIS.NORMAL]: 1.2,
  [EMPHASIS.CONNECTED]: 3,
  [EMPHASIS.DIMMED]: 1,
};

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

function truncateLabel(label, maxLength = LABEL_MAX_LENGTH) {
  return label.length > maxLength ? `${label.slice(0, maxLength)}…` : label;
}

function MindmapEdges({ edges, neighborhood }) {
  return edges.map((edge) => {
    const emphasis = edgeEmphasis(neighborhood, edge.id);
    return (
      <line
        key={edge.id}
        x1={edge.from.x}
        y1={edge.from.y}
        x2={edge.to.x}
        y2={edge.to.y}
        className={`mobile-mindmap__edge is-${emphasis}`}
        data-edge-id={edge.id}
        data-edge-emphasis={emphasis}
        style={{ stroke: edge.color, strokeWidth: EDGE_WIDTH_BY_EMPHASIS[emphasis] }}
        strokeDasharray={edge.dashed ? '6 4' : undefined}
      />
    );
  });
}

function hitRadiusFor(scale) {
  return Math.max(NODE_RADIUS + 4, MIN_TOUCH_TARGET_PX / 2 / scale);
}

function RelationLabels({ edges, neighborhood }) {
  return edges
    .filter((edge) => edgeEmphasis(neighborhood, edge.id) === EMPHASIS.CONNECTED)
    .map((edge) => (
      <text
        key={`${edge.id}-label`}
        x={(edge.from.x + edge.to.x) / 2}
        y={(edge.from.y + edge.to.y) / 2}
        className="mobile-mindmap__relation"
      >
        {truncateLabel(edge.relationLabel, RELATION_LABEL_MAX_LENGTH)}
      </text>
    ));
}

function nodeClassName(isHighlighted, emphasis) {
  return ['mobile-mindmap__dot', isHighlighted ? 'is-highlighted' : '', `is-${emphasis}`].filter(Boolean).join(' ');
}

function MindmapNodes({ nodes, highlightIds, neighborhood, showLabels, hitRadius, onTapNode }) {
  return nodes.map((node) => {
    const emphasis = nodeEmphasis(neighborhood, node.id);
    const isHighlighted = highlightIds?.has(node.id) || emphasis === EMPHASIS.SELECTED;
    const showsLabel = showLabels || emphasis === EMPHASIS.SELECTED || emphasis === EMPHASIS.CONNECTED;

    return (
      <g
        key={node.id}
        onClick={(event) => {
          event.stopPropagation();
          onTapNode(node);
        }}
        className={`mobile-mindmap__node is-${emphasis}`}
        data-node-id={node.id}
        data-node-emphasis={emphasis}
      >
        <circle cx={node.x} cy={node.y} r={hitRadius} fill="transparent" className="mobile-mindmap__hit" />
        <circle
          cx={node.x}
          cy={node.y}
          r={isHighlighted ? NODE_RADIUS + 4 : NODE_RADIUS}
          fill={node.color}
          className={nodeClassName(isHighlighted, emphasis)}
        />
        {showsLabel && (
          <text x={node.x} y={node.y + NODE_RADIUS + 14} className="mobile-mindmap__label">
            {truncateLabel(node.label)}
          </text>
        )}
      </g>
    );
  });
}

export default function MindmapCanvas({
  view,
  fitKey,
  highlightIds,
  neighborhood,
  focusTarget,
  onSelectNode,
  onClearSelection,
}) {
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

  const handleTapBackground = () => {
    if (gestures.isTap()) onClearSelection();
  };

  if (!view) return null;

  return (
    <div className="mobile-mindmap" ref={containerRef}>
      <svg
        className="mobile-mindmap__canvas"
        width={size.width}
        height={size.height}
        onClick={handleTapBackground}
        {...gestures.handlers}
      >
        <g transform={`translate(${transform.x} ${transform.y}) scale(${transform.scale})`}>
          <MindmapEdges edges={view.edges} neighborhood={neighborhood} />
          <MindmapNodes
            nodes={view.nodes}
            highlightIds={highlightIds}
            neighborhood={neighborhood}
            showLabels={transform.scale >= LABEL_MIN_SCALE}
            hitRadius={hitRadiusFor(transform.scale)}
            onTapNode={handleTapNode}
          />
          <RelationLabels edges={view.edges} neighborhood={neighborhood} />
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
