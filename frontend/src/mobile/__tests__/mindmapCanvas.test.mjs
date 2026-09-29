import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_SCALE,
  MIN_SCALE,
  centerOn,
  fitTransform,
  hasMovedBeyondTap,
  pinchTransform,
  zoomAround,
} from '../screens/mindmap/canvasTransform.js';

function toScreen(transform, point) {
  return { x: point.x * transform.scale + transform.x, y: point.y * transform.scale + transform.y };
}

function toGraph(transform, point) {
  return { x: (point.x - transform.x) / transform.scale, y: (point.y - transform.y) / transform.scale };
}

test('줌은 기준점 아래의 그래프 좌표를 고정한다', () => {
  const start = { x: 40, y: -20, scale: 1 };
  const anchor = { x: 120, y: 200 };
  const before = toGraph(start, anchor);
  const zoomed = zoomAround(start, anchor, 2);

  assert.equal(zoomed.scale, 2);
  assert.deepEqual(toScreen(zoomed, before), anchor);
});

test('핀치는 두 손가락 중심을 기준으로 확대하고 중심 이동만큼 팬한다', () => {
  const start = { x: 0, y: 0, scale: 1 };
  const startMidpoint = { x: 100, y: 100 };
  const graphPoint = toGraph(start, startMidpoint);
  const currentMidpoint = { x: 130, y: 90 };
  const next = pinchTransform(start, startMidpoint, currentMidpoint, 1.5);

  assert.equal(next.scale, 1.5);
  assert.deepEqual(toScreen(next, graphPoint), currentMidpoint);
});

test('배율은 최소/최대 범위로 제한한다', () => {
  assert.equal(zoomAround({ x: 0, y: 0, scale: 1 }, { x: 0, y: 0 }, 100).scale, MAX_SCALE);
  assert.equal(zoomAround({ x: 0, y: 0, scale: 1 }, { x: 0, y: 0 }, 0.001).scale, MIN_SCALE);
});

test('전체 보기는 그래프 중심을 화면 중심에 둔다', () => {
  const size = { width: 300, height: 400 };
  const fitted = fitTransform({ minX: -100, minY: -50, maxX: 100, maxY: 50 }, size, 20);
  assert.deepEqual(toScreen(fitted, { x: 0, y: 0 }), { x: 150, y: 200 });
});

test('노드 중심 맞추기는 배율을 유지한다', () => {
  const centered = centerOn({ x: 0, y: 0, scale: 2 }, { x: 10, y: 20 }, { width: 200, height: 100 });
  assert.equal(centered.scale, 2);
  assert.deepEqual(toScreen(centered, { x: 10, y: 20 }), { x: 100, y: 50 });
});

test('조금 움직인 터치는 탭, 크게 움직이면 팬으로 본다', () => {
  assert.equal(hasMovedBeyondTap({ x: 0, y: 0 }, { x: 3, y: 4 }), false);
  assert.equal(hasMovedBeyondTap({ x: 0, y: 0 }, { x: 12, y: 0 }), true);
});
