import React, { useEffect, useMemo, useState } from 'react';
import { CalendarPlus } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { describeApiError, useAsync, useSubmit } from '../../../data/useAsync';
import { useBackgroundTask } from '../../../data/useBackgroundTask';
import { PLANNER_TYPE } from '../../planner/plannerAdapter';
import RoadmapDaySheet from '../../roadmap/RoadmapDaySheet';
import RoadmapLegacyWeeks from '../../roadmap/RoadmapLegacyWeeks';
import RoadmapPlannerSheet from '../../roadmap/RoadmapPlannerSheet';
import RoadmapRegenerateCard from '../../roadmap/RoadmapRegenerateCard';
import RoadmapWeekView from '../../roadmap/RoadmapWeekView';
import {
  DEFAULT_ROADMAP_LEVEL,
  ROADMAP_DAYS_REQUIRED_MESSAGE,
  assertRoadmapSucceeded,
  canCreatePlanners,
  findDay,
  firstOpenWeekNumber,
  hasDayStructure,
  normalizeRoadmapWeeks,
  roadmapProgress,
  roadmapRegenerationTaskKey,
  roadmapUsedServerFallback,
  toggleDayInWeeks,
  toggleTaskInWeeks,
} from '../../roadmap/roadmapModel';

function dayKey(weekNumber, dayIndex) {
  return `${weekNumber}-${dayIndex}`;
}

function ProgressCard({ weeks }) {
  const progress = roadmapProgress(weeks);

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">전체 학습 진행률</p>
      <p className="mobile-stat">
        {progress.percent}% <span className="mobile-roadmap__progress-label">({progress.label})</span>
      </p>
      <div
        className="mobile-progress"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress.percent}
      >
        <span style={{ width: `${progress.percent}%` }} />
      </div>
    </section>
  );
}

