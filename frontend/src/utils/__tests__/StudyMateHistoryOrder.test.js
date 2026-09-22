// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { reorderHistoryByRequest } from '../studymate/historyOrder.js';

const U = (id, rid, t) => ({ id, sender: 'USER', requestId: rid, content: t });
const A = (id, rid, t) => ({ id, sender: 'AI', requestId: rid, content: t });

test('late partial answers stored after the next question move back under their own question', () => {
  const rows = [U(1, 'rA', 'A?'), U(2, 'rB', 'B?'), U(3, 'rC', 'C?'), A(4, 'rB', 'b1'), A(5, 'rB', 'b2'), A(6, 'rC', 'c1')];
  const out = reorderHistoryByRequest(rows).map((r) => r.id);
  assert.deepEqual(out, [1, 2, 4, 5, 3, 6]);
});

test('normal ordering is untouched; legacy rows without requestId keep position', () => {
  const rows = [U(1, 'rA', 'A?'), A(2, 'rA', 'a1'), A(3, 'rA', 'a2'), { id: 4, sender: 'USER', content: 'legacy' }, { id: 5, sender: 'AI', content: 'legacy answer' }, U(6, 'rB', 'B?'), A(7, 'rB', 'b1')];
  assert.deepEqual(reorderHistoryByRequest(rows).map((r) => r.id), [1, 2, 3, 4, 5, 6, 7]);
});

test('AI rows whose USER row is missing stay in place; empty/short input safe', () => {
  assert.deepEqual(reorderHistoryByRequest([A(1, 'rX', 'x')]).map((r) => r.id), [1]);
  assert.deepEqual(reorderHistoryByRequest([]), []);
  const rows = [U(1, 'rA', 'A?'), A(2, 'rZ', 'orphan'), A(3, 'rA', 'a1')];
  assert.deepEqual(reorderHistoryByRequest(rows).map((r) => r.id), [1, 3, 2]);
});
