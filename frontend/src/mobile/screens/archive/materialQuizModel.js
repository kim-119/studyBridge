export const QUESTION_OUTCOME = {
  CORRECT: 'correct',
  WRONG: 'wrong',
  UNANSWERED: 'unanswered',
};

function fallbackQuestionId(quiz, index) {
  return `q${quiz?.quizId ?? 0}-${index + 1}`;
}

function toPublicOption(option, optionIndex) {
  const fallbackOptionId = `o${optionIndex + 1}`;
  if (typeof option === 'string') return { optionId: fallbackOptionId, text: option };
  return { optionId: option?.optionId || fallbackOptionId, text: option?.text ?? '' };
}

export function toPublicQuestions(quiz) {
  const questions = Array.isArray(quiz?.questions) ? quiz.questions : [];

  return questions.map((question, index) => ({
    questionId: question.questionId || fallbackQuestionId(quiz, index),
    index: typeof question.index === 'number' ? question.index : index,
    stem: question.question || `문항 ${index + 1}`,
    options: (Array.isArray(question.options) ? question.options : []).map(toPublicOption),
    gradable: question.gradable !== false,
  }));
}

export function isQuizFailed(quiz) {
  return quiz?.success === false || String(quiz?.status || '').toUpperCase() === 'FAILED';
}

export function toSubmissionAnswers(questions, selections) {
  return questions.map((question) => {
    const selectedOptionId = selections[question.questionId];
    return { questionId: question.questionId, selectedOptionIds: selectedOptionId ? [selectedOptionId] : [] };
  });
}

export function hasAnySelection(answers) {
  return answers.some((answer) => answer.selectedOptionIds.length > 0);
}

export function resultsByQuestionId(result) {
  const results = Array.isArray(result?.results) ? result.results : [];
  return Object.fromEntries(results.map((entry) => [entry.questionId, entry]));
}

export function outcomeOf(questionResult) {
  if (!questionResult || !questionResult.answered) return QUESTION_OUTCOME.UNANSWERED;
  return questionResult.correct === true ? QUESTION_OUTCOME.CORRECT : QUESTION_OUTCOME.WRONG;
}

export function firstOptionId(optionIds) {
  return Array.isArray(optionIds) && optionIds.length > 0 ? optionIds[0] : null;
}

export function selectionsFromResult(result) {
  const selections = {};
  (Array.isArray(result?.results) ? result.results : []).forEach((entry) => {
    const selectedOptionId = firstOptionId(entry.selectedOptionIds);
    if (selectedOptionId) selections[entry.questionId] = selectedOptionId;
  });
  return selections;
}

export function countOutcomes(questions, result) {
  const byQuestionId = resultsByQuestionId(result);
  const outcomes = questions.map((question) => outcomeOf(byQuestionId[question.questionId]));
  const countOf = (outcome) => outcomes.filter((value) => value === outcome).length;

  return {
    correct: countOf(QUESTION_OUTCOME.CORRECT),
    wrong: countOf(QUESTION_OUTCOME.WRONG),
    unanswered: countOf(QUESTION_OUTCOME.UNANSWERED),
  };
}

export function needsReviewNote(outcomeCounts) {
  return outcomeCounts.wrong + outcomeCounts.unanswered > 0;
}

export function toReviewNoteAnswers(questions, selections) {
  const answers = {};
  questions.forEach((question) => {
    const optionIndex = question.options.findIndex((option) => option.optionId === selections[question.questionId]);
    if (optionIndex >= 0) answers[String(question.index)] = optionIndex;
  });
  return answers;
}
