import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ReviewScheduleError,
  VariantGenerationError,
  buildVariantRequest,
  correctChoiceText,
  describeScheduleResult,
  explanationSummary,
  isCorrectChoice,
  normalizeSimilarQuestions,
  readVariantResponse,
  registeredScheduleMessage,
  reviewDateBadges,
  reviewScheduleTitle,
  reviewTargetCount,
  similarQuestionStatus,
  wrongQuestionNumbers,
} from '../screens/reviewnotes/reviewNoteModel.js';

test('유사문제 요청은 웹과 같이 wrongQuestionId/difficulty/count 를 보낸다', () => {
  assert.deepEqual(buildVariantRequest({ wrongQuestionId: '2', difficulty: 'hard', count: '4' }), {
    wrongQuestionId: 2,
    difficulty: 'hard',
    count: 4,
  });
  assert.deepEqual(buildVariantRequest({ wrongQuestionId: '', difficulty: 'easy', count: 0 }), {
    wrongQuestionId: 1,
    difficulty: 'easy',
    count: 1,
  });
});

test('대상 오답 번호는 오답 수만큼, 최소 1개를 만든다', () => {
  assert.deepEqual(wrongQuestionNumbers({ wrongCount: 3 }), [1, 2, 3]);
  assert.deepEqual(wrongQuestionNumbers({ wrongCount: 0 }), [1]);
});

test('유사문제 응답의 여러 키 형태를 하나의 배열로 정규화한다', () => {
  const fromSimilar = normalizeSimilarQuestions({
    similarQuestions: [{ question: 'Q1', options: ['a', 'b'], correct_answer: 'b', variation_point: 'v' }],
  });
  assert.equal(fromSimilar[0].question, 'Q1');
  assert.deepEqual(fromSimilar[0].choices, ['a', 'b']);
  assert.equal(fromSimilar[0].answer, 'b');
  assert.equal(fromSimilar[0].variationPoint, 'v');
  assert.equal(fromSimilar[0].number, 1);

  assert.equal(normalizeSimilarQuestions({ data: { questions: [{ question: 'Q' }] } }).length, 1);
  assert.equal(normalizeSimilarQuestions({ result: { similarQuestions: { question: 'single' } } }).length, 1);
  assert.deepEqual(normalizeSimilarQuestions(null), []);
});

test('서버가 success=false 를 주면 메시지와 함께 실패로 처리한다', () => {
  assert.throws(() => readVariantResponse({ success: false, message: '원본 없음' }), (error) => {
    assert.ok(error instanceof VariantGenerationError);
    assert.equal(error.message, '원본 없음');
    return true;
  });
  assert.equal(readVariantResponse({ questions: [], usedFallback: true }).usedFallback, true);
});

test('정답은 보기 텍스트, 0-base, 1-base 인덱스를 모두 허용한다', () => {
  assert.equal(isCorrectChoice('b', 1, 'b'), true);
  assert.equal(isCorrectChoice('b', 1, '1'), true);
  assert.equal(isCorrectChoice('b', 1, '2'), true);
  assert.equal(isCorrectChoice('a', 0, 'b'), false);
  assert.equal(isCorrectChoice('a', 0, ''), false);

  const question = { choices: ['a', 'b'], answer: 'b' };
  assert.equal(correctChoiceText(question), 'b');
  assert.equal(similarQuestionStatus(question, 1, false), '풀이 전');
  assert.equal(similarQuestionStatus(question, 1, true), '정답');
  assert.equal(similarQuestionStatus(question, 0, true), '오답');
});

test('복습 일정 등록 제목과 결과 문구는 웹과 같다', () => {
  assert.equal(reviewScheduleTitle({ sourceName: '운영체제', title: 't' }), '[복습] 운영체제 오답 복습');
  assert.equal(reviewScheduleTitle({}), '[복습] 오답 오답 복습');
  assert.equal(
    describeScheduleResult({ todoId: 1, scheduledDate: '2026-09-30', alreadyRegistered: false }),
    '2026-09-30 주간 일정에 복습이 등록되었습니다.'
  );
  assert.equal(
    describeScheduleResult({ todoId: 1, scheduledDate: '2026-09-30', alreadyRegistered: true }),
    '2026-09-30 주간 일정에 이미 등록되어 있습니다.'
  );
  assert.throws(() => describeScheduleResult({ todoId: null }), ReviewScheduleError);
  assert.equal(
    registeredScheduleMessage({ reviewScheduled: true, recommendedReviewDate: '2026-09-30' }),
    '2026-09-30 주간 일정에 이미 등록되어 있습니다.'
  );
  assert.equal(registeredScheduleMessage({ reviewScheduled: false }), '');
});

test('추천 복습일 상태 배지는 완료 > 필요 순, 등록됨은 미완료일 때만', () => {
  assert.deepEqual(reviewDateBadges({}), []);
  assert.deepEqual(
    reviewDateBadges({ recommendedReviewDate: '2026-09-30', reviewNeeded: true, reviewScheduled: true }).map(
      (badge) => badge.label
    ),
    ['복습 필요', '일정 등록됨']
  );
  assert.deepEqual(
    reviewDateBadges({ recommendedReviewDate: '2026-09-30', reviewCompleted: true, reviewScheduled: true }).map(
      (badge) => badge.label
    ),
    ['복습 완료']
  );
});

test('복습 필요 수와 AI 해설 요약은 API 값만 사용한다', () => {
  assert.equal(reviewTargetCount({ reviewCount: 5, wrongCount: 1 }), 5);
  assert.equal(reviewTargetCount({ wrongCount: 2, unansweredCount: 1 }), 3);
  assert.equal(explanationSummary({ overallFeedback: 'f' }), 'f');
  assert.equal(explanationSummary({ aiExplanationSummary: 's', overallFeedback: 'f' }), 's');
  assert.equal(explanationSummary({}), '');
});
