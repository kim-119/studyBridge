import React, { useEffect, useState } from 'react';
import Button from '../../components/Button';
import { ErrorState, LoadingState } from '../../components/ScreenState';
import { timerService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import { formatDuration, runningSessionStart, toSeoulLocalDateTime } from './reportStats';

function elapsedSecondsSince(startedAt) {
  return Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
}

function useElapsedSeconds(startedAt) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) {
      setElapsed(0);
      return undefined;
    }

    setElapsed(elapsedSecondsSince(startedAt));
    const timer = setInterval(() => setElapsed(elapsedSecondsSince(startedAt)), 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  return elapsed;
}

export default function StudyTimerPanel({ userId, currentSession, onSessionFinished }) {
  const [startedAt, setStartedAt] = useState(null);
  const elapsed = useElapsedSeconds(startedAt);
  const isRunning = Boolean(startedAt);

  useEffect(() => {
    setStartedAt(runningSessionStart(currentSession.data));
  }, [currentSession.data]);

  const startTimer = useSubmit(async () => {
    await timerService.startTimer(userId, toSeoulLocalDateTime(new Date()));
    setStartedAt(Date.now());
  });

  const finishTimer = useSubmit(async () => {
    const durationSeconds = elapsedSecondsSince(startedAt);
    await timerService.endTimer(userId, toSeoulLocalDateTime(new Date()), durationSeconds);
    setStartedAt(null);
    await onSessionFinished();
  });

  const actionError = startTimer.errorMessage || finishTimer.errorMessage;

  if (currentSession.isLoading && currentSession.data == null) {
    return <LoadingState label="타이머를 불러오는 중입니다" />;
  }

  if (currentSession.isError) {
    return <ErrorState message={currentSession.errorMessage} onRetry={currentSession.reload} />;
  }

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">현재 공부 시간</p>
      <p className="mobile-report__timer">{formatDuration(elapsed)}</p>
      <p className="mobile-field__hint">종료를 누르면 오늘의 학습 시간에 누적됩니다.</p>

      {actionError && <p className="mobile-auth__error">{actionError}</p>}

      <div className="mobile-report__timer-actions">
        <Button
          isLoading={startTimer.isSubmitting}
          disabled={isRunning}
          onClick={() => startTimer.submit().catch(() => {})}
        >
          {isRunning ? '진행중' : '시작'}
        </Button>
        <Button
          variant="secondary"
          isLoading={finishTimer.isSubmitting}
          disabled={!isRunning}
          onClick={() => finishTimer.submit().catch(() => {})}
        >
          종료
        </Button>
      </div>
    </section>
  );
}
