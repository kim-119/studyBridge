import React from 'react';
import StudyTimer from './StudyTimer';
import StudyStatistics from './StudyStatistics';

const formatStudyTime = (seconds) => {
  const totalSeconds = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  const parts = [];

  if (h) parts.push(`${h}시간`);
  if (m) parts.push(`${m}분`);
  if (s || parts.length === 0) parts.push(`${s}초`);

  return parts.join(' ');
};

export default function StudyReport({ todayStudySeconds, todoCount, onTimeUpdate }) {
  const summaryCards = [
    { title: '오늘의 학습 시간', value: formatStudyTime(todayStudySeconds), desc: '종료된 개인 학습 시간 기준' },
    { title: '진행 중인 스터디', value: '0개', desc: '참여 중인 그룹 스터디' },
    { title: '등록된 Todo', value: `${todoCount || 0}개`, desc: '캘린더에 등록된 전체 할 일' },
  ];

  return (
    <div className="study-report-layout">
      <StudyTimer onTimeUpdate={onTimeUpdate} />
      <div className="summary-grid">
        {summaryCards.map((card) => (
          <div key={card.title} className="glass-panel summary-card animate-fade-in">
            <p>{card.title}</p>
            <h3>{card.value}</h3>
            <p>{card.desc}</p>
          </div>
        ))}
      </div>
      <StudyStatistics todayStudySeconds={todayStudySeconds} />
    </div>
  );
}
