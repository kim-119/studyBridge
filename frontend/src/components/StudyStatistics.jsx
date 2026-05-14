import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { studyTimeService, activityService, timerService } from '../services/api';
import StudyChart from '../components/StudyChart';

const formatDuration = (seconds) => {
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

const minutesToDuration = (minutes) => {
  return formatDuration(Math.round((minutes || 0) * 60));
};

export default function StudyStatistics({ todayStudySeconds = 0 }) {
  // ✅ 1. 모든 Hook은 반드시 여기(최상단)에 모여 있어야 함!
  const { user, userId } = useAuth(); // 👈 함수 밖으로 절대 나가면 안 됨

  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isEmpty, setIsEmpty] = useState(false);
  const [weeklyStats, setWeeklyStats] = useState(null);
  const [graphData, setGraphData] = useState([]);
  const [baseRawData, setBaseRawData] = useState([]);
  const [weeklySecondsMap, setWeeklySecondsMap] = useState({});

  // ✅ 2. 유저 ID 계산 로직
  const effectiveUserId = useMemo(() => {
    return user?.id || userId || localStorage.getItem("userId");
  }, [user?.id, userId]);

  // ✅ 3. 데이터 로딩 함수 (내부에서 Hook 호출 금지!)
  const loadData = useCallback(async () => {
    if (!effectiveUserId) return;

    try {
      setIsLoading(true);
      setError(null);
      setIsEmpty(false);

      // Spring Boot 데이터 호출
      const weeklyResult = await studyTimeService.getWeekly(effectiveUserId);

      // ✨ 프론트엔드 정밀 교정 2탄: 과거 요일의 '초' 데이터도 정확하게 반영하기 위해 모든 타이머 히스토리를 불러와서 주간 초를 직접 계산합니다.
      const timerHistory = await timerService.getTimerHistory(effectiveUserId);

      // 이번 주 월요일 ~ 일요일 범위 계산
      const now = new Date();
      const currentDay = now.getDay();
      const diffToMonday = now.getDate() - currentDay + (currentDay === 0 ? -6 : 1);
      const startOfWeek = new Date(now);
      startOfWeek.setDate(diffToMonday);
      startOfWeek.setHours(0, 0, 0, 0);

      const endOfWeek = new Date(startOfWeek);
      endOfWeek.setDate(startOfWeek.getDate() + 6);
      endOfWeek.setHours(23, 59, 59, 999);

      const tempWeeklySecondsMap = {};
      const dayNames = ['일', '월', '화', '수', '목', '금', '토'];

      if (Array.isArray(timerHistory)) {
        timerHistory.forEach(timer => {
          if (timer.status === 'COMPLETED' && timer.startTime && timer.endTime) {
            const sTime = new Date(timer.startTime);
            const eTime = new Date(timer.endTime);
            if (eTime >= startOfWeek && eTime <= endOfWeek) {
              const diffSeconds = (eTime.getTime() - sTime.getTime()) / 1000;
              const dayName = dayNames[eTime.getDay()];
              tempWeeklySecondsMap[dayName] = (tempWeeklySecondsMap[dayName] || 0) + diffSeconds;
            }
          }
        });
      }
      setWeeklySecondsMap(tempWeeklySecondsMap);

      console.log("StudyStatistics loadData weeklyResult:", weeklyResult);
      let rawData = Array.isArray(weeklyResult) 
        ? weeklyResult 
        : (weeklyResult?.dailyStats || []);
        
      setBaseRawData(rawData);

      if (!Array.isArray(rawData) || rawData.length === 0) {
        setGraphData([]);
        setWeeklyStats(null);
        setIsEmpty(true);
        return;
      }

      setGraphData(rawData); // 초기값 설정

      // FastAPI 데이터 호출 (백엔드 DailyStudyTime DTO의 hours 필드에 맞춰 변환)
      const payload = {
        user_id: Number(effectiveUserId),
        data: rawData.map(item => ({
          day: item.day,
          hours: Number((item.minutes || 0) / 60)
        })),
      };
      const graphResult = await activityService.getWeeklyGraph(payload);
      console.log("StudyStatistics loadData graphResult:", graphResult);

      if (graphResult && Object.keys(graphResult).length > 0) {
        setWeeklyStats(graphResult);
      } else {
        setWeeklyStats(null);
      }

    } catch (err) {
      console.error("StudyStatistics loadData error:", err);
      setError("학습 통계를 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [effectiveUserId]);

  // ✅ 4. 실행
  useEffect(() => {
    if (effectiveUserId) {
      loadData();
    }
  }, [effectiveUserId, loadData]);

  // ✅ 5. todayStudySeconds 변경 시 그래프 데이터만 로컬로 업데이트
  useEffect(() => {
    if (!baseRawData.length) {
      setGraphData([]);
      return;
    }

    const todayDayName = new Date().toLocaleDateString('ko-KR', { weekday: 'short' });
    const dayMap = {'MONDAY':'월', 'TUESDAY':'화', 'WEDNESDAY':'수', 'THURSDAY':'목', 'FRIDAY':'금', 'SATURDAY':'토', 'SUNDAY':'일'};

    const updatedData = baseRawData.map(item => {
      // item.day가 MONDAY 같은 영어일 경우 한글로 매핑, 이미 한글이면 그대로 사용
      const koreanDay = dayMap[item.day] || item.day;
      let exactSeconds = weeklySecondsMap[koreanDay] || 0;
      
      // 오늘은 진행 중인 타이머가 포함된 가장 정확한 todayStudySeconds를 우선 사용
      if (koreanDay === todayDayName && todayStudySeconds > 0) {
        exactSeconds = Math.max(exactSeconds, todayStudySeconds); // 혹은 todayStudySeconds 자체를 사용
      }
      
      return {
        ...item,
        day: koreanDay,
        seconds: exactSeconds,
        minutes: exactSeconds / 60
      };
    });

    setGraphData(updatedData);
  }, [baseRawData, weeklySecondsMap, todayStudySeconds]);

  return (
    <div className="statistics-page-container">
      <section className="stats-section animate-fade-in glass-panel" style={{
        padding: '24px',
        borderRadius: '16px',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.05)',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
        minHeight: '550px', // 전체 최소 높이 고정
        overflow: 'hidden'
      }}>

        <h2 style={{ margin: 0 }}>주간 학습 리포트</h2>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', flex: 1 }}>
          {/* 상단 통계 요약 영역: 데이터가 없어도 공간 유지 */}
          <div style={{
            minHeight: '84px', // 통계 요약 바의 고정 높이
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#F9FAFB',
            borderRadius: '12px',
            padding: '16px'
          }}>
            {!effectiveUserId ? (
              <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>로그인 후 이용 가능합니다.</p>
            ) : isLoading ? (
              <div style={{ display: 'flex', gap: '16px', width: '100%', opacity: 0.5 }}>
                <div style={{ flex: 1, height: '20px', backgroundColor: '#E5E7EB', borderRadius: '4px' }}></div>
                <div style={{ flex: 1, height: '20px', backgroundColor: '#E5E7EB', borderRadius: '4px' }}></div>
                <div style={{ flex: 1, height: '20px', backgroundColor: '#E5E7EB', borderRadius: '4px' }}></div>
              </div>
            ) : error || isEmpty || graphData.length === 0 ? (
              <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>
                {error ? error : "주간 학습 기록이 없습니다."}
              </p>
            ) : (() => {
              // ✅ 실시간 통계 계산 (FastAPI 결과를 기다리지 않고 graphData 기준으로 계산)
              const totalMinutes = graphData.reduce((acc, cur) => acc + (cur.minutes || 0), 0);
              const avgMinutes = totalMinutes / 7;
              
              // 집중 요일 계산
              let maxMin = -1;
              let maxDay = "없음";
              graphData.forEach(item => {
                if ((item.minutes || 0) > maxMin && (item.minutes || 0) > 0) {
                  maxMin = item.minutes;
                  maxDay = item.day;
                }
              });

              return (
                <div style={{ display: 'flex', gap: '16px', width: '100%', flexWrap: 'nowrap', alignItems: 'center' }}>
                  <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                    <div style={{ padding: '8px', backgroundColor: '#E0F2FE', borderRadius: '8px', color: '#0284C7', flexShrink: 0 }}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '2px', whiteSpace: 'nowrap' }}>총 시간</div>
                      <div style={{ fontSize: '15px', fontWeight: 'bold', color: 'var(--color-text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {minutesToDuration(totalMinutes)}
                      </div>
                    </div>
                  </div>

                  <div style={{ width: '1px', height: '30px', backgroundColor: '#E5E7EB', flexShrink: 0 }}></div>

                  <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                    <div style={{ padding: '8px', backgroundColor: '#FEF3C7', borderRadius: '8px', color: '#D97706', flexShrink: 0 }}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18" /><path d="m19 9-5 5-4-4-3 3" /></svg>
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '2px', whiteSpace: 'nowrap' }}>평균 시간</div>
                      <div style={{ fontSize: '15px', fontWeight: 'bold', color: 'var(--color-text-main)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {minutesToDuration(avgMinutes)}
                      </div>
                    </div>
                  </div>

                  <div style={{ width: '1px', height: '30px', backgroundColor: '#E5E7EB', flexShrink: 0 }}></div>

                  <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px', minWidth: 0 }}>
                    <div style={{ padding: '8px', backgroundColor: '#DCFCE7', borderRadius: '8px', color: '#16A34A', flexShrink: 0 }}>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z" /></svg>
                    </div>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '2px', whiteSpace: 'nowrap' }}>집중 요일</div>
                      <div style={{ fontSize: '15px', fontWeight: 'bold', color: 'var(--color-text-main)', whiteSpace: 'nowrap' }}>
                        {maxDay}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })()}
          </div>

          {/* 차트 영역: 데이터 유무에 관계없이 350px 고정 */}
          <div style={{ height: '350px', width: '100%', position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            {effectiveUserId && isLoading ? (
              <div style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>통계 데이터를 분석 중입니다...</div>
            ) : effectiveUserId ? (
              <StudyChart rawData={graphData} />
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}