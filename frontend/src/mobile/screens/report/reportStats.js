export const KOREAN_DAY_NAMES = ['일', '월', '화', '수', '목', '금', '토'];

const ENGLISH_TO_KOREAN_DAY = {
  MONDAY: '월',
  TUESDAY: '화',
  WEDNESDAY: '수',
  THURSDAY: '목',
  FRIDAY: '금',
  SATURDAY: '토',
  SUNDAY: '일',
};

const WEEK_ORDER = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY', 'SATURDAY', 'SUNDAY'];
const MINIMUM_VISIBLE_HOURS = 0.03;

export function formatDuration(seconds) {
  const totalSeconds = Math.max(0, Math.round(seconds || 0));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const rest = totalSeconds % 60;
  const parts = [];

  if (hours) parts.push(`${hours}시간`);
  if (minutes) parts.push(`${minutes}분`);
  if (rest || parts.length === 0) parts.push(`${rest}초`);

  return parts.join(' ');
}

export function formatHoursMinutes(seconds) {
  const totalSeconds = Math.max(0, Number(seconds) || 0);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const parts = [];

  if (hours > 0) parts.push(`${hours}시간`);
  if (minutes > 0 || parts.length === 0) parts.push(`${minutes}분`);

  return parts.join(' ');
}

export function toSeoulLocalDateTime(date) {
  return date.toLocaleString('sv', { timeZone: 'Asia/Seoul' }).replace(' ', 'T');
}

export function seoulIsoDate(date) {
  return toSeoulLocalDateTime(date).slice(0, 10);
}

export function sumTodaySeconds(history, todayIsoDate) {
  if (!Array.isArray(history)) return 0;

  return history.reduce((total, session) => {
    if (!session?.startTime || !session?.endTime) return total;
    if (!String(session.startTime).startsWith(todayIsoDate)) return total;

    const start = new Date(session.startTime).getTime();
    const end = new Date(session.endTime).getTime();
    return total + Math.floor((end - start) / 1000);
  }, 0);
}

export function runningSessionStart(currentSession) {
  if (!currentSession?.startTime || currentSession.endTime) return null;

  const startedAt = new Date(currentSession.startTime).getTime();
  return Number.isNaN(startedAt) ? null : startedAt;
}

export function currentWeekBounds(now) {
  const dayOfWeek = now.getDay();
  const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek;

  const start = new Date(now);
  start.setDate(now.getDate() + mondayOffset);
  start.setHours(0, 0, 0, 0);

  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  end.setHours(23, 59, 59, 999);

  return { start, end };
}

export function secondsByWeekdayFromHistory(history, now) {
  const { start, end } = currentWeekBounds(now);
  const secondsByDay = {};

  if (!Array.isArray(history)) return secondsByDay;

  history.forEach((timer) => {
    if (timer?.status !== 'COMPLETED' || !timer.startTime || !timer.endTime) return;

    const startTime = new Date(timer.startTime);
    const endTime = new Date(timer.endTime);
    if (endTime < start || endTime > end) return;

    const dayName = KOREAN_DAY_NAMES[endTime.getDay()];
    const seconds = (endTime.getTime() - startTime.getTime()) / 1000;
    secondsByDay[dayName] = (secondsByDay[dayName] || 0) + seconds;
  });

  return secondsByDay;
}

function dailyStatsOf(weeklyResponse) {
  if (Array.isArray(weeklyResponse)) return weeklyResponse;
  const stats = weeklyResponse?.dailyStats || weeklyResponse?.data;
  return Array.isArray(stats) ? stats : [];
}

function emptyWeek() {
  return WEEK_ORDER.map((day) => ({ day, seconds: 0 }));
}

export function buildWeeklyGraph({ weeklyResponse, historySecondsByDay, todaySeconds, todayDayName }) {
  const dailyStats = dailyStatsOf(weeklyResponse);
  const source = dailyStats.length > 0 ? dailyStats : emptyWeek();

  return source.map((item) => {
    const day = ENGLISH_TO_KOREAN_DAY[item.day] || item.day;
    let seconds = Number(item.seconds || 0);

    if ((historySecondsByDay[day] || 0) > seconds) seconds = historySecondsByDay[day];
    if (day === todayDayName && todaySeconds > 0) seconds = Math.max(seconds, todaySeconds);

    return { date: item.date || null, day, seconds };
  });
}

export function summarizeWeek(graph) {
  const totalSeconds = graph.reduce((sum, item) => sum + item.seconds, 0);
  const focusItem = graph.reduce(
    (best, item) => (item.seconds > 0 && item.seconds > (best?.seconds ?? 0) ? item : best),
    null
  );

  return {
    totalSeconds,
    averageSeconds: totalSeconds / 7,
    focusDay: focusItem ? focusItem.day : '없음',
    hasRecords: totalSeconds > 0,
  };
}

export function toChartHours(seconds) {
  const hours = seconds / 3600;
  if (hours > 0 && hours < MINIMUM_VISIBLE_HOURS) return MINIMUM_VISIBLE_HOURS;
  return Number(hours.toFixed(4));
}

export function summarizeTodos(todos) {
  const list = Array.isArray(todos) ? todos : [];
  return {
    total: list.length,
    completed: list.filter((todo) => todo.completed === true).length,
  };
}
