export const MIN_SCALE = 1;
export const MAX_SCALE = 4;
export const ZOOM_STEP = 0.5;
export const INITIAL_ZOOM = { scale: 1, x: 0, y: 0 };

export function clampScale(scale) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

export function zoomTo(zoom, scale) {
  const nextScale = clampScale(scale);
  if (nextScale === MIN_SCALE) return INITIAL_ZOOM;
  return { ...zoom, scale: nextScale };
}

function distanceBetween(first, second) {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

export function startGesture(points, zoom) {
  const [first, second] = points;
  return {
    zoom,
    origin: first || null,
    distance: second ? distanceBetween(first, second) : 0,
  };
}

export function followGesture(gesture, points) {
  const [first, second] = points;
  if (!gesture || !first) return gesture?.zoom || INITIAL_ZOOM;

  if (second && gesture.distance > 0) {
    return zoomTo(gesture.zoom, gesture.zoom.scale * (distanceBetween(first, second) / gesture.distance));
  }

  if (gesture.zoom.scale === MIN_SCALE || !gesture.origin) return gesture.zoom;

  return {
    ...gesture.zoom,
    x: gesture.zoom.x + (first.x - gesture.origin.x),
    y: gesture.zoom.y + (first.y - gesture.origin.y),
  };
}

export function transformOf(zoom) {
  return `translate3d(${zoom.x}px, ${zoom.y}px, 0) scale(${zoom.scale})`;
}
