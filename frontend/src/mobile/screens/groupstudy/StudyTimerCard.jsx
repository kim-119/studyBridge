import React, { useEffect, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import Button from '../../components/Button';
import { timerService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { describeApiError, useAsync, useSubmit } from '../../data/useAsync';
import { toSeoulLocalDateTime } from '../report/reportStats';
import { formatElapsed } from './groupStudyModel';

const TICK_MS = 1000;

function startedAtOf(session) {
  const raw = session?.startTime || session?.startedAt;
  if (!raw) return null;
  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function useElapsedSince(startedAt) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!startedAt) {
      setElapsed(0);
      return undefined;
    }

    const tick = () => setElapsed((Date.now() - startedAt) / 1000);
    tick();
    const timer = setInterval(tick, TICK_MS);
    return () => clearInterval(timer);
  }, [startedAt]);

  return elapsed;
}

export default function StudyTimerCard({ groupId }) {
  const { userId } = useAuth();
  const [startedAt, setStartedAt] = useState(null);
  const [syncErrorMessage, setSyncErrorMessage] = useState(null);
  const elapsed = useElapsedSince(startedAt);

  const current = useAsync(() => timerService.getCurrentSession(userId), [userId]);

  useEffect(() => {
    const resumed = startedAtOf(current.data);
    if (resumed) setStartedAt(resumed);
  }, [current.data]);

  const syncWithGroup = async () => {
    setSyncErrorMessage(null);
    try {
      await timerService.syncTimer(groupId);
    } catch (error) {
      setSyncErrorMessage(`그룹 타이머 동기화에 실패했습니다. ${describeApiError(error)}`);
    }
  };

  const startTimer = useSubmit(async () => {
    const now = new Date();
    await timerService.startTimer(userId, toSeoulLocalDateTime(now));
    setStartedAt(now.getTime());
    await syncWithGroup();
  });

  const stopTimer = useSubmit(async () => {
    const now = new Date();
    const durationSeconds = startedAt ? Math.round((now.getTime() - startedAt) / 1000) : 0;
    await timerService.endTimer(userId, toSeoulLocalDateTime(now), durationSeconds);
    setStartedAt(null);
    await current.reload();
  });

  const isRunning = Boolean(startedAt);
  const action = isRunning ? stopTimer : startTimer;
  const errorMessage = action.errorMessage || current.errorMessage || syncErrorMessage;

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">스터디 진행 시간</p>
      <p className="mobile-stat">{formatElapsed(elapsed)}</p>

      <Button
        fullWidth
        variant={isRunning ? 'secondary' : 'primary'}
        isLoading={action.isSubmitting}
        onClick={() => action.submit().catch(() => {})}
      >
        {isRunning ? <Pause size={16} /> : <Play size={16} />}
        {isRunning ? '타이머 정지' : '타이머 시작'}
      </Button>

      {errorMessage && <p className="mobile-auth__error">{errorMessage}</p>}
    </section>
  );
}
