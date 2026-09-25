export const PLANNER_TYPE = {
  USER: 'USER',
  ROADMAP: 'ROADMAP',
};

export const PRIORITY_OPTIONS = ['낮음', '보통', '높음', '긴급'];

export const STUDY_TYPE_OPTIONS = ['강의', '과제', '시험', '복습', '프로젝트'];

function toIsoDate(value) {
  if (!value) return '';
  return String(value).slice(0, 10);
}

function parseTimeTable(timeTableJson) {
  if (!timeTableJson) return [];

  try {
    const parsed = JSON.parse(timeTableJson);
    if (Array.isArray(parsed)) return parsed;
    if (Array.isArray(parsed?.tasks)) return parsed.tasks;
    if (Array.isArray(parsed?.slots)) return parsed.slots;
    return [];
  } catch {
    return [];
  }
}

function taskProgress(tasks) {
  if (tasks.length === 0) return { completed: 0, total: 0, ratio: 0 };

  const completed = tasks.filter((task) => task.completed || task.done || task.checked).length;
  return { completed, total: tasks.length, ratio: Math.round((completed / tasks.length) * 100) };
}

export function toPlannerSummary(response) {
  const tasks = parseTimeTable(response?.timeTableJson);

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
    downloadUrl: response?.downloadUrl || null,
    progress: taskProgress(tasks),
  };
}

export function toPlannerDetail(response) {
  return {
    ...toPlannerSummary(response),
    content: response?.content || '',
    tmi: response?.tmi || '',
    netStudyTime: response?.netStudyTime || '',
    wakeUpTime: response?.wakeUpTime || '',
    materialId: response?.materialId ?? null,
    sourceType: response?.sourceType || null,
    tasks: parseTimeTable(response?.timeTableJson),
    updatedAt: response?.updatedAt || null,
  };
}

export function toPlannerRequest(form) {
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
  };
}

export function isTodayPlanner(planner, today = new Date()) {
  if (!planner.date) return false;
  return planner.date === today.toISOString().slice(0, 10);
}
