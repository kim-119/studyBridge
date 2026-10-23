import { cleanLearningOrNull } from '../../../utils/learningContent.js';

export const PLANNER_TYPE = {
  USER: 'USER',
  ROADMAP: 'ROADMAP',
};

export const DAY_OF_WEEK_OPTIONS = ['일', '월', '화', '수', '목', '금', '토'];

export const STUDY_TYPE_OPTIONS = ['강의 복습', '과제', '시험 준비', '팀플', '프로젝트', '발표 준비', '개인 공부'];

export const PRIORITY_OPTIONS = ['낮음', '보통', '높음', '긴급'];

export const DEFAULT_PLANNER_TITLE = '공부 플래너';

export const TIMETABLE_START_HOUR = 6;
export const TIMETABLE_END_HOUR = 23;
export const SLOTS_PER_HOUR = 6;
export const MINUTES_PER_SLOT = 10;

const ROADMAP_TITLE_PATTERN = /^\s*(\[로드맵\s*\d+\s*주차\s*\d+\s*일\])\s*(.*)$/;

function padTwo(value) {
  return String(value).padStart(2, '0');
}

export function localIsoDate(date = new Date()) {
  return `${date.getFullYear()}-${padTwo(date.getMonth() + 1)}-${padTwo(date.getDate())}`;
}

export function dayOfWeekOf(isoDate) {
  if (!isoDate) return '';
  const [year, month, day] = isoDate.split('-').map(Number);
  if (!year || !month || !day) return '';
  return DAY_OF_WEEK_OPTIONS[new Date(year, month - 1, day).getDay()];
}

function plannerDateOf(response) {
  if (response?.year && response?.month && response?.day) {
    return `${response.year}-${padTwo(response.month)}-${padTwo(response.day)}`;
  }
  return response?.plannerDate ? String(response.plannerDate).slice(0, 10) : '';
}

export function resolvePlannerType(response) {
  if (!response) return PLANNER_TYPE.USER;
  if (response.plannerType === PLANNER_TYPE.ROADMAP || response.plannerType === PLANNER_TYPE.USER) {
    return response.plannerType;
  }
  if (response.sourceType || response.sourceRoadmapId) return PLANNER_TYPE.ROADMAP;
  return PLANNER_TYPE.USER;
}

export function splitRoadmapTitle(title) {
  const match = typeof title === 'string' ? title.match(ROADMAP_TITLE_PATTERN) : null;
  if (!match) return { prefix: null, topic: title };

  return {
    prefix: match[1].replace(/^\[|\]$/g, ''),
    topic: cleanLearningOrNull(match[2].trim()) || '학습 계획',
  };
}

export function plannerDisplayTitle(response) {
  const rawTitle = String(response?.title || '').trim();
  const looksValid = rawTitle && !/^\d+$/.test(rawTitle) && rawTitle.length >= 3;

  if (looksValid) return splitRoadmapTitle(rawTitle).topic;

  if (resolvePlannerType(response) === PLANNER_TYPE.ROADMAP) {
    if (response?.roadmapWeek && response?.roadmapDay) {
      return `로드맵 ${response.roadmapWeek}주차 ${response.roadmapDay}일 학습`;
    }
    return '로드맵 학습 계획';
  }

  return '사용자 플래너';
}

