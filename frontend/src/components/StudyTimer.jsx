import React, { useEffect, useState } from 'react';

export default function StudyTimer({ onTimeUpdate }) {
  const DAILY_GOAL_SECONDS = 2 * 60 * 60;

  const todayKey = new Date().toISOString().slice(0, 10);
  const totalKey = `studyTotal_${todayKey}`;
  const sessionKey = `studySession_${todayKey}`;
  const runningKey = `studyRunning_${todayKey}`;
  const startKey = `studyStart_${todayKey}`;

  const [totalSeconds, setTotalSeconds] = useState(() => {
    return Number(localStorage.getItem(totalKey)) || 0;
  });

  const [sessionSeconds, setSessionSeconds] = useState(() => {
    return Number(localStorage.getItem(sessionKey)) || 0;
  });

  const [isRunning, setIsRunning] = useState(() => {
    return localStorage.getItem(runningKey) === 'true';
  });

  const formatTime = (seconds) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    return `${h}시간 ${m}분 ${s}초`;
  };

  const getCurrentSessionSeconds = () => {
    const savedSession = Number(localStorage.getItem(sessionKey)) || 0;
    const startTime = Number(localStorage.getItem(startKey));

    if (!startTime) return savedSession;

    const elapsed = Math.floor((Date.now() - startTime) / 1000);
    return savedSession + elapsed;
  };

  useEffect(() => {
    onTimeUpdate?.(totalSeconds);
  }, []);

  useEffect(() => {
    if (!isRunning) return;

    const timer = setInterval(() => {
      const currentSession = getCurrentSessionSeconds();
      setSessionSeconds(currentSession);

      // 실행 중에는 sessionKey 저장하지 않음
      // 저장하면 savedSession + elapsed가 중복 누적됨
    }, 1000);

    return () => clearInterval(timer);
  }, [isRunning]);

  const handleStart = () => {
    if (isRunning) return;

    localStorage.setItem(startKey, String(Date.now()));
    localStorage.setItem(runningKey, 'true');

    setIsRunning(true);
  };

  const handlePause = () => {
    const currentSession = getCurrentSessionSeconds();

    localStorage.setItem(sessionKey, String(currentSession));
    localStorage.removeItem(startKey);
    localStorage.setItem(runningKey, 'false');

    setSessionSeconds(currentSession);
    setIsRunning(false);
  };

  const handleFinish = () => {
    const currentSession = isRunning ? getCurrentSessionSeconds() : sessionSeconds;

    if (currentSession <= 0) return;

    const nextTotal = totalSeconds + currentSession;

    localStorage.setItem(totalKey, String(nextTotal));
    localStorage.setItem(sessionKey, '0');
    localStorage.removeItem(startKey);
    localStorage.setItem(runningKey, 'false');

    setTotalSeconds(nextTotal);
    setSessionSeconds(0);
    setIsRunning(false);

    onTimeUpdate?.(nextTotal);
  };

  const progress = Math.min((sessionSeconds / DAILY_GOAL_SECONDS) * 100, 100);
  const isFinishDisabled = sessionSeconds === 0 && !isRunning;

  return (
    <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>현재 공부 시간</h3>

        <button
          className="btn-outline"
          style={{
            width: 'auto',
            height: '32px',
            padding: '0 10px',
            fontSize: '12px',
          }}
        >
          설정
        </button>
      </div>

      <div style={{ marginTop: '18px', fontSize: '26px', fontWeight: 700 }}>
        {formatTime(sessionSeconds)}
        <span style={{ color: 'var(--color-text-muted)', fontWeight: 500 }}>
          {' '} / 2시간 0분
        </span>
      </div>

      <div
        style={{
          marginTop: '8px',
          fontSize: '14px',
          color: 'var(--color-text-muted)',
        }}
      >
        종료를 누르면 오늘의 학습 시간에 누적됩니다.
      </div>

      <div
        style={{
          height: '10px',
          backgroundColor: 'var(--color-border)',
          borderRadius: '999px',
          marginTop: '14px',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${progress}%`,
            height: '100%',
            backgroundColor: 'var(--color-primary)',
            borderRadius: '999px',
            transition: 'width 0.2s ease',
          }}
        />
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '10px',
          marginTop: '18px',
        }}
      >
        {isRunning ? (
          <button className="btn-outline" onClick={handlePause}>
            정지
          </button>
        ) : (
          <button className="btn-primary" onClick={handleStart}>
            시작
          </button>
        )}

        <button
          className="btn-primary"
          onClick={handleFinish}
          disabled={isFinishDisabled}
        >
          종료
        </button>
      </div>
    </div>
  );
}