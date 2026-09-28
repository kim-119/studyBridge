import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ROADMAP_DAYS_REQUIRED_MESSAGE,
  assertRoadmapSucceeded,
  buildFromRoadmapRequest,
  buildPlannerItemsFromRoadmap,
  canCreatePlanners,
  findDay,
  firstOpenWeekNumber,
  hasDayStructure,
  normalizeRoadmapWeeks,
  roadmapFailureMessage,
  roadmapProgress,
  toggleDayInWeeks,
  toggleTaskInWeeks,
} from '../screens/roadmap/roadmapModel.js';

function dayFixture(weekNumber, dayIndex) {
  return {
    day_index: dayIndex,
    day_label: `${dayIndex}일차`,
    title: `${weekNumber}주 ${dayIndex}일 핵심 학습`,
    objective: 'ViewModel 상태 관리 이해',
    core_concepts: ['ViewModel', 'LiveData'],
    tasks: [
      { title: '강의 정리', description: '핵심 개념 요약', estimated_minutes: 30 },
      { title: '실습 코드 작성', estimated_minutes: 20 },
    ],
    review_questions: ['ViewModel은 언제 사라지는가?'],
    checkpoint: '화면 회전 후 상태 유지 확인',
    deliverable: '실습 코드 저장소',
    completed: weekNumber === 1 && dayIndex <= 2,
  };
}

function ai07RoadmapFixture(weekCount = 12, dayCount = 7) {
  const weeks = Array.from({ length: weekCount }, (_, weekPosition) => ({
    week: weekPosition + 1,
    title: `${weekPosition + 1}주차 주제`,
    objective: '주간 학습 목표',
    days: Array.from({ length: dayCount }, (__, dayPosition) => dayFixture(weekPosition + 1, dayPosition + 1)),
  }));

  return { roadmapId: 55, materialId: 9, title: 'AI 로드맵', steps: null, roadmapData: { total_weeks: weekCount, weeks } };
}

function legacyRoadmapFixture() {
  return {
    roadmapId: 3,
    steps: [{ stepId: 1, stepOrder: 1, title: '기초', tasks: [] }],
    roadmapData: {
      weeks: [
        {
          week: 1,
          title: '기초',
          description: '기초 개념',
          tasks: [
            { taskId: 101, taskOrder: 1, content: '강의 듣기', isCompleted: true },
            { taskId: 102, taskOrder: 2, content: '실습', isCompleted: false },
          ],
        },
      ],
    },
  };
}

test('84일 로드맵은 주차별 7일로 정규화된다', () => {
  const weeks = normalizeRoadmapWeeks(ai07RoadmapFixture());

  assert.equal(weeks.length, 12);
  assert.equal(weeks[0].weekNumber, 1);
  assert.equal(weeks[0].days.length, 7);
  assert.equal(hasDayStructure(weeks), true);

  const day = weeks[0].days[0];
  assert.equal(day.dayIndex, 1);
  assert.equal(day.dayLabel, '1일차');
  assert.equal(day.objective, 'ViewModel 상태 관리 이해');
  assert.deepEqual(day.coreConcepts, ['ViewModel', 'LiveData']);
  assert.deepEqual(day.tasks, ['강의 정리', '실습 코드 작성']);
  assert.deepEqual(day.reviewQuestions, ['ViewModel은 언제 사라지는가?']);
  assert.equal(day.deliverable, '실습 코드 저장소');
  assert.equal(day.completed, true);
});

test('문자열로 저장된 roadmapData 도 파싱한다', () => {
  const roadmap = ai07RoadmapFixture(1, 7);
  const weeks = normalizeRoadmapWeeks({ roadmapData: JSON.stringify(roadmap.roadmapData) });

  assert.equal(weeks[0].days.length, 7);
});

test('레거시 로드맵은 서버 taskId 를 가진 태스크로 정규화된다', () => {
  const weeks = normalizeRoadmapWeeks(legacyRoadmapFixture());

  assert.equal(hasDayStructure(weeks), false);
  assert.equal(weeks[0].tasks[0].taskId, 101);
  assert.equal(weeks[0].tasks[0].hasServerId, true);
  assert.deepEqual(roadmapProgress(weeks), { done: 1, total: 2, percent: 50, label: '1/2' });
});

