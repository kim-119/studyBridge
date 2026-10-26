import React from 'react';
import { EmptyState } from '../../components/ScreenState';
import WeeklyStudyChart from './WeeklyStudyChart';
import { formatDuration } from './reportStats';

function StatTile({ label, value, children }) {
  return (
    <div className="mobile-report__stat">
      <p className="mobile-card__meta">{label}</p>
      <p className="mobile-report__stat-value">{value}</p>
      {children}
    </div>
  );
}

function PredictionTile({ prediction }) {
  if (prediction.isLoading && prediction.data == null) {
    return <StatTile label="내일 예측" value="불러오는 중" />;
  }

  if (prediction.isError) {
    return (
      <StatTile label="내일 예측" value="-">
        <p className="mobile-field__error">{prediction.errorMessage}</p>
        <button type="button" className="mobile-report__retry" onClick={prediction.reload}>
          다시 시도
        </button>
      </StatTile>
    );
  }

  if (!prediction.data) return <StatTile label="내일 예측" value="-" />;

  return (
    <StatTile label="내일 예측" value={formatDuration(prediction.data.predictedSeconds)}>
      {prediction.data.message && <p className="mobile-field__hint">{prediction.data.message}</p>}
    </StatTile>
  );
}

export default function WeeklyReportSection({ graph, summary, attendanceDays, prediction }) {
  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">주간 학습 리포트</h3>

      {summary.hasRecords ? (
        <>
          <div className="mobile-report__stats">
            <StatTile label="총 시간" value={formatDuration(summary.totalSeconds)} />
            <StatTile label="평균 시간" value={formatDuration(summary.averageSeconds)} />
            <StatTile label="집중 요일" value={summary.focusDay} />
            <StatTile label="학습일수" value={attendanceDays == null ? '-' : `${attendanceDays}일`} />
            <PredictionTile prediction={prediction} />
          </div>
          <WeeklyStudyChart graph={graph} />
        </>
      ) : (
        <EmptyState message="주간 학습 기록이 없습니다." />
      )}
    </section>
  );
}
