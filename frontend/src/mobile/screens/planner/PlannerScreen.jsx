import React, { useMemo, useState } from 'react';
import { CalendarCheck, FileText, Route } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { materialService, plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { PLANNER_TYPE, formatMinutes, isTodayPlanner, toPlannerSummary } from './plannerAdapter';

const PLANNER_TABS = [
  { key: PLANNER_TYPE.USER, label: '내 플래너' },
  { key: PLANNER_TYPE.ROADMAP, label: '로드맵' },
];

const SHEET = {
  ACTIONS: 'actions',
  FROM_ROADMAP: 'from-roadmap',
};

function RoadmapSourcePicker({ onSelect }) {
  const archive = useAsync(() => materialService.getArchiveItems(null, 'LEARNING_MATERIAL'), []);

  return (
    <ScreenState
      query={archive}
      loadingLabel="학습자료를 불러오는 중입니다"
      emptyWhen={(value) => !value?.materials?.length}
      emptyMessage="로드맵을 만들 학습자료가 없습니다."
    >
      <ul className="mobile-list">
        {(archive.data?.materials || []).map((material) => (
          <li key={material.materialId}>
            <ListRow
              icon={<FileText size={20} />}
              title={material.title}
              onClick={() => onSelect(material.materialId)}
            />
          </li>
        ))}
      </ul>
    </ScreenState>
  );
}

export default function PlannerScreen() {
  const navigate = useNavigate();
  const [plannerType, setPlannerType] = useState(PLANNER_TYPE.USER);
  const [openSheet, setOpenSheet] = useState(null);

  const planners = useAsync(() => plannerService.getPlanners(plannerType), [plannerType]);

  const items = useMemo(() => {
    const list = Array.isArray(planners.data) ? planners.data : planners.data?.content || [];
    return list.map(toPlannerSummary);
  }, [planners.data]);

  const todayPlanners = items.filter((planner) => isTodayPlanner(planner));
  const todayMinutes = todayPlanners.reduce((total, planner) => total + planner.plannedMinutes, 0);

  const createFromRoadmap = useSubmit(async (materialId) => {
    await plannerService.createFromRoadmap({
      materialId,
      startDate: new Date().toISOString().slice(0, 10),
    });
    setOpenSheet(null);
    setPlannerType(PLANNER_TYPE.ROADMAP);
    await planners.reload();
  });

  return (
    <MobileScreen title="플래너">
      <SubTabs tabs={PLANNER_TABS} activeKey={plannerType} onChange={setPlannerType} />

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">오늘의 학습 계획</p>
        <p className="mobile-stat">{todayPlanners.length}건</p>
        <p className="mobile-card__meta">
          계획 학습량 {formatMinutes(todayMinutes)} · 전체 {items.length}건
        </p>
      </section>

      {createFromRoadmap.errorMessage && (
        <p className="mobile-auth__error">{createFromRoadmap.errorMessage}</p>
      )}

      <ScreenState query={planners} loadingLabel="플래너를 불러오는 중입니다">
        {items.length === 0 ? (
          <EmptyState message="등록된 플래너가 없습니다." />
        ) : (
          <ul className="mobile-list">
            {items.map((planner) => (
              <li key={planner.id}>
                <ListRow
                  icon={planner.type === PLANNER_TYPE.ROADMAP ? <Route size={20} /> : <CalendarCheck size={20} />}
                  title={planner.title}
                  subtitle={[planner.subject, planner.date, planner.priority].filter(Boolean).join(' · ')}
                  meta={planner.plannedMinutes > 0 ? formatMinutes(planner.plannedMinutes) : undefined}
                  onClick={() => navigate(`/planner/${planner.id}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="플래너 추가" onClick={() => setOpenSheet(SHEET.ACTIONS)} />

      <BottomSheet title="플래너 추가" isOpen={openSheet === SHEET.ACTIONS} onClose={() => setOpenSheet(null)}>
        <ul className="mobile-list">
          <li>
            <ListRow
              icon={<CalendarCheck size={20} />}
              title="직접 만들기"
              onClick={() => {
                setOpenSheet(null);
                navigate('/planner/new');
              }}
            />
          </li>
          <li>
            <ListRow
              icon={<Route size={20} />}
              title="로드맵으로 만들기"
              subtitle="학습자료의 로드맵을 일자별 플래너로 변환합니다"
              onClick={() => setOpenSheet(SHEET.FROM_ROADMAP)}
            />
          </li>
        </ul>
      </BottomSheet>

      <BottomSheet
        title="로드맵 선택"
        isOpen={openSheet === SHEET.FROM_ROADMAP}
        onClose={() => setOpenSheet(null)}
      >
        <RoadmapSourcePicker
          onSelect={(materialId) => createFromRoadmap.submit(materialId).catch(() => {})}
        />
      </BottomSheet>
    </MobileScreen>
  );
}
