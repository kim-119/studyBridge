import { cleanLearningOrNull, filterLearningList } from '../../../utils/learningContent.js';

export const ROADMAP_TOTAL_DAYS = 84;

export const ROADMAP_LEVELS = [
  { value: 'beginner', label: '초보자', description: '기본 개념·용어·환경 설정·따라 하기 중심' },
  { value: 'intermediate', label: '중급자', description: '응용·코드 흐름 이해·오류 분석·구조 비교 포함' },
  { value: 'advanced', label: '상급자', description: '고급 개념·설계 판단·테스트·예외 처리·유지보수 관점' },
];

export const DEFAULT_ROADMAP_LEVEL = 'intermediate';

const ROADMAP_ERROR_MESSAGES = {
  PDF_TEXT_EMPTY: 'PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.',
  PDF_TEXT_TOO_SHORT: '문서 텍스트가 너무 짧아 요약 품질이 낮을 수 있습니다.',
  PDF_EXTRACTION_FAILED: 'PDF 텍스트 추출에 실패했습니다.',
  PDF_OCR_REQUIRED: '이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.',
  AI_TIMEOUT: 'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.',
  OLLAMA_UNAVAILABLE: '로컬 AI 모델 연결에 실패했습니다.',
  OPENAI_UNAVAILABLE: 'AI 모델 연결에 실패했습니다.',
  AI_RESPONSE_PARSE_FAILED: 'AI 응답 형식 처리에 실패했습니다. 다시 생성해주세요.',
  ROADMAP_VALIDATE_FAILED: '로드맵 형식 검증에 실패했습니다. 다시 생성해주세요.',
  UNKNOWN_ERROR: 'AI 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.',
};

export const ROADMAP_DAYS_REQUIRED_MESSAGE =
  '84일 로드맵이 필요합니다. 먼저 AI 84일 로드맵을 재생성해주세요.';

function parseMaybeJson(value, fallback) {
  if (value == null) return fallback;
  if (typeof value !== 'string') return value;

  const trimmed = value.trim();
  if (!trimmed) return fallback;

  try {
    return JSON.parse(trimmed);
  } catch {
    return fallback;
  }
}

export function roadmapFailureMessage(roadmap) {
  if (!roadmap || roadmap.success !== false) return null;
  if (roadmap.message) return roadmap.message;
  if (roadmap.errorCode && ROADMAP_ERROR_MESSAGES[roadmap.errorCode]) {
    return ROADMAP_ERROR_MESSAGES[roadmap.errorCode];
  }
  if (roadmap.textStatus?.hasText === false) return ROADMAP_ERROR_MESSAGES.PDF_TEXT_EMPTY;
  if (roadmap.textStatus?.status === 'TOO_SHORT') return ROADMAP_ERROR_MESSAGES.PDF_TEXT_TOO_SHORT;
  return ROADMAP_ERROR_MESSAGES.UNKNOWN_ERROR;
}

export function roadmapUsedServerFallback(roadmap) {
  return Boolean(roadmap?.fallbackUsed || roadmap?.usedFallback || roadmap?.metadata?.usedFallback);
}

export function assertRoadmapSucceeded(roadmap) {
  const failure = roadmapFailureMessage(roadmap);
  if (failure) throw new Error(failure);
  return roadmap;
}

export function rawRoadmapWeeks(roadmap) {
  const source = roadmap?.roadmapData || roadmap;
  const parsed = parseMaybeJson(source, {}) || {};
  const root = parsed.roadmap || parsed.roadmapData?.roadmap || parsed.roadmapData || parsed;
  const weeks = root.weeks || root.steps || parsed.weeks || parsed.steps || [];
  return Array.isArray(weeks) ? weeks : [];
}

function taskText(task) {
  if (typeof task === 'string') return task;
  if (task && typeof task === 'object') return task.title || task.content || task.description || '';
  return String(task ?? '');
}

function weekNumberOf(week, weekPosition) {
  return Number(week.week || week.weekNumber || week.stepOrder || weekPosition + 1);
}

function normalizeDay(day, dayPosition, courseTitle) {
  const dayNumber = dayPosition + 1;

  return {
    dayIndex: Number(day.day_index || dayNumber),
    dayLabel: day.day_label || `${dayNumber}일차`,
    title: cleanLearningOrNull(day.title, courseTitle) || `${dayNumber}일차 학습`,
    objective: cleanLearningOrNull(day.objective, courseTitle) || '',
    coreConcepts: filterLearningList(Array.isArray(day.core_concepts) ? day.core_concepts : [], courseTitle),
    tasks: filterLearningList((Array.isArray(day.tasks) ? day.tasks : []).map(taskText), courseTitle),
    reviewQuestions: filterLearningList(
      Array.isArray(day.review_questions) ? day.review_questions : [],
      courseTitle
    ),
    deliverable: cleanLearningOrNull(day.deliverable, courseTitle) || '',
    checkpoint: cleanLearningOrNull(day.checkpoint, courseTitle) || '',
    completed: Boolean(day.completed),
  };
}

function normalizeLegacyTask(task, weekPosition, taskPosition, courseTitle) {
  const fallbackId = `week-${weekPosition + 1}-task-${taskPosition + 1}`;

  if (typeof task === 'string') {
    return {
      taskId: fallbackId,
      hasServerId: false,
      content: cleanLearningOrNull(task, courseTitle) || task,
      isCompleted: false,
    };
  }

  const rawContent = task.content || task.title || String(task);

  return {
    taskId: task.taskId ?? task.id ?? fallbackId,
    hasServerId: task.taskId != null || task.id != null,
    content: cleanLearningOrNull(rawContent, courseTitle) || rawContent,
    isCompleted: Boolean(task.isCompleted),
  };
}

