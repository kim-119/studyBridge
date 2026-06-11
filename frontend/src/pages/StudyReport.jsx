import React, { useState } from 'react';
import StudyTimer from '../components/StudyTimer';
import StudyStatistics from '../components/StudyStatistics';

/**
 * 학습 리포트 탭.
 *  - 기존 타이머/공부시간 기능(StudyTimer)과 주간 통계(StudyStatistics)를 그대로 재사용한다.
 *  - 새 테이블/누적 로직을 만들지 않고, 기존 /api/timers, /api/study-time 흐름을 유지한다.
 */
export default function StudyReport() {
  // StudyTimer 가 누적한 오늘 총 공부 시간을 통계 카드로 전달(대시보드와 동일한 연결).
  const [todayStudySeconds, setTodayStudySeconds] = useState(0);

  return (
    <div className="container-main" style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 900, color: '#15803D', margin: '0 0 6px 0' }}>학습 리포트</h1>
        <p style={{ color: '#6B7280', margin: 0, fontSize: '14px' }}>
          현재 공부 시간을 측정하고, 주간 학습 리포트로 학습 패턴을 확인하세요.
        </p>
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