test('진행률은 일(日) 단위로 계산한다', () => {
  const weeks = normalizeRoadmapWeeks(ai07RoadmapFixture());

  assert.deepEqual(roadmapProgress(weeks), { done: 2, total: 84, percent: 2, label: '2/84일' });
  assert.equal(firstOpenWeekNumber(weeks), 1);
});

test('일자 토글은 해당 주차·일자만 뒤집는다', () => {
  const weeks = normalizeRoadmapWeeks(ai07RoadmapFixture(2, 7));
  const toggled = toggleDayInWeeks(weeks, 2, 3);

  assert.equal(findDay(toggled, 2, 3).completed, true);
  assert.equal(findDay(toggled, 1, 3).completed, false);
  assert.equal(findDay(weeks, 2, 3).completed, false);
  assert.equal(findDay(toggleDayInWeeks(toggled, 2, 3), 2, 3).completed, false);
});

test('태스크 토글은 taskId 로 대상만 뒤집는다', () => {
  const weeks = normalizeRoadmapWeeks(legacyRoadmapFixture());
  const toggled = toggleTaskInWeeks(weeks, 102);

  assert.equal(toggled[0].tasks[1].isCompleted, true);
  assert.equal(toggled[0].tasks[0].isCompleted, true);
});

test('플래너 항목은 웹과 같은 필드로 84개 생성된다', () => {
  const items = buildPlannerItemsFromRoadmap(ai07RoadmapFixture());

  assert.equal(items.length, 84);
  assert.deepEqual(items[8], {
    week: 2,
    dayIndex: 2,
    title: '2주 2일 핵심 학습',
    objective: 'ViewModel 상태 관리 이해',
    tasks: ['강의 정리: 핵심 개념 요약', '실습 코드 작성'],
    coreConcepts: ['ViewModel', 'LiveData'],
    reviewQuestions: ['ViewModel은 언제 사라지는가?'],
    checkpoint: '화면 회전 후 상태 유지 확인',
    deliverable: '실습 코드 저장소',
    targetMinutes: 50,
  });
});

test('84일이 아니면 플래너를 만들 수 없다', () => {
  assert.equal(canCreatePlanners(ai07RoadmapFixture()), true);
  assert.equal(canCreatePlanners(ai07RoadmapFixture(11, 7)), false);
  assert.equal(canCreatePlanners(legacyRoadmapFixture()), false);
  assert.throws(
    () => buildFromRoadmapRequest({ materialId: '9', roadmap: legacyRoadmapFixture(), startDate: '2026-09-26' }),
    { message: ROADMAP_DAYS_REQUIRED_MESSAGE }
  );
});

test('플래너 생성 요청은 백엔드 FromRoadmapRequest 필드를 채운다', () => {
  const request = buildFromRoadmapRequest({
    materialId: '9',
    roadmap: ai07RoadmapFixture(),
    materialTitle: '안드로이드 프로그래밍',
    startDate: '2026-09-26',
    force: false,
  });

  assert.equal(request.materialId, 9);
  assert.equal(request.roadmapId, 55);
  assert.equal(request.subject, '안드로이드 프로그래밍');
  assert.equal(request.startDate, '2026-09-26');
  assert.equal(request.force, false);
  assert.equal(request.items.length, 84);
});

test('로드맵 실패 응답은 서버 메시지 또는 오류 코드 메시지로 드러낸다', () => {
  assert.equal(roadmapFailureMessage({ success: true }), null);
  assert.equal(roadmapFailureMessage({ success: false, message: '텍스트가 없습니다.' }), '텍스트가 없습니다.');
  assert.equal(
    roadmapFailureMessage({ success: false, errorCode: 'AI_TIMEOUT' }),
    'AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.'
  );
  assert.throws(() => assertRoadmapSucceeded({ success: false, errorCode: 'UNKNOWN_ERROR' }));
});