export function parseTimeTable(timeTableJson) {
  if (!timeTableJson) return {};

  try {
    const parsed = JSON.parse(timeTableJson);
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

export function isSlotChecked(timeTable, hour, slot) {
  const row = timeTable?.[String(hour)] ?? timeTable?.[hour];
  return Array.isArray(row) ? Boolean(row[slot]) : false;
}

export function countCheckedSlots(timeTable) {
  let checked = 0;

  for (let hour = TIMETABLE_START_HOUR; hour <= TIMETABLE_END_HOUR; hour += 1) {
    for (let slot = 0; slot < SLOTS_PER_HOUR; slot += 1) {
      if (isSlotChecked(timeTable, hour, slot)) checked += 1;
    }
  }

  return checked;
}

export function toggleSlot(timeTable, hour, slot) {
  const key = String(hour);
  const row = Array.isArray(timeTable[key]) ? [...timeTable[key]] : new Array(SLOTS_PER_HOUR).fill(false);

  row[slot] = !row[slot];

  const next = { ...timeTable, [key]: row };
  if (row.every((value) => !value)) delete next[key];

  return next;
}

export function plannedMinutes(timeTable) {
  return countCheckedSlots(timeTable) * MINUTES_PER_SLOT;
}

export function formatMinutes(minutes) {
  if (!minutes) return '0분';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${rest}분`;
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`;
}

export function formatPlannerDate(summary) {
  if (!summary.date) return '날짜 미입력';
  const dottedDate = summary.date.replace(/-/g, '.');
  return summary.dayOfWeek ? `${dottedDate} (${summary.dayOfWeek})` : dottedDate;
}

export function toPlannerSummary(response) {
  const timeTable = parseTimeTable(response?.timeTableJson);

  return {
    id: response?.id,
    title: plannerDisplayTitle(response),
    roadmapLabel: splitRoadmapTitle(String(response?.title || '').trim()).prefix,
    type: resolvePlannerType(response),
    subject: response?.subject || '',
    date: plannerDateOf(response),
    dayOfWeek: response?.dayOfWeek || '',
    term: response?.term || '',
    priority: response?.priority || '',
    studyType: response?.studyType || '',
    goalTime: response?.goalTime || '',
    dDay: response?.dDay || '',
    roadmapWeek: response?.roadmapWeek ?? null,
    roadmapDay: response?.roadmapDay ?? null,
    plannedMinutes: plannedMinutes(timeTable),
  };
}

export function toPlannerDetail(response) {
  const timeTable = parseTimeTable(response?.timeTableJson);

  return {
    ...toPlannerSummary(response),
    content: response?.content || '',
    tmi: response?.tmi || '',
    netStudyTime: response?.netStudyTime || '',
    wakeUpTime: response?.wakeUpTime || '',
    materialId: response?.materialId ?? null,
    sourceType: response?.sourceType || null,
    sourceMaterialId: response?.sourceMaterialId ?? null,
    sourceRoadmapId: response?.sourceRoadmapId ?? null,
    downloadUrl: response?.downloadUrl || null,
    timeTable,
    updatedAt: response?.updatedAt || null,
  };
}

export function createBlankPlannerForm(today = new Date()) {
  return {
    title: DEFAULT_PLANNER_TITLE,
    plannerDate: localIsoDate(today),
    dayOfWeek: DAY_OF_WEEK_OPTIONS[today.getDay()],
    term: '',
    subject: '',
    studyType: '',
    priority: '',
    goalTime: '',
    netStudyTime: '',
    wakeUpTime: '',
    dDay: '',
    content: '',
    tmi: '',
  };
}

export function toPlannerForm(response) {
  const plannerDate = plannerDateOf(response);

  return {
    title: response?.title ?? DEFAULT_PLANNER_TITLE,
    plannerDate,
    dayOfWeek: response?.dayOfWeek || dayOfWeekOf(plannerDate),
    term: response?.term ?? '',
    subject: response?.subject ?? '',
    studyType: response?.studyType ?? '',
    priority: response?.priority ?? '',
    goalTime: response?.goalTime ?? '',
    netStudyTime: response?.netStudyTime ?? '',
    wakeUpTime: response?.wakeUpTime ?? '',
    dDay: response?.dDay ?? '',
    content: response?.content ?? '',
    tmi: response?.tmi ?? '',
  };
}

export function toPlannerRequest(form, timeTable, plannerType = PLANNER_TYPE.USER) {
  const plannerDate = form.plannerDate || '';
  const [year, month, day] = plannerDate ? plannerDate.split('-').map(Number) : [];

  return {
    title: form.title?.trim() || '',
    plannerType,
    year: year || null,
    month: month || null,
    day: day || null,
    dayOfWeek: form.dayOfWeek || '',
    plannerDate: plannerDate || null,
    term: form.term ?? '',
    subject: form.subject ?? '',
    studyType: form.studyType ?? '',
    priority: form.priority ?? '',
    goalTime: form.goalTime ?? '',
    netStudyTime: form.netStudyTime ?? '',
    wakeUpTime: form.wakeUpTime ?? '',
    dDay: form.dDay ?? '',
    content: form.content ?? '',
    tmi: form.tmi ?? '',
    timeTableJson: JSON.stringify(timeTable || {}),
  };
}

export function isTodayPlanner(planner, today = new Date()) {
  if (!planner.date) return false;
  return planner.date === localIsoDate(today);
}

export function splitPlannersByType(summaries) {
  return {
    [PLANNER_TYPE.ROADMAP]: summaries.filter((planner) => planner.type === PLANNER_TYPE.ROADMAP),
    [PLANNER_TYPE.USER]: summaries.filter((planner) => planner.type === PLANNER_TYPE.USER),
  };
}

export function summarizePlanners(summaries, today = new Date()) {
  const todayDate = localIsoDate(today);
  const upcoming = summaries
    .filter((planner) => planner.date && planner.date >= todayDate)
    .sort((left, right) => left.date.localeCompare(right.date));
  const subjects = new Set(summaries.map((planner) => planner.subject.trim()).filter(Boolean));

  return {
    total: summaries.length,
    upcomingCount: upcoming.length,
    upcoming: upcoming.slice(0, 3),
    subjectCount: subjects.size,
  };
}

export function findLinkedSchedule(todos, plannerId) {
  const list = Array.isArray(todos) ? todos : [];
  return (
    list.find(
      (todo) => todo.sourceType === 'PLANNER' && String(todo.sourceId ?? '') === String(plannerId)
    ) || null
  );
}
