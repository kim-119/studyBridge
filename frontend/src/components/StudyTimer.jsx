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

  const toSeoulLocalDateTime = (date) => {
    const seoulString = date.toLocaleString('sv', { timeZone: 'Asia/Seoul' });
    return seoulString.replace(' ', 'T');
  };

  const loadTimerData = async () => {
    try {
      // 1. 당일 총 공부 시간 계산
      const history = await timerService.getTimerHistory(userId);
      const today = new Date().toLocaleString('sv', { timeZone: 'Asia/Seoul' }).slice(0, 10);
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
        const serverTimeStr = current.startTime;
        const parsedTime = new Date(serverTimeStr).getTime();
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

  const handleStart = async () => {
    if (isRunning || !userId) return;

    try {
      const startTime = toSeoulLocalDateTime(new Date());
      const res = await timerService.startTimer(userId, startTime);
      setIsRunning(true);
      setSessionStartTime(Date.now());
      setSessionSeconds(0);
    } catch (err) {
      alert('타이머 시작에 실패했습니다.');
    }
  };

  const handleFinish = async () => {
    if (!isRunning || !userId) return;

    try {
      const endTime = toSeoulLocalDateTime(new Date());
      const durationSeconds = sessionSeconds;
      await timerService.endTimer(userId, endTime, durationSeconds);
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
    <div
      className="animate-fade-in"
      style={{
        backgroundColor: '#FFFFFF',
        border: '1px solid #E5E7EB',
        borderRadius: '16px',
        boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
        padding: '24px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: '#111827' }}>현재 공부 시간</h3>
      </div>

      <div style={{ marginTop: '12px', fontSize: '32px', fontWeight: 800, color: '#22C55E', letterSpacing: '-0.5px' }}>
        {formatTime(sessionSeconds)}
      </div>

      <div style={{ marginTop: '6px', fontSize: '13px', color: '#6B7280' }}>
        종료를 누르면 오늘의 학습 시간에 누적됩니다.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginTop: '18px' }}>
        {/* Primary: 시작 */}
        <button
          onClick={handleStart}
          disabled={isRunning}
          style={{
            height: '48px', borderRadius: '10px', border: 'none',
            backgroundColor: isRunning ? '#A7F3C0' : '#22C55E',
            color: '#FFFFFF', fontSize: '15px', fontWeight: 700,
            cursor: isRunning ? 'not-allowed' : 'pointer',
            transition: 'background-color 0.2s ease',
          }}
        >
          {isRunning ? '진행중' : '시작'}
        </button>

        {/* Secondary: 종료 */}
        <button
          onClick={handleFinish}
          disabled={isFinishDisabled}
          style={{
            height: '48px', borderRadius: '10px',
            backgroundColor: '#FFFFFF', border: '1px solid #22C55E',
            color: '#16A34A', fontSize: '15px', fontWeight: 700,
            cursor: isFinishDisabled ? 'not-allowed' : 'pointer',
            opacity: isFinishDisabled ? 0.5 : 1,
            transition: 'all 0.2s ease',
          }}
        >
          종료
        </button>
      </div>
    </div>
  );
}