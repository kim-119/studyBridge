import test from 'node:test';
import assert from 'node:assert/strict';
import {
  clearVariantSession,
  createEmptyVariantSession,
  loadVariantSession,
  parseVariantSession,
  saveVariantSession,
  serializeVariantSession,
  variantSessionKey,
} from '../data/reviewNoteVariantSession.js';

const DEFAULT_SETTINGS = { wrongQuestionId: 1, difficulty: 'normal', count: 3 };

function createMemoryStorage() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
    size: () => values.size,
  };
}

function solvedSession() {
  return {
    settings: { wrongQuestionId: 2, difficulty: 'hard', count: 5 },
    lastRequest: { wrongQuestionId: 2, difficulty: 'hard', count: 5 },
    questions: [
      { id: 'sq-1', number: 1, question: 'Q1', choices: ['a', 'b'], answer: 'a' },
      { id: 'sq-2', number: 2, question: 'Q2', choices: ['c', 'd'], answer: 'd' },
    ],
    usedFallback: true,
    hasResult: true,
    activeId: 'sq-2',
    answers: { 'sq-1': 0, 'sq-2': 1 },
    submitted: { 'sq-1': true },
  };
}

test('풀이 상태는 직렬화 후 그대로 복원된다', () => {
  const session = solvedSession();
  assert.deepEqual(parseVariantSession(serializeVariantSession(session), DEFAULT_SETTINGS), session);
});

test('오답노트별 키로 저장하고 불러온다', () => {
  const storage = createMemoryStorage();
  assert.equal(saveVariantSession(7, solvedSession(), storage), true);

  assert.deepEqual(loadVariantSession(7, DEFAULT_SETTINGS, storage), solvedSession());
  assert.deepEqual(loadVariantSession(8, DEFAULT_SETTINGS, storage), createEmptyVariantSession(DEFAULT_SETTINGS));
  assert.equal(storage.getItem(variantSessionKey(7)) !== null, true);
});

test('삭제하면 저장된 상태가 사라진다', () => {
  const storage = createMemoryStorage();
  saveVariantSession(7, solvedSession(), storage);
  assert.equal(clearVariantSession(7, storage), true);
  assert.equal(storage.size(), 0);
  assert.deepEqual(loadVariantSession(7, DEFAULT_SETTINGS, storage), createEmptyVariantSession(DEFAULT_SETTINGS));
});

test('깨진 JSON 이나 다른 버전은 빈 상태로 시작한다', () => {
  assert.equal(parseVariantSession('{not json', DEFAULT_SETTINGS), null);
  assert.equal(parseVariantSession(JSON.stringify({ version: 99, questions: [] }), DEFAULT_SETTINGS), null);
  assert.equal(
    parseVariantSession(JSON.stringify({ version: 1, questions: [{ id: 1 }] }), DEFAULT_SETTINGS),
    null
  );
});

test('잘못된 답안·제출 값과 없는 활성 문제는 걸러낸다', () => {
  const raw = JSON.stringify({
    ...JSON.parse(serializeVariantSession(solvedSession())),
    activeId: 'missing',
    answers: { 'sq-1': 1, 'sq-2': 'x', 'sq-3': -1 },
    submitted: { 'sq-1': true, 'sq-2': 'yes' },
    lastRequest: { count: 0 },
  });
  const restored = parseVariantSession(raw, DEFAULT_SETTINGS);

  assert.equal(restored.activeId, 'sq-1');
  assert.deepEqual(restored.answers, { 'sq-1': 1 });
  assert.deepEqual(restored.submitted, { 'sq-1': true });
  assert.equal(restored.lastRequest, null);
});

test('저장소를 쓸 수 없으면 실패를 알리고 빈 상태를 준다', () => {
  const brokenStorage = {
    getItem: () => {
      throw new Error('denied');
    },
    setItem: () => {
      throw new Error('quota');
    },
    removeItem: () => {
      throw new Error('denied');
    },
  };
  assert.equal(saveVariantSession(1, solvedSession(), brokenStorage), false);
  assert.equal(clearVariantSession(1, brokenStorage), false);
  assert.deepEqual(loadVariantSession(1, DEFAULT_SETTINGS, brokenStorage), createEmptyVariantSession(DEFAULT_SETTINGS));
  assert.deepEqual(loadVariantSession(1, DEFAULT_SETTINGS, null), createEmptyVariantSession(DEFAULT_SETTINGS));
});
