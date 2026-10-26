function parseMaybeJson(value, fallback) {
  if (typeof value !== 'string') return value ?? fallback;

  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
}

function rawQuestionsOf(quiz) {
  if (Array.isArray(quiz?.quizzes) && quiz.quizzes.length > 0) return quiz.quizzes;

  const parsed = parseMaybeJson(quiz?.quizData, []);
  if (Array.isArray(parsed)) return parsed;
  if (Array.isArray(parsed?.quizzes)) return parsed.quizzes;
  if (Array.isArray(parsed?.questions)) return parsed.questions;

  return [];
}

function optionsOf(question) {
  const raw = question.options || question.choices || question.answers;
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === 'object') return Object.values(raw);
  return [];
}

function optionLabel(option) {
  if (typeof option === 'string') return option;
  return option?.text ?? option?.label ?? String(option);
}

function answerIndexOf(question, options) {
  const numericAnswer = [
    question.answerIndex,
    question.correctAnswer,
    question.correct_answer,
    question.answer,
  ].find((value) => typeof value === 'number');

  if (typeof numericAnswer === 'number') return numericAnswer;

  const labels = options.map(optionLabel);
  const candidate = question.answer ?? question.correctAnswer ?? question.correct_answer;

  if (typeof candidate === 'string') {
    const found = labels.indexOf(candidate);
    if (found >= 0) return found;

    const numeric = Number(candidate);
    if (Number.isInteger(numeric)) return numeric;
  }

  return 0;
}

export function toQuizQuestions(quiz) {
  return rawQuestionsOf(quiz).map((question, index) => {
    const options = optionsOf(question).map(optionLabel);

    return {
      id: `${index}-${question.question || question.stem || question.title || index}`,
      stem: question.question || question.stem || question.title || `문항 ${index + 1}`,
      options,
      answerIndex: answerIndexOf(question, optionsOf(question)),
      explanation: question.explanation || '',
    };
  });
}

export function gradeQuiz(questions, selections) {
  const answered = questions.filter((_, index) => selections[index] != null).length;
  const correct = questions.filter((question, index) => selections[index] === question.answerIndex).length;

  return { correct, answered, total: questions.length };
}

export function toRetryResults(questions, selections) {
  return questions.map((question, index) => ({
    questionIndex: index,
    question: question.stem,
    selectedIndex: selections[index] ?? null,
    answerIndex: question.answerIndex,
    correct: selections[index] === question.answerIndex,
  }));
}

export const QUESTION_OUTCOME = {
  CORRECT: 'correct',
  WRONG: 'wrong',
  UNANSWERED: 'unanswered',
};

export function questionOutcome(question, selectedIndex) {
  if (selectedIndex == null) return QUESTION_OUTCOME.UNANSWERED;
  if (selectedIndex === question.answerIndex) return QUESTION_OUTCOME.CORRECT;
  return QUESTION_OUTCOME.WRONG;
}

export function summarizeSubmission(questions, selections) {
  const outcomes = questions.map((question, index) => questionOutcome(question, selections[index]));
  const countOf = (outcome) => outcomes.filter((value) => value === outcome).length;

  return {
    total: questions.length,
    correct: countOf(QUESTION_OUTCOME.CORRECT),
    wrong: countOf(QUESTION_OUTCOME.WRONG),
    unanswered: countOf(QUESTION_OUTCOME.UNANSWERED),
  };
}

export function needsReviewNote(submission) {
  return submission.wrong + submission.unanswered > 0;
}

export function toReviewNoteAnswers(selections) {
  return Object.fromEntries(
    Object.entries(selections)
      .filter(([, optionIndex]) => Number.isInteger(optionIndex))
      .map(([questionIndex, optionIndex]) => [String(questionIndex), optionIndex])
  );
}

function createdTime(quiz) {
  const time = quiz?.createdAt ? new Date(quiz.createdAt).getTime() : 0;
  return Number.isNaN(time) ? 0 : time;
}

export function newestQuizzesFirst(quizzes) {
  const list = Array.isArray(quizzes) ? [...quizzes] : [];
  return list.sort((left, right) => {
    const byTime = createdTime(right) - createdTime(left);
    if (byTime !== 0) return byTime;
    return Number(right?.quizId ?? 0) - Number(left?.quizId ?? 0);
  });
}
