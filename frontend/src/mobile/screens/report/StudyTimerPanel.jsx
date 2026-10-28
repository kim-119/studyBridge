import React, { useEffect, useRef, useState } from 'react';
import Button from '../../components/Button';
import { ErrorState, LoadingState } from '../../components/ScreenState';
import { timerService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import { useReloadWhenVisible } from '../knowledge/useReloadWhenVisible';
import { formatDuration, toSeoulLocalDateTime } from './reportStats';
import {
  SESSION_KIND,
  STUDY_HEARTBEAT_INTERVAL_MS,
  checkRunningSession,
  describeRunningSession,
  elapsedSecondsOf,
  sessionFromServer,
} from './studySessionModel';

function useElapsedSeconds(running) {
  const [elapsed, setElapsed] = useState(() => elapsedSecondsOf(running));

  useEffect(() => {
    setElapsed(elapsedSecondsOf(running));
    if (!running) return undefined;

    const timer = setInterval(() => setElapsed(elapsedSecondsOf(running)), 1000);
    return () => clearInterval(timer);
  }, [running]);

  return elapsed;
}

// 실행 중 30초 주기: 개인 세션은 heartbeat, 그룹 세션은 조회만. 서버가 다른 상태를 돌려주면 서버 기준으로 다시 불러온다.
function useSessionHeartbeat(running, onSessionChanged) {
  const latestOnChanged = useRef(onSessionChanged);
  latestOnChanged.current = onSessionChanged;

  useEffect(() => {
    if (!running) return undefined;

    let isCancelled = false;
    const tick = async () => {
      try {
        const isSame = await checkRunningSession(running, {
          heartbeat: () => timerService.heartbeat(),
          getCurrentSession: () => timerService.getCurrentSession(),
        });
        if (!isSame && !isCancelled) await latestOnChanged.current();
      } catch {
        // 네트워크 오류는 다음 주기에 재시도한다. 서버는 heartbeat 가 90초 끊기면 마지막 heartbeat 시각으로 종료한다.
      }
    };

    const timer = setInterval(tick, STUDY_HEARTBEAT_INTERVAL_MS);
    return () => {
      isCancelled = true;
      clearInterval(timer);
    };
  }, [running]);
}

export default function StudyTimerPanel({ userId, currentSession, onSessionFinished }) {
  const [running, setRunning] = useState(null);
  const elapsed = useElapsedSeconds(running);
  const isPersonalRunning = running?.kind === SESSION_KIND.PERSONAL;

  useEffect(() => {
    setRunning(sessionFromServer(currentSession.data));
  }, [currentSession.data]);

  useEffect(() => {
    if (!userId) setRunning(null);
  }, [userId]);

  // 백그라운드 복귀·재연결 시 서버 상태로 복원한다(그 사이 자동 종료됐으면 화면도 멈춘다).
  useReloadWhenVisible(currentSession.reload);
  useSessionHeartbeat(running, currentSession.reload);

  const startTimer = useSubmit(async () => {
    const started = await timerService.startTimer(userId, toSeoulLocalDateTime(new Date()), {
      supportsHeartbeat: true,
    });
    setRunning(sessionFromServer(started));
    currentSession.reload().catch(() => {});
  });

  const finishTimer = useSubmit(async () => {
    await timerService.endTimer(userId, toSeoulLocalDateTime(new Date()), elapsed, 'USER_STOP');
    setRunning(null);
    await onSessionFinished();
  });

  const actionError = startTimer.errorMessage || finishTimer.errorMessage;
  const isBusy = startTimer.isSubmitting || finishTimer.isSubmitting;

  if (currentSession.isLoading && currentSession.data == null) {
    return <LoadingState label="타이머를 불러오는 중입니다" />;
  }

  if (currentSession.isError) {
    return <ErrorState message={currentSession.errorMessage} onRetry={currentSession.reload} />;
  }

  return (
    <section className="mobile-card mobile-section" data-session-kind={running?.kind || 'idle'}>
      <p className="mobile-card__meta">
        {running?.kind === SESSION_KIND.GROUP ? '그룹 스터디 진행 시간' : '현재 공부 시간'}
      </p>
      <p className="mobile-report__timer">{formatDuration(elapsed)}</p>
      <p className="mobile-field__hint">{describeRunningSession(running)}</p>

      {actionError && <p className="mobile-auth__error">{actionError}</p>}

      <div className="mobile-report__timer-actions">
        <Button
          isLoading={startTimer.isSubmitting}
          disabled={isPersonalRunning || isBusy}
          onClick={() => startTimer.submit().catch(() => {})}
        >
          {isPersonalRunning ? '진행중' : '시작'}
        </Button>
        <Button
          variant="secondary"
          isLoading={finishTimer.isSubmitting}
          disabled={!isPersonalRunning || isBusy}
          onClick={() => finishTimer.submit().catch(() => {})}
        >
          종료
        </Button>
      </div>
    </section>
  );
}
