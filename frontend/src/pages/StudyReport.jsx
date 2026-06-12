import React, { useEffect, useState } from 'react';
import StudyTimer from '../components/StudyTimer';
import StudyStatistics from '../components/StudyStatistics';
import { useAuth } from '../hooks/useAuth';
import { todoService } from '../services/api';

/**
 * 학습 리포트 탭.
 *  - 기존 타이머/공부시간 기능(StudyTimer)과 주간 통계(StudyStatistics)를 그대로 재사용한다.
 *  - 상단 요약 카드 2종(오늘의 학습 시간 / 등록된 Todo)은 구 대시보드에서 이전한 것으로,
 *    기존 timerService(StudyTimer 누적값)와 todoService.getTodos 로직을 그대로 재사용한다.
 *  - 새 테이블/누적 로직을 만들지 않고, 기존 /api/timers, /api/study-time, /api/todos 흐름을 유지한다.
 */
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

export default function StudyReport() {
  const { userId } = useAuth();
  // StudyTimer 가 누적한 오늘 총 공부 시간을 통계 카드로 전달(대시보드와 동일한 연결).
  const [todayStudySeconds, setTodayStudySeconds] = useState(0);
  const [todoCount, setTodoCount] = useState(0);

  // 등록된 Todo 개수: 기존 todoService.getTodos 재사용(주간일정과 동일한 데이터원).
  useEffect(() => {
    const savedUserId = userId || localStorage.getItem('userId');
    if (!savedUserId) {
      setTodoCount(0);
      return;
    }
    todoService.getTodos(savedUserId)
      .then((data) => setTodoCount(Array.isArray(data) ? data.length : 0))
      .catch((err) => {
        console.error('Todo 개수 조회 실패:', err);
        setTodoCount(0);
      });
  }, [userId]);

  const summaryCards = [
    { title: '오늘의 학습 시간', value: formatStudyTime(todayStudySeconds), desc: '종료된 개인 학습 시간 기준' },
    { title: '등록된 Todo', value: `${todoCount}개`, desc: '캘린더에 등록된 전체 할 일' },
  ];

  return (
    <div className="container-main dashboard-page" style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 900, color: '#15803D', margin: '0 0 6px 0' }}>학습 리포트</h1>
        <p style={{ color: '#6B7280', margin: 0, fontSize: '14px' }}>
          현재 공부 시간을 측정하고, 주간 학습 리포트로 학습 패턴을 확인하세요.
        </p>
      </div>

      {/* 상단 요약 카드 2종 (구 대시보드에서 이전: 오늘의 학습 시간 / 등록된 Todo) */}
      <div className="summary-grid cols-2">
        {summaryCards.map((card) => (
          <div key={card.title} className="summary-card">
            <p>{card.title}</p>
            <h3>{card.value}</h3>
            <p>{card.desc}</p>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        {/* 현재 공부 시간 카드 (시작/종료/누적) */}
        <StudyTimer onTimeUpdate={setTodayStudySeconds} />

        {/* 주간 학습 리포트 (총 시간/평균/집중 요일/내일 예측/월~일 그래프) */}
        <StudyStatistics todayStudySeconds={todayStudySeconds} />
      </div>
    </div>
  );
}
