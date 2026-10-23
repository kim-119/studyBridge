import React, { useMemo } from 'react';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { studyTimeService, timerService, todoService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import StudyTimerPanel from './StudyTimerPanel';
import WeeklyReportSection from './WeeklyReportSection';
import { formatDuration, summarizeTodos } from './reportStats';
import { buildReport, loadWeeklyReport } from './weeklyReport';
import './report.css';

function TodoCountCard({ todos }) {
  if (todos.isError) {
    return (
      <div className="mobile-card mobile-report__summary-card">
        <p className="mobile-card__meta">등록된 Todo</p>
        <p className="mobile-field__error">{todos.errorMessage}</p>
        <button type="button" className="mobile-report__retry" onClick={todos.reload}>
          다시 시도
        </button>
      </div>
    );
  }

  const counts = summarizeTodos(todos.data);
  const isPending = todos.isLoading && todos.data == null;

  return (
    <div className="mobile-card mobile-report__summary-card">
      <p className="mobile-card__meta">등록된 Todo</p>
      <p className="mobile-report__stat-value">{isPending ? '-' : `${counts.total}개`}</p>
      <p className="mobile-field__hint">{isPending ? '불러오는 중' : `완료 ${counts.completed}개`}</p>
    </div>
  );
}

export default function StudyReportScreen() {
  const { userId } = useAuth();
  const weeklyReport = useAsync(() => loadWeeklyReport(userId), [userId]);
  const currentSession = useAsync(() => timerService.getCurrentSession(userId), [userId]);
  const prediction = useAsync(() => studyTimeService.getPrediction(userId), [userId]);
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);

  const report = useMemo(() => buildReport(weeklyReport.data), [weeklyReport.data]);

  const refreshAfterSession = async () => {
    await Promise.all([weeklyReport.reload(), currentSession.reload(), prediction.reload()]);
  };

  return (
    <MobileScreen title="학습리포트" showBackButton>
      <ScreenState query={weeklyReport} loadingLabel="학습 리포트를 불러오는 중입니다">
        <>
          <div className="mobile-report__summary mobile-section">
            <div className="mobile-card mobile-report__summary-card">
              <p className="mobile-card__meta">오늘의 학습 시간</p>
              <p className="mobile-report__stat-value">{formatDuration(report.todaySeconds)}</p>
              <p className="mobile-field__hint">종료된 개인 학습 시간 기준</p>
            </div>
            <TodoCountCard todos={todos} />
          </div>

          <StudyTimerPanel
            userId={userId}
            currentSession={currentSession}
            onSessionFinished={refreshAfterSession}
          />

          <WeeklyReportSection
            graph={report.graph}
            summary={report.summary}
            attendanceDays={report.attendanceDays}
            prediction={prediction}
          />
        </>
      </ScreenState>
    </MobileScreen>
  );
}
