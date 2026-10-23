import { studyTimeService, timerService } from '../../../services/api';
import {
  KOREAN_DAY_NAMES,
  buildWeeklyGraph,
  secondsByWeekdayFromHistory,
  seoulIsoDate,
  summarizeWeek,
  sumTodaySeconds,
} from './reportStats';

export async function loadWeeklyReport(userId) {
  const [weekly, history] = await Promise.all([
    studyTimeService.getWeekly(userId),
    timerService.getTimerHistory(userId),
  ]);
  return { weekly, history };
}

export function buildReport(reportData, now = new Date()) {
  const history = reportData?.history;
  const todaySeconds = sumTodaySeconds(history, seoulIsoDate(now));
  const graph = buildWeeklyGraph({
    weeklyResponse: reportData?.weekly,
    historySecondsByDay: secondsByWeekdayFromHistory(history, now),
    todaySeconds,
    todayDayName: KOREAN_DAY_NAMES[now.getDay()],
  });

  return {
    todaySeconds,
    graph,
    summary: summarizeWeek(graph),
    attendanceDays: reportData?.weekly?.attendanceDays ?? null,
  };
}
