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

/**
 * 서버(ai07/material_legacy_routes)는 정답을 0-based 인덱스로 내려준다.
 * answerIndex · answer(number) · answer(문자열이면 options 에서 위치 탐색) 순으로 해석해
 * 데스크톱 parseQuizQuestions 와 같은 0-based 계약으로 정규화한다.
 */
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
