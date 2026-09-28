import { aiFailureMessage } from './aiResponseModel.js';
import { isQuizFailed, toPublicQuestions } from './materialQuizModel.js';

export const MIN_QUESTION_COUNT = 5;
export const MAX_QUESTION_COUNT = 20;
export const DEFAULT_QUESTION_COUNT = 10;
export const GENERATING_MESSAGE = '퀴즈를 생성하고 있습니다.';

const EMPTY_QUIZ_MESSAGE = 'AI 문제 응답이 비어 있습니다. 다시 생성해주세요.';

export class QuizGenerationFailure extends Error {
  constructor(message, response = null) {
    super(message);
    this.name = 'QuizGenerationFailure';
    this.userMessage = message;
    this.response = response;
  }
}

export function materialQuizTaskKey(materialId) {
  return `material-quiz:${materialId}`;
}

export function clampQuestionCount(value) {
  const count = Number.parseInt(value, 10);
  if (Number.isNaN(count)) return DEFAULT_QUESTION_COUNT;
  return Math.min(MAX_QUESTION_COUNT, Math.max(MIN_QUESTION_COUNT, count));
}

export function buildMaterialQuizRequest({ difficulty, questionCount }) {
  return {
    difficulty,
    questionCount: clampQuestionCount(questionCount),
    pageRange: '전체',
    sourceMode: 'PDF_BASED',
  };
}

export function assertQuizGenerated(response) {
  if (isQuizFailed(response)) throw new QuizGenerationFailure(aiFailureMessage(response), response);
  if (toPublicQuestions(response).length === 0) throw new QuizGenerationFailure(EMPTY_QUIZ_MESSAGE, response);
  return response;
}

export function startMaterialQuizGeneration(store, { materialId, options, generateQuiz }) {
  const request = buildMaterialQuizRequest(options);
  return store.run(materialQuizTaskKey(materialId), async () =>
    assertQuizGenerated(await generateQuiz(materialId, request))
  );
}

export function mergeGeneratedQuiz(quizzes, createdQuiz) {
  const list = Array.isArray(quizzes) ? quizzes : [];
  if (!createdQuiz || createdQuiz.quizId == null) return list;
  return [createdQuiz, ...list.filter((quiz) => quiz.quizId !== createdQuiz.quizId)];
}

export function describeServerScore(result) {
  if (!result || typeof result.score !== 'number') return null;
  return `채점 결과 ${result.score}점 (${result.correctCount ?? 0}/${result.totalQuestions ?? 0})`;
}
