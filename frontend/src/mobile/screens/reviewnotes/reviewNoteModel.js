import { sanitizeMarkdownText } from '../../../utils/markdown.js';

export const DIFFICULTY_LABEL = { easy: '쉬움', medium: '보통', normal: '보통', hard: '어려움' };

export const VARIANT_LEVELS = [
  { label: '하', value: 'easy' },
  { label: '중', value: 'normal' },
  { label: '상', value: 'hard' },
];

export const VARIANT_COUNTS = [1, 2, 3, 4, 5];

export const DEFAULT_VARIANT_SETTINGS = { wrongQuestionId: 1, difficulty: 'normal', count: 3 };

export class VariantGenerationError extends Error {
  constructor(message) {
    super(message);
    this.name = 'VariantGenerationError';
  }
}

export class ReviewScheduleError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ReviewScheduleError';
  }
}

export function cleanText(value) {
  return sanitizeMarkdownText(value ?? '');
}

export function difficultyLabel(difficulty) {
  return DIFFICULTY_LABEL[difficulty] || difficulty || '';
}

export function wrongQuestionNumbers(note) {
  const count = Math.max(1, Number(note?.wrongCount) || 1);
  return Array.from({ length: count }, (_, index) => index + 1);
}

export function buildVariantRequest({ wrongQuestionId, difficulty, count }) {
  return {
    wrongQuestionId: Number(wrongQuestionId) || 1,
    difficulty,
    count: Number(count) || 1,
  };
}

function rawSimilarQuestions(response) {
  return (
    response?.similarQuestions ??
    response?.possibleSimilarQuestions ??
    response?.questions ??
    response?.data?.similarQuestions ??
    response?.data?.questions ??
    response?.result?.similarQuestions ??
    response?.result?.questions ??
    []
  );
}

function toSimilarQuestion(question, index) {
  const choices = question?.choices || question?.options || [];

  const serverId = question?.id ?? question?.questionId ?? null;

  return {
    id: String(serverId ?? `sq-${index}`),
    sourceId: serverId == null ? null : String(serverId),
    number: index + 1,
    question: question?.question ?? question?.prompt ?? question?.text ?? '',
    choices: Array.isArray(choices) ? choices : [],
    answer: question?.answer ?? question?.correctAnswer ?? question?.correct_answer ?? '',
    explanation: question?.explanation ?? question?.rationale ?? '',
    difficulty: question?.difficulty ?? '',
    variationPoint:
      question?.variationPoint ??
      question?.variation_point ??
      question?.changePoint ??
      question?.change_point ??
      '',
  };
}

export function normalizeSimilarQuestions(response) {
  const raw = rawSimilarQuestions(response);
  const list = Array.isArray(raw) ? raw : raw && typeof raw === 'object' ? [raw] : [];
  return list.map(toSimilarQuestion);
}

export function readVariantResponse(response) {
  if (response && response.success === false) {
    throw new VariantGenerationError(
      response.message || response.error || '유사문제 생성에 실패했습니다. 잠시 후 다시 시도해주세요.'
    );
  }

  return {
    questions: normalizeSimilarQuestions(response),
    usedFallback: Boolean(response?.usedFallback),
  };
}

export function isCorrectChoice(choiceText, choiceIndex, answer) {
  const expected = String(answer ?? '').trim();
  if (!expected) return false;
  if (String(choiceText).trim() === expected) return true;
  if (String(choiceIndex) === expected) return true;
  return String(choiceIndex + 1) === expected;
}

export function correctChoiceText(question) {
  const found = question.choices.find((choice, index) => isCorrectChoice(choice, index, question.answer));
  return found ?? question.answer;
}

export function similarQuestionStatus(question, pickedIndex, isSubmitted) {
  if (!isSubmitted) return '풀이 전';
  const picked = question.choices[pickedIndex];
  if (picked != null && isCorrectChoice(picked, pickedIndex, question.answer)) return '정답';
  return '오답';
}

export function reviewScheduleTitle(note) {
  return `[복습] ${note?.sourceName || note?.title || '오답'} 오답 복습`;
}

export function describeScheduleResult(response) {
  if (!response || response.todoId == null) {
    throw new ReviewScheduleError('등록 결과를 확인하지 못했습니다.');
  }

  return response.alreadyRegistered
    ? `${response.scheduledDate} 주간 일정에 이미 등록되어 있습니다.`
    : `${response.scheduledDate} 주간 일정에 복습이 등록되었습니다.`;
}

export function registeredScheduleMessage(note) {
  if (!note?.reviewScheduled) return '';
  return `${note.reviewScheduledDate || note.recommendedReviewDate} 주간 일정에 이미 등록되어 있습니다.`;
}

export function reviewDateBadges(note) {
  if (!note?.recommendedReviewDate) return [];

  const badges = [];
  if (note.reviewCompleted) badges.push({ key: 'completed', label: '복습 완료', tone: 'done' });
  else if (note.reviewNeeded) badges.push({ key: 'needed', label: '복습 필요', tone: 'alert' });
  if (note.reviewScheduled && !note.reviewCompleted) {
    badges.push({ key: 'scheduled', label: '일정 등록됨', tone: 'info' });
  }
  return badges;
}

export function reviewTargetCount(note) {
  return note?.reviewCount ?? (note?.wrongCount ?? 0) + (note?.unansweredCount ?? 0);
}

export function explanationSummary(detail) {
  return detail?.aiExplanationSummary || detail?.overallFeedback || '';
}

export function formatNoteDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
}

export function buildRetrySubmission(questions, selections, lockedIndexes) {
  return questions
    .map((question, index) => {
      if (selections[index] == null || lockedIndexes.has(index)) return null;
      return { index: index + 1, userAnswer: question.options[selections[index]] ?? '' };
    })
    .filter(Boolean);
}
