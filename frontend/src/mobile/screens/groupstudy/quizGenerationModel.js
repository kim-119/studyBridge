export const QUESTION_COUNT_OPTIONS = [3, 5, 10];
export const TIME_LIMIT_OPTIONS = [15, 30, 60];
export const DEFAULT_QUIZ_OPTIONS = { questionCount: 5, timeLimitSeconds: 15 };

const PLACEHOLDER_TITLE_MARKER = '기본 안내형';

export function quizIdOf(quiz) {
  return quiz?.id ?? quiz?.quizId ?? null;
}

function findListedQuiz(quizzes, quizId) {
  return (Array.isArray(quizzes) ? quizzes : []).find((quiz) => String(quizIdOf(quiz)) === String(quizId)) || null;
}

export function evaluateGeneratedQuiz(response, quizzes) {
  const quizId = quizIdOf(response);
  if (quizId == null) {
    return { ok: false, reason: '서버가 생성된 퀴즈 정보를 돌려주지 않았습니다.' };
  }

  const listed = findListedQuiz(quizzes, quizId);
  const title = listed?.title || response.title || '';
  if (title.includes(PLACEHOLDER_TITLE_MARKER)) {
    return { ok: false, reason: 'PDF 내용과 무관한 기본 문제가 생성되어 사용할 수 없습니다.' };
  }

  if (!listed) {
    return { ok: false, reason: '생성된 퀴즈가 퀴즈 목록에 없습니다. 목록을 새로고침해주세요.' };
  }

  const questionCount = Math.max(Number(response.questionCount) || 0, Number(listed.questionCount) || 0);
  if (questionCount === 0) {
    return { ok: false, reason: '생성된 퀴즈에 문항이 없습니다.' };
  }

  return { ok: true, quiz: listed, title, questionCount };
}

export function serverReasonOf(error) {
  const data = error?.response?.data;
  if (typeof data === 'string' && data.trim()) return data.trim();
  return data?.message || data?.error || null;
}

export function describeQuizGenerationFailure(reason) {
  return `퀴즈를 만들지 못했습니다. ${reason}`;
}

export function describeQuizGenerationSuccess({ title, questionCount }) {
  return `퀴즈를 만들었습니다: ${title || '그룹 퀴즈'} (${questionCount}문항)`;
}
