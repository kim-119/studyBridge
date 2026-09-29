import test from 'node:test';
import assert from 'node:assert/strict';
import {
  COUNT_STATUS,
  appendMissingQuestions,
  canRequestMissing,
  checkVariantCount,
  missingRequestMessage,
  numberVariantQuestions,
  variantCountMessage,
} from '../screens/reviewnotes/variantCountModel.js';

function question(text) {
  return { id: 'server-id', number: 99, question: text, choices: ['a', 'b'], answer: 'a' };
}

test('요청 수와 받은 수가 같으면 불일치 메시지가 없다', () => {
  const check = checkVariantCount(3, 3);
  assert.equal(check.status, COUNT_STATUS.MATCHED);
  assert.equal(variantCountMessage(check), '');
  assert.equal(canRequestMissing(check), false);
});

test('적게 받으면 부족분과 함께 사용자에게 알린다', () => {
  const check = checkVariantCount(5, 3);
  assert.deepEqual(check, { status: COUNT_STATUS.SHORT, requested: 5, received: 3, missing: 2 });
  assert.equal(variantCountMessage(check), '5문제 요청 중 3문제만 생성되었습니다.');
  assert.equal(canRequestMissing(check), true);
});

test('하나도 받지 못해도 부족으로 판단한다', () => {
  const check = checkVariantCount(3, 0);
  assert.equal(check.status, COUNT_STATUS.SHORT);
  assert.equal(check.missing, 3);
  assert.equal(variantCountMessage(check), '3문제 요청 중 0문제만 생성되었습니다.');
});

test('많이 받으면 그대로 두되 불일치를 알린다', () => {
  const check = checkVariantCount(2, 4);
  assert.equal(check.status, COUNT_STATUS.OVER);
  assert.equal(check.missing, 0);
  assert.equal(canRequestMissing(check), false);
  assert.match(variantCountMessage(check), /2문제를 요청했지만 서버가 4문제를 반환했습니다/);
});

test('요청 전 상태는 불일치로 보지 않는다', () => {
  assert.equal(checkVariantCount(undefined, 0).status, COUNT_STATUS.MATCHED);
  assert.equal(checkVariantCount('3', '3').status, COUNT_STATUS.MATCHED);
});

test('서버 응답 문제는 개수를 바꾸지 않고 순서대로 번호와 id를 붙인다', () => {
  const numbered = numberVariantQuestions([question('A'), question('A'), question('B')]);
  assert.equal(numbered.length, 3);
  assert.deepEqual(numbered.map((item) => item.id), ['sq-1', 'sq-2', 'sq-3']);
  assert.deepEqual(numbered.map((item) => item.number), [1, 2, 3]);
});

test('부족분 추가 시 기존 문제 뒤에 이어 붙이고 중복은 제외한다', () => {
  const existing = numberVariantQuestions([question('A'), question('B')]);
  const merged = appendMissingQuestions(existing, [question('B '), question('C'), question('C')]);

  assert.deepEqual(merged.questions.map((item) => item.question), ['A', 'B', 'C']);
  assert.deepEqual(merged.questions.map((item) => item.id), ['sq-1', 'sq-2', 'sq-3']);
  assert.equal(merged.addedCount, 1);
  assert.equal(merged.skippedCount, 2);
});

test('부족분 재요청 결과 메시지', () => {
  assert.equal(
    missingRequestMessage({ requested: 2, addedCount: 2, skippedCount: 0 }),
    '부족분 2문제를 다시 요청해 2문제를 추가했습니다.'
  );
  assert.equal(
    missingRequestMessage({ requested: 2, addedCount: 0, skippedCount: 1 }),
    '부족분 2문제를 다시 요청했지만 새로 추가된 문제가 없습니다. 이미 받은 문제와 같은 1문제는 제외했습니다.'
  );
});
