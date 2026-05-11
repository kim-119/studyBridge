import React, { useEffect, useState, useMemo, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { studyTimeService, activityService } from '../services/api';

const formatHoursReadable = (hours) => {
  const h = Number(hours || 0);
  return `${h.toFixed(2)} 시간`;
};

export default function StudyStatistics() {
  const { user, userId } = useAuth();
  
  const [graphBase64, setGraphBase64] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isEmpty, setIsEmpty] = useState(false);
  const [weeklyStats, setWeeklyStats] = useState(null);

  const effectiveUserId = useMemo(() => {
    return user?.id || userId || localStorage.getItem("userId");
  }, [user?.id, userId]);

  const loadData = useCallback(async () => {
    if (!effectiveUserId) return;

    try {
      setIsLoading(true);
      setError(null);
      setIsEmpty(false);

      const weeklyResult = await studyTimeService.getWeekly(effectiveUserId);
      const weeklyData = weeklyResult.data || [];

      if (weeklyData.length === 0) {
        setIsEmpty(true);
        return;
      }

      let totalMinutes = 0;
      const graphData = weeklyData.map((item) => {
        totalMinutes += item.minutes || 0;
        return {
          day: item.day,
          minutes: Number(item.minutes || 0)  // Spring 원본 minutes 그대로 전달 → 막대 높이 정상 렌더링
        };
      });

      if (totalMinutes === 0) {
        setIsEmpty(true);
        return;
      }

      const payload = {
        user_id: Number(effectiveUserId),
        data: graphData,
      };

      const graphResult = await activityService.getWeeklyGraph(payload);
      console.log("FastAPI response keys:", Object.keys(graphResult || {}));
      console.log("graph_base64 type:", typeof graphResult?.graph_base64, "length:", graphResult?.graph_base64?.length);

      const base64 = 
        graphResult?.graph_base64 || 
        graphResult?.graphBase64 || 
        graphResult?.image_base64 || 
        graphResult?.image;

      setWeeklyStats(graphResult);

      if (!base64) {
        console.error("base64 not found in response", graphResult);
        setError("그래프 응답 데이터가 올바르지 않습니다.");
        return;
      }

      setGraphBase64(base64);
    } catch (err) {
      console.error("StudyStatistics loadData error:", err);
      setError("학습 통계를 불러오지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  }, [effectiveUserId]);

  useEffect(() => {
    if (!effectiveUserId) return;
    loadData();
  }, [effectiveUserId, loadData]);

  const imageSrc = graphBase64
    ? `data:image/png;base64,${graphBase64}`
    : "";

  return (
    <>
      <section className="stats-section animate-fade-in">
        <h2>학습통계</h2>

        {!effectiveUserId ? (
          <p style={{ color: "#666" }}>로그인 후 주간 학습 통계를 확인할 수 있습니다.</p>
        ) : isLoading ? (
          <p style={{ color: "#666" }}>로딩 중...</p>
        ) : error ? (
          <p style={{ color: "red" }}>{error}</p>
        ) : isEmpty ? (
          <p style={{ color: "#666" }}>이번 주 학습 데이터가 없습니다.</p>
        ) : graphBase64 ? (
          <div className="graph-container">
            <img
              src={imageSrc}
              alt="주간 학습 시간 그래프"
              className="graph-image"
              onLoad={(e) => console.log("img rendered:", e.currentTarget.naturalWidth, "x", e.currentTarget.naturalHeight)}
            />
          </div>
        ) : null}
      </section>

      {weeklyStats && (
        <section className="stats-section animate-fade-in">
          <div className="summary-box">
            <h3 className="summary-title">학습 요약</h3>
            <ul className="summary-list">
              <li>총 학습 시간: {formatHoursReadable(weeklyStats.total_hours)}</li>
              <li>평균 학습 시간: {formatHoursReadable(weeklyStats.average_hours)}</li>
              <li>출석일: {weeklyStats.attendance_days || 0} 일</li>
              <li>가장 많이 공부한 날: {weeklyStats.max_study_day ? `${weeklyStats.max_study_day} / ${formatHoursReadable(weeklyStats.max_study_hours)}` : "없음"}</li>
            </ul>
          </div>
        </section>
      )}
    </>
  );
}