export function normalizeRoadmapWeeks(roadmap, courseTitle = null) {
  return rawRoadmapWeeks(roadmap).map((week, weekPosition) => {
    const weekNumber = weekNumberOf(week, weekPosition);
    const days = Array.isArray(week.days) ? week.days : [];
    const tasks = Array.isArray(week.tasks) ? week.tasks : [];

    return {
      weekNumber,
      title: cleanLearningOrNull(week.title, courseTitle) || `${weekPosition + 1}주차`,
      description:
        cleanLearningOrNull(
          week.objective || week.goal || week.description || week.week_summary,
          courseTitle
        ) || '',
      weekSummary: cleanLearningOrNull(week.week_summary, courseTitle) || '',
      days: days.map((day, dayPosition) => normalizeDay(day, dayPosition, courseTitle)),
      tasks: tasks.map((task, taskPosition) =>
        normalizeLegacyTask(task, weekPosition, taskPosition, courseTitle)
      ),
    };
  });
}

export function hasDayStructure(weeks) {
  return weeks.some((week) => week.days.length > 0);
}

export function isWeekCompleted(week) {
  if (week.days.length > 0) return week.days.every((day) => day.completed);
  return week.tasks.length > 0 && week.tasks.every((task) => task.isCompleted);
}

export function firstOpenWeekNumber(weeks) {
  if (weeks.length === 0) return null;
  const openWeek = weeks.find((week) => !isWeekCompleted(week));
  return (openWeek || weeks[0]).weekNumber;
}

export function findDay(weeks, weekNumber, dayIndex) {
  const week = weeks.find((candidate) => candidate.weekNumber === weekNumber);
  return week?.days.find((day) => day.dayIndex === dayIndex) || null;
}

export function roadmapProgress(weeks) {
  const usesDays = hasDayStructure(weeks);
  const units = usesDays
    ? weeks.flatMap((week) => week.days).map((day) => day.completed)
    : weeks.flatMap((week) => week.tasks).map((task) => task.isCompleted);

  const total = units.length;
  const done = units.filter(Boolean).length;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

  return {
    done,
    total,
    percent,
    label: usesDays ? `${done}/${total}일` : `${done}/${total}`,
  };
}

export function toggleDayInWeeks(weeks, weekNumber, dayIndex) {
  return weeks.map((week) => {
    if (week.weekNumber !== Number(weekNumber)) return week;

    return {
      ...week,
      days: week.days.map((day) =>
        day.dayIndex === Number(dayIndex) ? { ...day, completed: !day.completed } : day
      ),
    };
  });
}

export function toggleTaskInWeeks(weeks, taskId) {
  return weeks.map((week) => ({
    ...week,
    tasks: week.tasks.map((task) =>
      task.taskId === taskId ? { ...task, isCompleted: !task.isCompleted } : task
    ),
  }));
}

function plannerTaskText(task) {
  if (typeof task === 'string') return task;
  return [task.title, task.description].filter(Boolean).join(': ');
}

function plannerTaskMinutes(task) {
  if (typeof task !== 'object' || task === null) return 0;
  return Number(task.estimated_minutes || task.estimatedMinutes || 0);
}

function toPlannerItem(day, dayPosition, weekNumber) {
  const rawTasks = Array.isArray(day.tasks) ? day.tasks : [];
  const minutes = rawTasks.reduce((total, task) => total + plannerTaskMinutes(task), 0);

  return {
    week: weekNumber,
    dayIndex: Number(day.day_index || dayPosition + 1),
    title: day.title || `${dayPosition + 1}일차 학습`,
    objective: day.objective || '',
    tasks: rawTasks.map(plannerTaskText).filter(Boolean),
    coreConcepts: Array.isArray(day.core_concepts) ? day.core_concepts : [],
    reviewQuestions: Array.isArray(day.review_questions) ? day.review_questions : [],
    checkpoint: day.checkpoint || '',
    deliverable: day.deliverable || '',
    targetMinutes: minutes > 0 ? minutes : null,
  };
}

export function buildPlannerItemsFromRoadmap(roadmap) {
  return rawRoadmapWeeks(roadmap).flatMap((week, weekPosition) => {
    const weekNumber = Number(week.week || week.weekNumber || weekPosition + 1);
    const days = Array.isArray(week.days) ? week.days : [];
    return days.map((day, dayPosition) => toPlannerItem(day, dayPosition, weekNumber));
  });
}

export function canCreatePlanners(roadmap) {
  return buildPlannerItemsFromRoadmap(roadmap).length === ROADMAP_TOTAL_DAYS;
}

export function buildFromRoadmapRequest({ materialId, roadmap, materialTitle, startDate, force }) {
  const items = buildPlannerItemsFromRoadmap(roadmap);
  if (items.length !== ROADMAP_TOTAL_DAYS) throw new Error(ROADMAP_DAYS_REQUIRED_MESSAGE);

  return {
    materialId: Number(materialId),
    roadmapId: roadmap?.roadmapId ?? null,
    sourceTitle: materialTitle || null,
    subject: materialTitle || null,
    startDate,
    force: Boolean(force),
    items,
  };
}

export function roadmapRegenerationTaskKey(materialId) {
  return `roadmap-regenerate:${materialId}`;
}
