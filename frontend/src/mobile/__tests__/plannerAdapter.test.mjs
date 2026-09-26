// 실행: node --test frontend/src/mobile/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  countCheckedSlots,
  findLinkedSchedule,
  formatMinutes,
  isSlotChecked,
  parseTimeTable,
  plannedMinutes,
  toPlannerDetail,
  toPlannerRequest,
  toggleSlot,
} from '../screens/planner/plannerAdapter.js';

test('timeTableJson 은 { 시: [10분 슬롯 6칸] } 계약으로 파싱한다', () => {
  const table = parseTimeTable(JSON.stringify({ 9: [true, false, true, false, false, false] }));

  assert.equal(isSlotChecked(table, 9, 0), true);
  assert.equal(isSlotChecked(table, 9, 1), false);
  assert.equal(isSlotChecked(table, 9, 2), true);
  assert.equal(isSlotChecked(table, 10, 0), false);
});

test('깨진 JSON 은 빈 시간표로 처리한다', () => {
  assert.deepEqual(parseTimeTable('{nope'), {});
  assert.deepEqual(parseTimeTable(null), {});
  assert.deepEqual(parseTimeTable('[1,2,3]'), {});
});

test('체크된 슬롯 수와 계획 학습 시간이 일치한다', () => {
  const table = { 9: [true, true, true, false, false, false], 14: [true, false, false, false, false, false] };

  assert.equal(countCheckedSlots(table), 4);
  assert.equal(plannedMinutes(table), 40);
});

test('범위 밖(06시 미만) 슬롯은 집계하지 않는다', () => {
  assert.equal(countCheckedSlots({ 3: [true, true, true, true, true, true] }), 0);
});

test('슬롯 토글은 불변이며 모두 해제되면 행을 제거한다', () => {
  const before = {};
  const afterOn = toggleSlot(before, 8, 2);

  assert.deepEqual(before, {});
  assert.equal(isSlotChecked(afterOn, 8, 2), true);

  const afterOff = toggleSlot(afterOn, 8, 2);
  assert.equal(Object.prototype.hasOwnProperty.call(afterOff, '8'), false);
});

test('학습 시간 표기', () => {
  assert.equal(formatMinutes(0), '0분');
  assert.equal(formatMinutes(50), '50분');
  assert.equal(formatMinutes(60), '1시간');
  assert.equal(formatMinutes(130), '2시간 10분');
});

test('상세 변환은 시간표와 계획 학습량을 포함한다', () => {
  const detail = toPlannerDetail({
    id: 7,
    title: '머신러닝 3장',
    plannerDate: '2026-09-26T00:00:00',
    timeTableJson: JSON.stringify({ 20: [true, true, false, false, false, false] }),
  });

  assert.equal(detail.id, 7);
  assert.equal(detail.date, '2026-09-26');
  assert.equal(detail.plannedMinutes, 20);
});

test('요청 변환은 날짜를 연·월·일로 분해하고 빈 시간표는 보내지 않는다', () => {
  const request = toPlannerRequest({ title: ' 복습 ', date: '2026-09-26' }, {});

  assert.equal(request.title, '복습');
  assert.equal(request.year, 2026);
  assert.equal(request.month, 9);
  assert.equal(request.day, 26);
  assert.equal(request.timeTableJson, null);
});

test('시간표가 있으면 JSON 문자열로 직렬화한다', () => {
  const request = toPlannerRequest({ title: 'T' }, { 9: [true, false, false, false, false, false] });

  assert.deepEqual(JSON.parse(request.timeTableJson), { 9: [true, false, false, false, false, false] });
});

test('연동된 주간일정은 sourceType/sourceId 로 찾는다', () => {
  const todos = [
    { id: 1, sourceType: 'REVIEW_NOTE', sourceId: 7 },
    { id: 2, sourceType: 'PLANNER', sourceId: 7 },
    { id: 3, sourceType: null, sourceId: null },
  ];

  assert.equal(findLinkedSchedule(todos, 7).id, 2);
  assert.equal(findLinkedSchedule(todos, 99), null);
  assert.equal(findLinkedSchedule(null, 7), null);
});