export default function RoadmapTab({ materialId }) {
  const navigate = useNavigate();
  const [level, setLevel] = useState(DEFAULT_ROADMAP_LEVEL);
  const [weeks, setWeeks] = useState([]);
  const [selectedWeekNumber, setSelectedWeekNumber] = useState(null);
  const [openDayKey, setOpenDayKey] = useState(null);
  const [togglingKey, setTogglingKey] = useState(null);
  const [isPlannerSheetOpen, setPlannerSheetOpen] = useState(false);

  const roadmap = useAsync(
    async () => assertRoadmapSucceeded(await materialService.getRoadmap(materialId)),
    [materialId]
  );

  useEffect(() => {
    setWeeks(roadmap.data ? normalizeRoadmapWeeks(roadmap.data) : []);
  }, [roadmap.data]);

  const regeneration = useBackgroundTask(roadmapRegenerationTaskKey(materialId));
  const { isReady: isRegenerated, reset: resetRegeneration } = regeneration;
  const { reload: reloadRoadmap } = roadmap;

  useEffect(() => {
    if (!isRegenerated) return;
    setSelectedWeekNumber(null);
    resetRegeneration();
    reloadRoadmap().catch(() => {});
  }, [isRegenerated, resetRegeneration, reloadRoadmap]);

  const regenerate = () =>
    regeneration.run(async () => assertRoadmapSucceeded(await materialService.regenerateRoadmap(materialId, level)));

  const toggleDay = useSubmit(async (weekNumber, dayIndex) => {
    setTogglingKey(dayKey(weekNumber, dayIndex));
    setWeeks((previous) => toggleDayInWeeks(previous, weekNumber, dayIndex));

    try {
      roadmap.setData(await materialService.toggleRoadmapDay(materialId, weekNumber, dayIndex));
    } catch (error) {
      setWeeks((previous) => toggleDayInWeeks(previous, weekNumber, dayIndex));
      throw error;
    } finally {
      setTogglingKey(null);
    }
  });

  const toggleTask = useSubmit(async (taskId) => {
    setTogglingKey(taskId);
    setWeeks((previous) => toggleTaskInWeeks(previous, taskId));

    try {
      await materialService.toggleRoadmapTask(materialId, taskId);
    } catch (error) {
      setWeeks((previous) => toggleTaskInWeeks(previous, taskId));
      throw error;
    } finally {
      setTogglingKey(null);
    }
  });

  const usesDays = hasDayStructure(weeks);
  const plannerReady = useMemo(() => canCreatePlanners(roadmap.data), [roadmap.data]);
  const activeWeekNumber = selectedWeekNumber ?? firstOpenWeekNumber(weeks);
  const [openWeekNumber, openDayIndex] = openDayKey ? openDayKey.split('-').map(Number) : [];
  const openDay = openDayKey ? findDay(weeks, openWeekNumber, openDayIndex) : null;
  const toggleError = toggleDay.errorMessage || toggleTask.errorMessage;

  const openPlannerList = (result) => {
    setPlannerSheetOpen(false);
    navigate('/planner', { state: { plannerType: PLANNER_TYPE.ROADMAP, notice: result.message } });
  };

  const renderRoadmap = () => {
    if (weeks.length === 0) return <EmptyState message="아직 생성된 로드맵이 없습니다." />;

    if (!usesDays) {
      return (
        <RoadmapLegacyWeeks
          weeks={weeks}
          togglingTaskId={togglingKey}
          onToggleTask={(taskId) => toggleTask.submit(taskId).catch(() => {})}
        />
      );
    }

    return (
      <RoadmapWeekView
        weeks={weeks}
        selectedWeekNumber={activeWeekNumber}
        onSelectWeek={setSelectedWeekNumber}
        togglingDayKey={togglingKey}
        onToggleDay={(weekNumber, dayIndex) => toggleDay.submit(weekNumber, dayIndex).catch(() => {})}
        onOpenDay={(weekNumber, dayIndex) => setOpenDayKey(dayKey(weekNumber, dayIndex))}
      />
    );
  };

  return (
    <>
      <RoadmapRegenerateCard
        level={level}
        onChangeLevel={setLevel}
        isRegenerating={regeneration.isGenerating}
        errorMessage={regeneration.isFailed ? describeApiError(regeneration.error) : null}
        onRegenerate={regenerate}
      />

      <ScreenState query={roadmap} loadingLabel="로드맵을 불러오는 중입니다">
        <>
          <p className="mobile-card__meta">
            업로드한 자료를 기반으로 AI가 설계한 12주 × 7일(84일) 학습 로드맵입니다.
          </p>

          {roadmapUsedServerFallback(roadmap.data) && (
            <p className="mobile-notice mobile-section">
              AI가 문서 정보가 부족하여 기본 학습 절차 기반으로 로드맵을 구성했습니다.
            </p>
          )}

          {weeks.length > 0 && <ProgressCard weeks={weeks} />}

          <section className="mobile-section">
            <Button fullWidth disabled={!plannerReady} onClick={() => setPlannerSheetOpen(true)}>
              <CalendarPlus size={16} />
              플래너 생성
            </Button>
            {weeks.length > 0 && !plannerReady && (
              <p className="mobile-field__hint">{ROADMAP_DAYS_REQUIRED_MESSAGE}</p>
            )}
          </section>

          {toggleError && <p className="mobile-auth__error">{toggleError}</p>}

          {renderRoadmap()}
        </>
      </ScreenState>

      <RoadmapDaySheet
        weekNumber={openWeekNumber}
        day={openDay}
        isToggling={togglingKey === openDayKey}
        onToggle={() => toggleDay.submit(openWeekNumber, openDayIndex).catch(() => {})}
        onClose={() => setOpenDayKey(null)}
      />

      <RoadmapPlannerSheet
        isOpen={isPlannerSheetOpen}
        onClose={() => setPlannerSheetOpen(false)}
        materialId={materialId}
        materialTitle={null}
        roadmap={roadmap.data}
        onCreated={openPlannerList}
      />
    </>
  );
}
