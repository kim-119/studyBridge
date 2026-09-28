export const MIN_SCALE = 0.3;
export const MAX_SCALE = 3;
export const TAP_MOVE_TOLERANCE_PX = 8;

export function clampScale(value) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
}

export function zoomAround(transform, anchor, requestedScale) {
  const scale = clampScale(requestedScale);
  const graphX = (anchor.x - transform.x) / transform.scale;
  const graphY = (anchor.y - transform.y) / transform.scale;

  return {
    scale,
    x: anchor.x - graphX * scale,
    y: anchor.y - graphY * scale,
  };
}

export function pinchTransform(start, startMidpoint, currentMidpoint, distanceRatio) {
  const zoomed = zoomAround(start, startMidpoint, start.scale * distanceRatio);

  return {
    scale: zoomed.scale,
    x: zoomed.x + (currentMidpoint.x - startMidpoint.x),
    y: zoomed.y + (currentMidpoint.y - startMidpoint.y),
  };
}

export function fitTransform(bounds, size, padding) {
  const graphWidth = Math.max(1, bounds.maxX - bounds.minX) + padding * 2;
  const graphHeight = Math.max(1, bounds.maxY - bounds.minY) + padding * 2;
  const scale = clampScale(Math.min(size.width / graphWidth, size.height / graphHeight));
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;

  return {
    scale,
    x: size.width / 2 - centerX * scale,
    y: size.height / 2 - centerY * scale,
  };
}

export function centerOn(transform, point, size) {
  return {
    ...transform,
    x: size.width / 2 - point.x * transform.scale,
    y: size.height / 2 - point.y * transform.scale,
  };
}

export function distanceBetween(first, second) {
  return Math.hypot(first.x - second.x, first.y - second.y);
}

export function midpointOf(first, second) {
  return { x: (first.x + second.x) / 2, y: (first.y + second.y) / 2 };
}

export function hasMovedBeyondTap(origin, point) {
  return distanceBetween(origin, point) > TAP_MOVE_TOLERANCE_PX;
}
