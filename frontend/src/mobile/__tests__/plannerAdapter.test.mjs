import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PLANNER_TYPE,
  STUDY_TYPE_OPTIONS,
  countCheckedSlots,
  createBlankPlannerForm,
  dayOfWeekOf,
  findLinkedSchedule,
  formatMinutes,
  formatPlannerDate,
  isSlotChecked,
  isTodayPlanner,
  localIsoDate,
  parseTimeTable,
  plannedMinutes,
  plannerDisplayTitle,
  resolvePlannerType,
  splitPlannersByType,
  summarizePlanners,
  toPlannerDetail,
  toPlannerForm,
  toPlannerRequest,
  toPlannerSummary,
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

test('요청 변환은 날짜를 연·월·일로 분해하고 시간표는 항상 JSON 으로 보낸다', () => {
  const request = toPlannerRequest({ title: ' 복습 ', plannerDate: '2026-09-26' }, {});

  assert.equal(request.title, '복습');
  assert.equal(request.plannerType, PLANNER_TYPE.USER);
  assert.equal(request.plannerDate, '2026-09-26');
  assert.equal(request.year, 2026);
  assert.equal(request.month, 9);
  assert.equal(request.day, 26);
  assert.equal(request.timeTableJson, '{}');
});

test('시간표가 있으면 JSON 문자열로 직렬화한다', () => {
  const request = toPlannerRequest({ title: 'T' }, { 9: [true, false, false, false, false, false] });

  assert.deepEqual(JSON.parse(request.timeTableJson), { 9: [true, false, false, false, false, false] });
});

test('수정 요청은 폼에 없던 필드(tmi, 실제 학습 시간, 기상 시간, 마감일, 요일)를 보존한다', () => {
  const response = {
    id: 3,
    title: '[로드맵 2주차 3일] 뷰모델',
    plannerType: 'ROADMAP',
    year: 2026,
    month: 9,
    day: 7,
    dayOfWeek: '월',
    term: '2주차',
    subject: '안드로이드',
    studyType: '자료 기반 학습',
    priority: '보통',
    goalTime: '90분',
    netStudyTime: '1시간',
    wakeUpTime: '07:00',
    dDay: '2026-10-01',
    content: '학습 목표',
    tmi: '1. 강의 듣기, 2. 실습',
    timeTableJson: '{}',
  };

  const request = toPlannerRequest(toPlannerForm(response), {}, resolvePlannerType(response));

  assert.equal(request.title, response.title);
  assert.equal(request.plannerType, 'ROADMAP');
  assert.equal(request.plannerDate, '2026-09-07');
  assert.equal(request.dayOfWeek, '월');
  assert.equal(request.studyType, '자료 기반 학습');
  assert.equal(request.netStudyTime, '1시간');
  assert.equal(request.wakeUpTime, '07:00');
  assert.equal(request.dDay, '2026-10-01');
  assert.equal(request.tmi, response.tmi);
  assert.equal(request.content, '학습 목표');
});

test('요일이 없는 플래너는 날짜로 요일을 계산한다', () => {
  const form = toPlannerForm({ title: 'T', plannerDate: '2026-09-26' });

  assert.equal(form.dayOfWeek, '토');
  assert.equal(dayOfWeekOf('2026-09-27'), '일');
  assert.equal(dayOfWeekOf(''), '');
});

test('새 플래너 폼은 웹과 같은 기본값을 쓰고 학습 유형·우선순위를 강제하지 않는다', () => {
  const form = createBlankPlannerForm(new Date(2026, 8, 26));

  assert.equal(form.title, '공부 플래너');
  assert.equal(form.plannerDate, '2026-09-26');
  assert.equal(form.dayOfWeek, '토');
  assert.equal(form.studyType, '');
  assert.equal(form.priority, '');
  assert.deepEqual(STUDY_TYPE_OPTIONS, ['강의 복습', '과제', '시험 준비', '팀플', '프로젝트', '발표 준비', '개인 공부']);
});

test('오늘 날짜는 UTC 가 아니라 로컬 날짜 기준이다', () => {
  const lateNight = new Date(2026, 8, 26, 23, 30);

  assert.equal(localIsoDate(lateNight), '2026-09-26');
  assert.equal(isTodayPlanner({ date: '2026-09-26' }, lateNight), true);
  assert.equal(isTodayPlanner({ date: '2026-09-27' }, lateNight), false);
});

test('플래너 원천은 plannerType 우선, 없으면 sourceType 으로 판정한다', () => {
  assert.equal(resolvePlannerType({ plannerType: 'USER', sourceType: 'ROADMAP_AUTO' }), 'USER');
  assert.equal(resolvePlannerType({ sourceType: 'ROADMAP_AUTO' }), 'ROADMAP');
  assert.equal(resolvePlannerType({}), 'USER');
});

test('로드맵 플래너 제목은 접두어를 떼고 주차 라벨을 분리한다', () => {
  const summary = toPlannerSummary({ id: 1, plannerType: 'ROADMAP', title: '[로드맵 1주차 2일] Activity 생명주기' });

  assert.equal(summary.title, 'Activity 생명주기');
  assert.equal(summary.roadmapLabel, '로드맵 1주차 2일');
  assert.equal(plannerDisplayTitle({ plannerType: 'ROADMAP', title: '7', roadmapWeek: 3, roadmapDay: 4 }), '로드맵 3주차 4일 학습');
  assert.equal(plannerDisplayTitle({ title: '' }), '사용자 플래너');
});

test('목록은 원천별로 나누고 현재 탭 기준으로 요약한다', () => {
  const summaries = [
    { id: 1, plannerType: 'ROADMAP', title: '[로드맵 1주차 1일] 개요', plannerDate: '2026-09-26', subject: '안드로이드' },
    { id: 2, plannerType: 'ROADMAP', title: '[로드맵 1주차 2일] 뷰', plannerDate: '2026-09-20', subject: '안드로이드' },
    { id: 3, plannerType: 'USER', title: '시험 공부', plannerDate: '2026-09-30', subject: '운영체제' },
  ].map(toPlannerSummary);

  const byType = splitPlannersByType(summaries);
  const roadmapSummary = summarizePlanners(byType.ROADMAP, new Date(2026, 8, 25));

  assert.equal(byType.ROADMAP.length, 2);
  assert.equal(byType.USER.length, 1);
  assert.equal(roadmapSummary.total, 2);
  assert.equal(roadmapSummary.upcomingCount, 1);
  assert.equal(roadmapSummary.subjectCount, 1);
  assert.equal(formatPlannerDate(byType.USER[0]), '2026.09.30');
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
