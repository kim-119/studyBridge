const ACTIVITY_TYPE_LABEL = {
  CONCEPT: '개념',
  PRACTICE: '실습',
  ANALYSIS: '분석',
  COMPARISON: '비교',
  REVIEW: '복습',
  OUTPUT: '산출물',
};

const ALIGNMENT_LEVEL_LABEL = {
  HIGH: '높음',
  MEDIUM: '보통',
  LOW: '낮음',
};

const MINUTES_PER_DAY = 1440;

export const DEFAULT_START_TIME = '09:00';

export function activityTypeLabel(type) {
  return ACTIVITY_TYPE_LABEL[String(type || '').toUpperCase()] || type || '학습';
}

export function alignmentLevelLabel(level) {
  return ALIGNMENT_LEVEL_LABEL[String(level || '').toUpperCase()] || level || '—';
}

export function addMinutes(startTime, minutes) {
  const [hours, mins] = String(startTime || DEFAULT_START_TIME)
    .split(':')
    .map((part) => parseInt(part, 10) || 0);
  const total = hours * 60 + mins + (Number(minutes) || 0);
  const normalized = ((total % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;

  return `${String(Math.floor(normalized / 60)).padStart(2, '0')}:${String(normalized % 60).padStart(2, '0')}`;
}

export function isAnalysisEmpty(analysis) {
  return !analysis || analysis.empty === true;
}

export function analysisFlow(analysis) {
  if (Array.isArray(analysis?.flow) && analysis.flow.length > 0) return analysis.flow;
  return Array.isArray(analysis?.tasks) ? analysis.tasks : [];
}

export function analysisPrerequisites(analysis) {
  if (!Array.isArray(analysis?.prerequisites)) return [];
  return analysis.prerequisites.filter(
    (prerequisite) => prerequisite && typeof prerequisite.name === 'string' && prerequisite.name.trim()
  );
}

export function buildSchedulePreview(analysis, startTime) {
  let cursor = startTime || DEFAULT_START_TIME;

  return analysisFlow(analysis).map((node, position) => {
    const minutes = Number(node.recommendedMinutes) || 0;
    const start = cursor;
    const end = addMinutes(cursor, minutes);
    cursor = end;

    return {
      key: `${node.taskId ?? node.id ?? node.title}-${position}`,
      title: node.title,
      type: node.type,
      recommendedMinutes: minutes,
      startTime: start,
      endTime: end,
    };
  });
}

export function analysisTimeLabel(analysis) {
  return analysis?.targetMinutesEstimated
    ? `AI 예상 학습시간 ${analysis.totalRecommendedMinutes ?? 0}분`
    : `총 목표 학습시간 ${analysis?.targetMinutes ?? 0}분`;
}

export function nextLearningOrderLabel(nextLearning) {
  if (nextLearning?.roadmapWeek != null && nextLearning?.roadmapDay != null) {
    return `로드맵 ${nextLearning.roadmapWeek}주차 ${nextLearning.roadmapDay}일`;
  }
  return nextLearning?.recommendationType === 'USER_NEXT' ? '같은 과목의 다음 계획' : '다음 학습';
}

export function completionPercent(nextLearning) {
  if (nextLearning?.completionRate == null) return null;
  return Math.round(nextLearning.completionRate * 100);
}
