export const PLANNER_PREFIX = '[플래너]';

export const EVENT_COLORS = ['#DDF5E3', '#D9F0FF', '#FDF0D5', '#EEE3FF', '#E6FFF4'];

export const PLANNER_EVENT_STYLE = {
  backgroundColor: '#DCFCE7',
  borderColor: '#86EFAC',
};

const DEFAULT_EVENT_BORDER = 'rgba(0,0,0,0.05)';
const EVENT_TEXT_COLOR = '#1F2937';
const ISO_DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

export function isPlannerTodo(todo) {
  if (todo?.sourceType === 'PLANNER') return true;
  return typeof todo?.text === 'string' && todo.text.startsWith(PLANNER_PREFIX);
}

export function isReviewTodo(todo) {
  return todo?.sourceType === 'REVIEW_NOTE';
}

export function displayTodoText(text) {
  if (typeof text === 'string' && text.startsWith(PLANNER_PREFIX)) {
    return text.slice(PLANNER_PREFIX.length).trim();
  }
  return text;
}

export function toLocalIsoDate(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

export function datePartOf(value) {
  if (!value) return '';
  return String(value).split('T')[0];
}

export function addDaysToIsoDate(isoDate, days) {
  const [year, month, day] = isoDate.split('-').map(Number);
  const shifted = new Date(Date.UTC(year, month - 1, day + days));
  return shifted.toISOString().slice(0, 10);
}

function todoStartDate(todo) {
  return datePartOf(todo?.startDate);
}

function todoLastDate(todo) {
  return datePartOf(todo?.endDate) || todoStartDate(todo);
}

export function todoToCalendarEvent(todo) {
  const start = todoStartDate(todo);
  if (!start) return null;

  const planner = isPlannerTodo(todo);

  return {
    id: String(todo.id),
    title: displayTodoText(todo.text),
    start,
    end: addDaysToIsoDate(todoLastDate(todo), 1),
    allDay: true,
    backgroundColor: planner
      ? PLANNER_EVENT_STYLE.backgroundColor
      : EVENT_COLORS[(todo.id || 0) % EVENT_COLORS.length],
    borderColor: planner ? PLANNER_EVENT_STYLE.borderColor : DEFAULT_EVENT_BORDER,
    textColor: EVENT_TEXT_COLOR,
    extendedProps: { completed: Boolean(todo.completed), source: planner ? 'planner' : 'todo' },
  };
}

export function toCalendarEvents(todos) {
  if (!Array.isArray(todos)) return [];
  return todos.map(todoToCalendarEvent).filter(Boolean);
}

export function isDateInTodoRange(isoDate, todo) {
  const start = todoStartDate(todo);
  if (!isoDate || !start) return false;
  return isoDate >= start && isoDate <= todoLastDate(todo);
}

export function todosOnDate(todos, isoDate) {
  if (!Array.isArray(todos)) return [];
  return todos.filter((todo) => isDateInTodoRange(isoDate, todo));
}

export function todosOverlappingRange(todos, firstDate, lastDate) {
  if (!Array.isArray(todos)) return [];
  return todos.filter((todo) => {
    const start = todoStartDate(todo);
    if (!start) return false;
    return start <= lastDate && todoLastDate(todo) >= firstDate;
  });
}

export function countCompleted(todos) {
  return todos.filter((todo) => todo.completed).length;
}

export function validateTodoDraft({ text, startDate, endDate }) {
  if (!text || !text.trim()) return '할 일을 입력하세요.';
  if (!ISO_DATE_PATTERN.test(startDate || '')) return '시작 날짜를 선택하세요.';
  if (!ISO_DATE_PATTERN.test(endDate || '')) return '종료 날짜를 선택하세요.';
  if (endDate < startDate) return '종료 날짜는 시작 날짜와 같거나 이후여야 합니다.';
  return null;
}

export function buildCreateTodoPayload({ text, startDate, endDate }) {
  return {
    text: text.trim(),
    startDate: `${startDate}T00:00:00`,
    endDate: `${endDate}T23:59:59`,
    viewType: 'MONTH',
    completed: false,
  };
}

export function todoPeriodLabel(todo) {
  const start = todoStartDate(todo);
  const last = todoLastDate(todo);
  if (!start) return '';
  if (start === last) return start;
  return `${start} ~ ${last}`;
}
