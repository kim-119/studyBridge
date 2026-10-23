import test from 'node:test';
import assert from 'node:assert/strict';
import {
  QUESTION_OUTCOME,
  countOutcomes,
  hasAnySelection,
  isQuizFailed,
  needsReviewNote,
  outcomeOf,
  selectionsFromResult,
  toPublicQuestions,
  toReviewNoteAnswers,
  toSubmissionAnswers,
} from '../screens/archive/materialQuizModel.js';

const ANSWER_KEYS = ['correctAnswer', 'answerIndex', 'correctOptionIds', 'explanation', 'wrongExplanations', 'sourceTrace', 'quizData'];

function publicQuiz(questionCount) {
  return {
    quizId: 41,
    questions: Array.from({ length: questionCount }, (_, index) => ({
      questionId: `q41-${index + 1}`,
      index,
      question: `문항 ${index + 1}`,
      options: [
        { optionId: 'o1', text: '가' },
        { optionId: 'o2', text: '나' },
        { optionId: 'o3', text: '다' },
        { optionId: 'o4', text: '라' },
      ],
      gradable: true,
    })),
  };
}

function serverResult(correctFlags) {
  const correctCount = correctFlags.filter(Boolean).length;
  return {
    quizId: 41,
    score: Math.round((correctCount / correctFlags.length) * 100),
    correctCount,
    totalQuestions: correctFlags.length,
    results: correctFlags.map((isCorrect, index) => ({
      questionId: `q41-${index + 1}`,
      index,
      answered: true,
      correct: isCorrect,
      selectedOptionIds: [isCorrect ? 'o1' : 'o2'],
      correctOptionIds: ['o1'],
      explanation: '해설',
    })),
  };
}

test('공개 문항 변환 결과에는 정답 키가 없다', () => {
  const leakyQuiz = {
    quizId: 7,
    quizData: '[{"answer":1}]',
    questions: [
      {
        questionId: 'q7-1',
        question: 'Q',
        options: [{ optionId: 'o1', text: 'A' }, { optionId: 'o2', text: 'B' }],
        answerIndex: 1,
        correctAnswer: 'B',
        correctOptionIds: ['o2'],
        explanation: '정답은 B',
      },
    ],
  };

  const [question] = toPublicQuestions(leakyQuiz);
  ANSWER_KEYS.forEach((key) => assert.equal(key in question, false, key));
  question.options.forEach((option) => assert.deepEqual(Object.keys(option).sort(), ['optionId', 'text']));
});

test('문자열 보기와 id 없는 문항은 서버와 같은 규칙의 id 를 받는다', () => {
  const [question] = toPublicQuestions({ quizId: 9, questions: [{ question: 'Q', options: ['A', 'B'] }] });

  assert.equal(question.questionId, 'q9-1');
  assert.deepEqual(question.options, [
    { optionId: 'o1', text: 'A' },
    { optionId: 'o2', text: 'B' },
  ]);
});

test('제출 payload 는 questionId 와 selectedOptionIds 만 담는다', () => {
  const questions = toPublicQuestions(publicQuiz(2));
  const answers = toSubmissionAnswers(questions, { 'q41-1': 'o3' });

  assert.deepEqual(answers, [
    { questionId: 'q41-1', selectedOptionIds: ['o3'] },
    { questionId: 'q41-2', selectedOptionIds: [] },
  ]);
  answers.forEach((answer) => assert.deepEqual(Object.keys(answer).sort(), ['questionId', 'selectedOptionIds']));
  assert.equal(hasAnySelection(answers), true);
  assert.equal(hasAnySelection(toSubmissionAnswers(questions, {})), false);
});

test('5문제 중 4개 정답이면 서버 점수 80 과 서버 판정을 그대로 쓴다', () => {
  const questions = toPublicQuestions(publicQuiz(5));
  const result = serverResult([true, true, true, true, false]);

  assert.equal(result.score, 80);
  assert.equal(result.correctCount, 4);
  assert.equal(result.totalQuestions, 5);
  assert.deepEqual(countOutcomes(questions, result), { correct: 4, wrong: 1, unanswered: 0 });
  assert.equal(needsReviewNote(countOutcomes(questions, result)), true);
});

test('서버 결과가 없는 문항은 미응답으로 본다', () => {
  assert.equal(outcomeOf(undefined), QUESTION_OUTCOME.UNANSWERED);
  assert.equal(outcomeOf({ answered: false }), QUESTION_OUTCOME.UNANSWERED);
  assert.equal(outcomeOf({ answered: true, correct: false }), QUESTION_OUTCOME.WRONG);
  assert.equal(outcomeOf({ answered: true, correct: true }), QUESTION_OUTCOME.CORRECT);
});

test('재진입 시 서버 lastResult 로 선택 상태를 복원한다', () => {
  assert.deepEqual(selectionsFromResult(serverResult([true, false])), { 'q41-1': 'o1', 'q41-2': 'o2' });
  assert.deepEqual(selectionsFromResult(null), {});
});

test('오답노트 답안은 서버 문항 index 와 보기 위치로 변환한다', () => {
  const questions = toPublicQuestions(publicQuiz(3));

  assert.deepEqual(toReviewNoteAnswers(questions, { 'q41-1': 'o2', 'q41-3': 'o4' }), { 0: 1, 2: 3 });
});

test('success:false 또는 status FAILED 인 퀴즈는 실패로 본다', () => {
  assert.equal(isQuizFailed({ success: false }), true);
  assert.equal(isQuizFailed({ status: 'failed' }), true);
  assert.equal(isQuizFailed({ status: 'OK', success: true }), false);
  assert.equal(isQuizFailed(null), false);
});
