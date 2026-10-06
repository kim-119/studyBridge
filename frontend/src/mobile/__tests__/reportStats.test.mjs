import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildWeeklyGraph,
  currentWeekBounds,
  formatDuration,
  formatHoursMinutes,
  runningSessionStart,
  secondsByWeekdayFromHistory,
  sumTodaySeconds,
  summarizeTodos,
  summarizeWeek,
  toChartHours,
  toSeoulLocalDateTime,
} from '../screens/report/reportStats.js';

test('타이머 시각은 웹과 같이 서울 로컬 시각(오프셋 없음)으로 보낸다', () => {
  assert.equal(toSeoulLocalDateTime(new Date('2026-09-26T00:30:15Z')), '2026-09-26T09:30:15');
  assert.equal(toSeoulLocalDateTime(new Date('2026-09-26T16:00:00Z')), '2026-09-27T01:00:00');
});

test('시간 표기는 웹 formatStudyTime 과 같다', () => {
  assert.equal(formatDuration(0), '0초');
  assert.equal(formatDuration(3725), '1시간 2분 5초');
  assert.equal(formatDuration(120), '2분');
  assert.equal(formatHoursMinutes(3725), '1시간 2분');
  assert.equal(formatHoursMinutes(30), '0분');
});

test('오늘 학습 시간은 오늘 시작된 종료 세션만 합산한다', () => {
  const history = [
    { startTime: '2026-09-26T09:00:00', endTime: '2026-09-26T10:00:00' },
    { startTime: '2026-09-26T11:00:00', endTime: null },
    { startTime: '2026-09-25T09:00:00', endTime: '2026-09-25T10:00:00' },
  ];
  assert.equal(sumTodaySeconds(history, '2026-09-26'), 3600);
  assert.equal(sumTodaySeconds(null, '2026-09-26'), 0);
});

test('진행 중 세션은 종료 시각이 없을 때만 인정한다', () => {
  assert.equal(runningSessionStart(''), null);
  assert.equal(runningSessionStart({ startTime: '2026-09-26T09:00:00', endTime: '2026-09-26T10:00:00' }), null);
  assert.equal(
    runningSessionStart({ startTime: '2026-09-26T09:00:00' }),
    new Date('2026-09-26T09:00:00').getTime()
  );
});

test('이번 주는 월요일 00:00 부터 일요일 23:59 까지다', () => {
  const { start, end } = currentWeekBounds(new Date(2026, 8, 27, 12));
  assert.equal(start.getDate(), 21);
  assert.equal(start.getDay(), 1);
  assert.equal(end.getDate(), 27);
  assert.equal(end.getDay(), 0);
});

test('주간 그래프는 서버 초와 타이머 기록 중 큰 값, 오늘은 오늘 누적을 반영한다', () => {
  const now = new Date(2026, 8, 26, 12);
  const history = [
    { status: 'COMPLETED', startTime: '2026-09-22T09:00:00', endTime: '2026-09-22T10:00:00' },
    { status: 'STARTED', startTime: '2026-09-23T09:00:00', endTime: '2026-09-23T10:00:00' },
  ];
  const graph = buildWeeklyGraph({
    weeklyResponse: {
      attendanceDays: 2,
      dailyStats: [
        { date: '2026-09-21', day: 'MONDAY', seconds: 600 },
        { date: '2026-09-22', day: 'TUESDAY', seconds: 1200 },
        { date: '2026-09-26', day: 'SATURDAY', seconds: 100 },
      ],
    },
    historySecondsByDay: secondsByWeekdayFromHistory(history, now),
    todaySeconds: 900,
    todayDayName: '토',
  });

  assert.deepEqual(
    graph.map((item) => [item.day, item.seconds]),
    [
      ['월', 600],
      ['화', 3600],
      ['토', 900],
    ]
  );

  const summary = summarizeWeek(graph);
  assert.equal(summary.totalSeconds, 5100);
  assert.equal(summary.averageSeconds, 5100 / 7);
  assert.equal(summary.focusDay, '화');
  assert.equal(summary.hasRecords, true);
});

test('주간 응답이 비어 있으면 7일 0초 그래프와 기록 없음 요약을 만든다', () => {
  const graph = buildWeeklyGraph({
    weeklyResponse: {},
    historySecondsByDay: {},
    todaySeconds: 0,
    todayDayName: '월',
  });
  assert.equal(graph.length, 7);
  assert.equal(graph[0].day, '월');
  assert.deepEqual(summarizeWeek(graph), {
    totalSeconds: 0,
    averageSeconds: 0,
    focusDay: '없음',
    hasRecords: false,
  });
});

test('차트 막대는 짧은 학습도 보이도록 최소 0.03시간으로 올린다', () => {
  assert.equal(toChartHours(0), 0);
  assert.equal(toChartHours(30), 0.03);
  assert.equal(toChartHours(5400), 1.5);
});

test('Todo 요약은 API completed 필드로만 완료 수를 센다', () => {
  assert.deepEqual(summarizeTodos([{ completed: true }, { completed: false }, {}]), { total: 3, completed: 1 });
  assert.deepEqual(summarizeTodos(null), { total: 0, completed: 0 });
});
