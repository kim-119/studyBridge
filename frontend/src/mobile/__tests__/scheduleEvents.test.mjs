import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EVENT_COLORS,
  PLANNER_EVENT_STYLE,
  addDaysToIsoDate,
  buildCreateTodoPayload,
  displayTodoText,
  isDateInTodoRange,
  isPlannerTodo,
  isReviewTodo,
  toCalendarEvents,
  todoToCalendarEvent,
  todosOnDate,
  todosOverlappingRange,
  validateTodoDraft,
} from '../screens/schedule/scheduleEvents.js';

test('종료일은 FullCalendar 계약에 맞춰 하루 뒤(배타적)로 변환한다', () => {
  const event = todoToCalendarEvent({
    id: 3,
    text: '머신러닝 복습',
    startDate: '2026-09-26T00:00:00',
    endDate: '2026-09-28T23:59:59',
    completed: false,
  });

  assert.equal(event.start, '2026-09-26');
  assert.equal(event.end, '2026-09-29');
  assert.equal(event.allDay, true);
  assert.equal(event.title, '머신러닝 복습');
  assert.equal(event.backgroundColor, EVENT_COLORS[3 % EVENT_COLORS.length]);
});

test('종료일이 없으면 시작일 하루짜리 일정이 된다', () => {
  const event = todoToCalendarEvent({ id: 1, text: 'a', startDate: '2026-12-31T00:00:00' });
  assert.equal(event.end, '2027-01-01');
});

test('시작일이 없는 레거시 todo 는 캘린더에서 제외한다', () => {
  const events = toCalendarEvents([
    { id: 1, text: 'no start', endDate: '2026-09-26T23:59:59' },
    { id: 2, text: 'ok', startDate: '2026-09-26T00:00:00' },
  ]);
  assert.deepEqual(events.map((event) => event.id), ['2']);
});

test('플래너 todo 는 sourceType 또는 접두어로 구분하고 초록색과 접두어 제거 제목을 쓴다', () => {
  const byPrefix = { id: 7, text: '[플래너] 영어 단어', startDate: '2026-09-26T00:00:00' };
  const bySource = { id: 8, text: '수학', sourceType: 'PLANNER', startDate: '2026-09-26T00:00:00' };

  assert.equal(isPlannerTodo(byPrefix), true);
  assert.equal(isPlannerTodo(bySource), true);
  assert.equal(displayTodoText(byPrefix.text), '영어 단어');
  assert.equal(todoToCalendarEvent(byPrefix).title, '영어 단어');
  assert.equal(todoToCalendarEvent(bySource).backgroundColor, PLANNER_EVENT_STYLE.backgroundColor);
  assert.equal(todoToCalendarEvent(bySource).extendedProps.source, 'planner');
});

test('복습 todo 는 REVIEW_NOTE sourceType 으로만 구분한다', () => {
  assert.equal(isReviewTodo({ sourceType: 'REVIEW_NOTE' }), true);
  assert.equal(isReviewTodo({ text: '[복습] a' }), false);
});

test('선택 날짜는 시작~종료 범위에 포함된 todo 만 보여준다', () => {
  const todo = { id: 1, startDate: '2026-09-26T00:00:00', endDate: '2026-09-28T23:59:59' };

  assert.equal(isDateInTodoRange('2026-09-26', todo), true);
  assert.equal(isDateInTodoRange('2026-09-28', todo), true);
  assert.equal(isDateInTodoRange('2026-09-29', todo), false);
  assert.equal(isDateInTodoRange('2026-09-25', todo), false);
  assert.deepEqual(todosOnDate([todo], '2026-09-27'), [todo]);
});

test('기간 요약은 보이는 기간과 겹치는 todo 를 센다', () => {
  const todos = [
    { id: 1, startDate: '2026-08-30T00:00:00', endDate: '2026-09-02T23:59:59' },
    { id: 2, startDate: '2026-10-01T00:00:00' },
    { id: 3, endDate: '2026-09-10T23:59:59' },
  ];
  assert.deepEqual(
    todosOverlappingRange(todos, '2026-09-01', '2026-09-30').map((todo) => todo.id),
    [1]
  );
});

test('일정 생성 요청은 웹과 같이 시작 00:00:00, 종료 23:59:59 로 보낸다', () => {
  assert.deepEqual(
    buildCreateTodoPayload({ text: '  복습  ', startDate: '2026-09-26', endDate: '2026-09-27' }),
    {
      text: '복습',
      startDate: '2026-09-26T00:00:00',
      endDate: '2026-09-27T23:59:59',
      viewType: 'MONTH',
      completed: false,
    }
  );
});

test('종료 날짜가 시작 날짜보다 빠르면 생성하지 않는다', () => {
  assert.equal(validateTodoDraft({ text: 'a', startDate: '2026-09-26', endDate: '2026-09-26' }), null);
  assert.match(validateTodoDraft({ text: 'a', startDate: '2026-09-26', endDate: '2026-09-25' }), /종료 날짜/);
  assert.match(validateTodoDraft({ text: ' ', startDate: '2026-09-26', endDate: '2026-09-26' }), /할 일/);
  assert.match(validateTodoDraft({ text: 'a', startDate: '', endDate: '2026-09-26' }), /시작 날짜/);
});

test('날짜 더하기는 월/연 경계를 넘는다', () => {
  assert.equal(addDaysToIsoDate('2026-02-28', 1), '2026-03-01');
  assert.equal(addDaysToIsoDate('2026-03-01', -1), '2026-02-28');
});
