import test from 'node:test';
import assert from 'node:assert/strict';
import {
  describeQuizGenerationFailure,
  describeQuizGenerationSuccess,
  evaluateGeneratedQuiz,
  serverReasonOf,
} from '../screens/groupstudy/quizGenerationModel.js';

const PDF_QUIZ = { id: 25, title: '[e2e-data-structures.pdf] PDF 기반 학습 퀴즈', questionCount: 3 };

test('응답의 문항 수가 0이어도 목록에서 확인된 문항 수로 성공을 판단한다', () => {
  const evaluation = evaluateGeneratedQuiz({ id: 25, title: PDF_QUIZ.title, questionCount: 0 }, [PDF_QUIZ]);
  assert.equal(evaluation.ok, true);
  assert.equal(evaluation.questionCount, 3);
  assert.equal(describeQuizGenerationSuccess(evaluation), `퀴즈를 만들었습니다: ${PDF_QUIZ.title} (3문항)`);
});

test('PDF와 무관한 기본 안내형 퀴즈는 성공으로 보여주지 않는다', () => {
  const placeholder = { id: 26, title: '자료 기반 학습 퀴즈 (기본 안내형)', questionCount: 3 };
  const evaluation = evaluateGeneratedQuiz(placeholder, [placeholder]);
  assert.equal(evaluation.ok, false);
  assert.match(evaluation.reason, /기본 문제/);
});

test('퀴즈 id가 없거나 목록에 없거나 문항이 없으면 실패로 처리한다', () => {
  assert.equal(evaluateGeneratedQuiz(null, [PDF_QUIZ]).ok, false);
  assert.equal(evaluateGeneratedQuiz({ id: 99, title: 'x', questionCount: 3 }, [PDF_QUIZ]).ok, false);
  assert.equal(evaluateGeneratedQuiz({ id: 25 }, [{ ...PDF_QUIZ, questionCount: 0 }]).ok, false);
});

test('서버가 돌려준 실패 사유를 그대로 보여준다', () => {
  const error = { response: { status: 409, data: { status: 409, message: 'PDF에서 텍스트를 추출하지 못했습니다.' } } };
  assert.equal(serverReasonOf(error), 'PDF에서 텍스트를 추출하지 못했습니다.');
  assert.equal(
    describeQuizGenerationFailure(serverReasonOf(error)),
    '퀴즈를 만들지 못했습니다. PDF에서 텍스트를 추출하지 못했습니다.'
  );
  assert.equal(serverReasonOf({ message: 'Network Error' }), null);
});
