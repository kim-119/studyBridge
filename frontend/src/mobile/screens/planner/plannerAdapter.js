export const PLANNER_TYPE = {
  USER: 'USER',
  ROADMAP: 'ROADMAP',
};

export const PRIORITY_OPTIONS = ['낮음', '보통', '높음', '긴급'];

export const STUDY_TYPE_OPTIONS = ['강의', '과제', '시험', '복습', '프로젝트'];

// 시간표 계약: { "<시>": [10분 단위 6칸 boolean] }. 서버 PDF 렌더러와 동일하게 06~23시를 다룬다.
export const TIMETABLE_START_HOUR = 6;
export const TIMETABLE_END_HOUR = 23;
export const SLOTS_PER_HOUR = 6;
export const MINUTES_PER_SLOT = 10;

function toIsoDate(value) {
  if (!value) return '';
  return String(value).slice(0, 10);
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

export function toPlannerSummary(response) {
  const timeTable = parseTimeTable(response?.timeTableJson);

  return {
    id: response?.id,
    title: response?.title || '제목 없는 플래너',
    type: response?.plannerType || PLANNER_TYPE.USER,
    subject: response?.subject || '',
    date: toIsoDate(response?.plannerDate),
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
    timeTable,
    updatedAt: response?.updatedAt || null,
  };
}

export function toPlannerForm(detail) {
  return {
    title: detail?.title || '',
    subject: detail?.subject || '',
    term: detail?.term || '',
    studyType: detail?.studyType || STUDY_TYPE_OPTIONS[0],
    priority: detail?.priority || PRIORITY_OPTIONS[1],
    goalTime: detail?.goalTime || '',
    date: detail?.date || '',
    content: detail?.content || '',
  };
}

export function toPlannerRequest(form, timeTable) {
  const plannerDate = form.date || '';
  const [year, month, day] = plannerDate ? plannerDate.split('-').map(Number) : [];

  return {
    title: form.title?.trim() || '',
    plannerType: PLANNER_TYPE.USER,
    subject: form.subject?.trim() || '',
    term: form.term?.trim() || '',
    studyType: form.studyType || '',
    priority: form.priority || '',
    goalTime: form.goalTime?.trim() || '',
    content: form.content?.trim() || '',
    plannerDate: plannerDate || null,
    year: year || null,
    month: month || null,
    day: day || null,
    timeTableJson: timeTable && Object.keys(timeTable).length > 0 ? JSON.stringify(timeTable) : null,
  };
}

export function isTodayPlanner(planner, today = new Date()) {
  if (!planner.date) return false;
  return planner.date === today.toISOString().slice(0, 10);
}

export function findLinkedSchedule(todos, plannerId) {
  const list = Array.isArray(todos) ? todos : [];
  return (
    list.find(
      (todo) => todo.sourceType === 'PLANNER' && String(todo.sourceId ?? '') === String(plannerId)
    ) || null
  );
}
