import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createBackgroundTaskStore } from '../data/backgroundTasks.js';
import {
  assertQuizGenerated,
  buildMaterialQuizRequest,
  describeServerScore,
  mergeGeneratedQuiz,
  startMaterialQuizGeneration,
} from '../screens/archive/materialQuizGeneration.js';
import { toPublicQuestions, toSubmissionAnswers } from '../screens/archive/materialQuizModel.js';

const QUIZ_TAB_SOURCE = readFileSync(new URL('../screens/archive/tabs/QuizTab.jsx', import.meta.url), 'utf8');

function serverQuiz() {
  return {
    quizId: 90,
    materialId: 3,
    success: true,
    status: 'OK',
    questions: [
      {
        questionId: 'q_1',
        index: 0,
        question: '프로세스의 정의는?',
        options: [
          { optionId: 'o1', text: '실행 중인 프로그램' },
          { optionId: 'o2', text: '저장된 파일' },
        ],
        correctAnswer: 'o1',
        answerIndex: 0,
        correctOptionIds: ['o1'],
        explanation: '정답 해설',
      },
    ],
  };
}

test('T31 퀴즈 생성 버튼은 자료 ID 로 생성 API 를 한 번 호출한다', async () => {
  const calls = [];
  const store = createBackgroundTaskStore();

  await startMaterialQuizGeneration(store, {
    materialId: 3,
    options: { difficulty: '어려움', questionCount: 5 },
    generateQuiz: async (materialId, request) => {
      calls.push({ materialId, request });
      return serverQuiz();
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].materialId, 3);
  assert.match(QUIZ_TAB_SOURCE, /onClick=\{\(\) => onGenerate\(\{ difficulty, questionCount \}\)\}/);
  assert.match(QUIZ_TAB_SOURCE, /generateQuiz: materialService\.generateQuiz/);
});

test('T32 요청 본문은 웹과 같은 계약(난이도·5~20 문항·전체 범위·PDF_BASED)을 따른다', () => {
  assert.deepEqual(buildMaterialQuizRequest({ difficulty: '보통', questionCount: '15' }), {
    difficulty: '보통',
    questionCount: 15,
    pageRange: '전체',
    sourceMode: 'PDF_BASED',
  });
  assert.equal(buildMaterialQuizRequest({ difficulty: '쉬움', questionCount: 2 }).questionCount, 5);
  assert.equal(buildMaterialQuizRequest({ difficulty: '쉬움', questionCount: 40 }).questionCount, 20);
  assert.equal(buildMaterialQuizRequest({ difficulty: '쉬움', questionCount: '' }).questionCount, 10);
});

test('T33 생성 응답을 목록 맨 앞에 넣고 문항을 렌더링 가능한 형태로 만든다', () => {
  const created = assertQuizGenerated(serverQuiz());
  const list = mergeGeneratedQuiz([{ quizId: 10 }, { quizId: 90, stale: true }], created);
  const questions = toPublicQuestions(list[0]);

  assert.deepEqual(list.map((quiz) => quiz.quizId), [90, 10]);
  assert.equal(questions[0].stem, '프로세스의 정의는?');
  assert.deepEqual(questions[0].options.map((option) => option.text), ['실행 중인 프로그램', '저장된 파일']);
  assert.throws(() => assertQuizGenerated({ quizId: 1, questions: [] }), /비어 있습니다/);
  assert.throws(() => assertQuizGenerated({ success: false, message: '자료 텍스트 없음' }), /자료 텍스트 없음/);
});

test('T34 초기 렌더링 데이터에는 정답·해설 필드가 없다', () => {
  const [question] = toPublicQuestions(serverQuiz());
  const serialized = JSON.stringify(question);

  assert.deepEqual(Object.keys(question).sort(), ['gradable', 'index', 'options', 'questionId', 'stem']);
  ['correctAnswer', 'answerIndex', 'correctOptionIds', 'explanation'].forEach((field) => {
    assert.equal(serialized.includes(field), false, field);
  });
});

test('T35 제출은 questionId 와 selectedOptionIds 만 보낸다', () => {
  const questions = toPublicQuestions(serverQuiz());
  const answers = toSubmissionAnswers(questions, { q_1: 'o2' });

  assert.deepEqual(answers, [{ questionId: 'q_1', selectedOptionIds: ['o2'] }]);
  assert.deepEqual(toSubmissionAnswers(questions, {}), [{ questionId: 'q_1', selectedOptionIds: [] }]);
});

test('T36 점수는 서버 응답 값을 그대로 표시한다', () => {
  assert.equal(
    describeServerScore({ score: 67, correctCount: 2, totalQuestions: 3 }),
    '채점 결과 67점 (2/3)'
  );
  assert.equal(describeServerScore({ correctCount: 3, totalQuestions: 3 }), null);
  assert.match(QUIZ_TAB_SOURCE, /describeServerScore\(result\)/);
  assert.doesNotMatch(QUIZ_TAB_SOURCE, /Math\.round\(/);
});
