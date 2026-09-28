import { similarQuestionStatus } from './reviewNoteModel.js';
import { numberVariantQuestions } from './variantCountModel.js';

export function variantGenerationTaskKey(reviewNoteId) {
  return `review-note-variant:${reviewNoteId}`;
}

export function applyGeneratedResult(session, request, result) {
  const questions = numberVariantQuestions(result.questions);
  return {
    ...session,
    lastRequest: request,
    questions,
    usedFallback: result.usedFallback,
    hasResult: true,
    activeId: questions[0]?.id ?? null,
    answers: {},
    submitted: {},
    completed: false,
  };
}

export function currentIndexOf(session) {
  const index = session.questions.findIndex((question) => question.id === session.activeId);
  return index >= 0 ? index : 0;
}

export function progressOf(session) {
  const total = session.questions.length;
  const currentIndex = currentIndexOf(session);
  const currentQuestion = session.questions[currentIndex] || null;
  const results = session.questions.map((question) =>
    similarQuestionStatus(question, session.answers[question.id], session.submitted[question.id])
  );

  return {
    total,
    currentIndex,
    currentNumber: total === 0 ? 0 : currentIndex + 1,
    currentQuestion,
    isLast: total > 0 && currentIndex === total - 1,
    isCurrentSubmitted: Boolean(currentQuestion && session.submitted[currentQuestion.id]),
    isCompleted: session.completed === true,
    correctCount: results.filter((status) => status === '정답').length,
    submittedCount: results.filter((status) => status !== '풀이 전').length,
  };
}

export function goToNextQuestion(session) {
  const nextQuestion = session.questions[currentIndexOf(session) + 1];
  if (!nextQuestion) return session;
  return { ...session, activeId: nextQuestion.id };
}

export function completeVariantSession(session) {
  if (session.questions.length === 0) return session;
  return { ...session, completed: true };
}

export function restartVariantSession(session) {
  return {
    ...session,
    activeId: session.questions[0]?.id ?? null,
    answers: {},
    submitted: {},
    completed: false,
  };
}
