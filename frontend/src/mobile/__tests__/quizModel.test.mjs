// 실행: node --test frontend/src/mobile/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { toQuizQuestions } from '../screens/archive/quizModel.js';

test('서버가 내려주는 0-based answer 를 그대로 정답 인덱스로 쓴다', () => {
  const quiz = {
    quizzes: [
      { question: 'TCP 혼잡제어의 목적은?', options: ['A', 'B', 'C', 'D'], answer: 2 },
    ],
  };

  const [question] = toQuizQuestions(quiz);
  assert.equal(question.answerIndex, 2);
  assert.equal(question.options[question.answerIndex], 'C');
});

test('answerIndex 가 있으면 answer 보다 우선한다', () => {
  const [question] = toQuizQuestions({
    quizzes: [{ question: 'Q', options: ['A', 'B'], answer: 0, answerIndex: 1 }],
  });

  assert.equal(question.answerIndex, 1);
});

test('answer 가 보기 문자열이면 위치를 찾아 인덱스로 바꾼다', () => {
  const [question] = toQuizQuestions({
    quizzes: [{ question: 'Q', options: ['가', '나', '다'], answer: '다' }],
  });

  assert.equal(question.answerIndex, 2);
});

test('quizData 문자열에 담긴 퀴즈도 파싱한다', () => {
  const questions = toQuizQuestions({
    quizData: JSON.stringify([{ question: 'Q1', choices: ['A', 'B'], correct_answer: 1 }]),
  });

  assert.equal(questions.length, 1);
  assert.equal(questions[0].answerIndex, 1);
});

test('퀴즈가 없으면 빈 배열을 돌려준다', () => {
  assert.deepEqual(toQuizQuestions(null), []);
  assert.deepEqual(toQuizQuestions({ quizData: 'not json' }), []);
});
