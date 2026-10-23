import test from 'node:test';
import assert from 'node:assert/strict';
import { dismissTopLayer, pendingDismissCount, pushBackDismiss } from '../platform/backDismissStack.js';

test('열린 레이어가 없으면 back 은 라우팅에 넘긴다', () => {
  assert.equal(pendingDismissCount(), 0);
  assert.equal(dismissTopLayer(), false);
});

test('back 은 가장 나중에 열린 레이어 하나만 닫는다', () => {
  const closed = [];
  const removeTab = pushBackDismiss(() => closed.push('quiz-tab'));
  const removeSheet = pushBackDismiss(() => closed.push('sheet'));

  assert.equal(dismissTopLayer(), true);
  assert.deepEqual(closed, ['sheet']);

  removeSheet();
  assert.equal(dismissTopLayer(), true);
  assert.deepEqual(closed, ['sheet', 'quiz-tab']);

  removeTab();
  assert.equal(pendingDismissCount(), 0);
});

test('닫힌 레이어의 등록 해제는 다른 레이어에 영향을 주지 않는다', () => {
  const removeFirst = pushBackDismiss(() => {});
  const removeSecond = pushBackDismiss(() => {});

  removeFirst();
  removeFirst();
  assert.equal(pendingDismissCount(), 1);

  removeSecond();
  assert.equal(pendingDismissCount(), 0);
});
