import React, { useEffect, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { timerService } from '../services/api';

export default function StudyTimer({ onTimeUpdate }) {
  const { userId } = useAuth();

  const [totalSeconds, setTotalSeconds] = useState(0);
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [isRunning, setIsRunning] = useState(false);
  const [sessionStartTime, setSessionStartTime] = useState(null);

  useEffect(() => {
    if (userId) {
      loadTimerData();
    } else {
      setTotalSeconds(0);
      setSessionSeconds(0);
      setIsRunning(false);
      setSessionStartTime(null);
    }
  }, [userId]);

  // 부모 컴포넌트에 총 공부 시간 업데이트
  useEffect(() => {
    onTimeUpdate?.(totalSeconds);
  }, [totalSeconds]);

  const loadTimerData = async () => {
    try {
      // 1. 당일 총 공부 시간 계산
      const history = await timerService.getTimerHistory(userId);
      const today = new Date().toISOString().slice(0, 10);
      let total = 0;
      
      if (history && Array.isArray(history)) {
        history.forEach(session => {
          if (session.startTime && session.endTime && session.startTime.startsWith(today)) {
            const start = new Date(session.startTime).getTime();
            const end = new Date(session.endTime).getTime();
            total += Math.floor((end - start) / 1000);
          }
        });
      }
      setTotalSeconds(total);

      // 2. 현재 실행 중인 세션 확인
      const current = await timerService.getCurrentSession(userId);
      if (current && current.startTime && !current.endTime) {
        setIsRunning(true);
        // 서버에서 온 startTime(KST 등 timezone offset이 없는 UTC 형태) 파싱 시 발생하는 9시간 오차 방지
        const serverTimeStr = current.startTime;
        const parsedTime = new Date(serverTimeStr.endsWith('Z') ? serverTimeStr : serverTimeStr + 'Z').getTime();
        setSessionStartTime(parsedTime);
        setSessionSeconds(Math.floor((Date.now() - parsedTime) / 1000));
      } else {
        setIsRunning(false);
        setSessionStartTime(null);
        setSessionSeconds(0);
      }
    } catch (err) {
      console.error('타이머 데이터 로드 실패:', err);
    }
  };

  useEffect(() => {
    if (!isRunning || !sessionStartTime) return;

    const timer = setInterval(() => {
      setSessionSeconds(Math.floor((Date.now() - sessionStartTime) / 1000));
    }, 1000);

    return () => clearInterval(timer);
  }, [isRunning, sessionStartTime]);

  const formatTime = (seconds) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;

    return `${h}시간 ${m}분 ${s}초`;
  };

  const handleStart = async () => {
    if (isRunning || !userId) return;

    try {
      const startTime = new Date().toISOString();
      const res = await timerService.startTimer(userId, startTime);
      setIsRunning(true);
      // 클라이언트에서 바로 시작 누른 시점을 Date.now()로 기록 (9시간 파싱 오류 원천 차단)
      setSessionStartTime(Date.now());
      setSessionSeconds(0);
    } catch (err) {
      alert('타이머 시작에 실패했습니다.');
    }
  };

  const handleFinish = async () => {
    if (!isRunning || !userId) return;

    try {
      const endTime = new Date().toISOString();
      const durationMinutes = Math.floor(sessionSeconds / 60);
      await timerService.endTimer(userId, endTime, durationMinutes);
      setIsRunning(false);
      setSessionStartTime(null);
      setSessionSeconds(0);
      // 타이머 종료 후 당일 총 공부 시간을 다시 불러옴
      await loadTimerData();
    } catch (err) {
      alert('타이머 종료에 실패했습니다.');
    }
  };

  const isFinishDisabled = !isRunning;

  return (
    <div className="glass-panel animate-fade-in" style={{ padding: '20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>현재 공부 시간</h3>
      </div>

      <div style={{ marginTop: '16px', fontSize: '28px', fontWeight: 700, color: 'var(--color-primary)' }}>
        {formatTime(sessionSeconds)}
      </div>

      <div
        style={{
          marginTop: '6px',
          fontSize: '13px',
          color: 'var(--color-text-muted)',
        }}
      >
        종료를 누르면 오늘의 학습 시간에 누적됩니다.
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '10px',
          marginTop: '18px',
        }}
      >
        <button 
          className="btn-primary" 
          onClick={handleStart}
          disabled={isRunning}
          style={{ opacity: isRunning ? 0.5 : 1 }}
        >
          {isRunning ? '진행중' : '시작'}
        </button>

        <button
          className="btn-primary"
          onClick={handleFinish}
          disabled={isFinishDisabled}
          style={{ backgroundColor: isFinishDisabled ? '#ccc' : 'var(--color-danger)', border: 'none' }}
        >
          종료
        </button>
      </div>
    </div>
  );
}