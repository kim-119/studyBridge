import React, { useEffect, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import Button from '../../components/Button';
import { timerService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';

function formatDuration(seconds) {
  const safe = Math.max(0, Math.floor(seconds));
  const hours = String(Math.floor(safe / 3600)).padStart(2, '0');
  const minutes = String(Math.floor((safe % 3600) / 60)).padStart(2, '0');
  const rest = String(safe % 60).padStart(2, '0');
  return `${hours}:${minutes}:${rest}`;
}

function startedAtOf(session) {
  const raw = session?.startTime || session?.startedAt;
  if (!raw) return null;
  const parsed = new Date(raw).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

export default function StudyTimerCard({ groupId }) {
  const { userId } = useAuth();
  const [startedAt, setStartedAt] = useState(null);
  const [elapsed, setElapsed] = useState(0);
  const tickRef = useRef(null);

  const current = useAsync(() => timerService.getCurrentSession(userId), [userId]);

  useEffect(() => {
    const resumed = startedAtOf(current.data);
    if (resumed) setStartedAt(resumed);
  }, [current.data]);

  useEffect(() => {
    if (!startedAt) {
      clearInterval(tickRef.current);
      setElapsed(0);
      return undefined;
    }

    const tick = () => setElapsed((Date.now() - startedAt) / 1000);
    tick();
    tickRef.current = setInterval(tick, 1000);

    return () => clearInterval(tickRef.current);
  }, [startedAt]);

  const startTimer = useSubmit(async () => {
    const now = new Date();
    await timerService.startTimer(userId, now.toISOString());
    await timerService.syncTimer(groupId).catch(() => {});
    setStartedAt(now.getTime());
  });

  const stopTimer = useSubmit(async () => {
    const now = new Date();
    const durationSeconds = startedAt ? Math.round((now.getTime() - startedAt) / 1000) : 0;
    await timerService.endTimer(userId, now.toISOString(), durationSeconds);
    setStartedAt(null);
    await current.reload();
  });

  const isRunning = Boolean(startedAt);
  const action = isRunning ? stopTimer : startTimer;

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">스터디 진행 시간</p>
      <p className="mobile-stat">{formatDuration(elapsed)}</p>

      <Button
        fullWidth
        variant={isRunning ? 'secondary' : 'primary'}
        isLoading={action.isSubmitting}
        onClick={() => action.submit().catch(() => {})}
      >
        {isRunning ? <Pause size={16} /> : <Play size={16} />}
        {isRunning ? '타이머 정지' : '타이머 시작'}
      </Button>

      {action.errorMessage && <p className="mobile-auth__error">{action.errorMessage}</p>}
    </section>
  );
}
