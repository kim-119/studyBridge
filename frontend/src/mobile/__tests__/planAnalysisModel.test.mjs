import test from 'node:test';
import assert from 'node:assert/strict';
import {
  activityTypeLabel,
  addMinutes,
  alignmentLevelLabel,
  analysisPrerequisites,
  buildSchedulePreview,
  completionPercent,
  isAnalysisEmpty,
  nextLearningOrderLabel,
} from '../screens/planner/planAnalysisModel.js';

test('시각 더하기는 자정을 넘기면 순환한다', () => {
  assert.equal(addMinutes('09:00', 45), '09:45');
  assert.equal(addMinutes('23:30', 45), '00:15');
  assert.equal(addMinutes('', 30), '09:30');
});

test('시간표 미리보기는 flow 를 우선 사용하고 시작 시각부터 이어 붙인다', () => {
  const analysis = {
    flow: [
      { taskId: 1, title: '개념 정리', type: 'CONCEPT', recommendedMinutes: 30 },
      { taskId: 2, title: '실습', type: 'PRACTICE', recommendedMinutes: 40 },
    ],
    tasks: [{ id: 9, title: '무시됨', recommendedMinutes: 10 }],
  };

  const rows = buildSchedulePreview(analysis, '10:00');

  assert.equal(rows.length, 2);
  assert.equal(rows[0].startTime, '10:00');
  assert.equal(rows[0].endTime, '10:30');
  assert.equal(rows[1].startTime, '10:30');
  assert.equal(rows[1].endTime, '11:10');
});

test('flow 가 없으면 학습 활동으로 대체한다', () => {
  const rows = buildSchedulePreview({ tasks: [{ id: 1, title: '복습', recommendedMinutes: 20 }] }, '09:00');

  assert.equal(rows[0].title, '복습');
  assert.equal(rows[0].endTime, '09:20');
});

test('라벨 변환', () => {
  assert.equal(activityTypeLabel('practice'), '실습');
  assert.equal(activityTypeLabel(null), '학습');
  assert.equal(alignmentLevelLabel('HIGH'), '높음');
  assert.equal(alignmentLevelLabel(undefined), '—');
});

test('비어 있는 분석과 선행 개념 필터', () => {
  assert.equal(isAnalysisEmpty(null), true);
  assert.equal(isAnalysisEmpty({ empty: true }), true);
  assert.equal(isAnalysisEmpty({ title: 'x' }), false);
  assert.deepEqual(
    analysisPrerequisites({ prerequisites: [{ name: 'Kotlin' }, { name: ' ' }, null] }).map((item) => item.name),
    ['Kotlin']
  );
});

test('다음 학습 순서 라벨과 이행도', () => {
  assert.equal(nextLearningOrderLabel({ roadmapWeek: 2, roadmapDay: 5 }), '로드맵 2주차 5일');
  assert.equal(nextLearningOrderLabel({ recommendationType: 'USER_NEXT' }), '같은 과목의 다음 계획');
  assert.equal(completionPercent({ completionRate: 0.456 }), 46);
  assert.equal(completionPercent({ completionRate: null }), null);
});
