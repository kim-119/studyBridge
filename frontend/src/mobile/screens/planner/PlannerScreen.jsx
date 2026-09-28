import React, { useMemo, useState } from 'react';
import { CalendarCheck, FileText, Route } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { materialService, plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import RoadmapPlannerSheet from '../roadmap/RoadmapPlannerSheet';
import {
  ROADMAP_DAYS_REQUIRED_MESSAGE,
  assertRoadmapSucceeded,
  canCreatePlanners,
} from '../roadmap/roadmapModel';
import {
  PLANNER_TYPE,
  formatMinutes,
  formatPlannerDate,
  splitPlannersByType,
  summarizePlanners,
  toPlannerSummary,
} from './plannerAdapter';

const TAB_LABEL = {
  [PLANNER_TYPE.ROADMAP]: '로드맵',
  [PLANNER_TYPE.USER]: '사용자',
};

const SHEET = {
  ACTIONS: 'actions',
  PICK_MATERIAL: 'pick-material',
  CREATE_FROM_ROADMAP: 'create-from-roadmap',
};

function RoadmapSourcePicker({ loadingMaterialId, onSelect }) {
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
              meta={loadingMaterialId === material.materialId ? '불러오는 중' : undefined}
              onClick={() => onSelect(material)}
            />
          </li>
        ))}
      </ul>
    </ScreenState>
  );
}

function PlannerSummaryCard({ plannerType, summary }) {
  const tabLabel = TAB_LABEL[plannerType];

  return (
    <section className="mobile-card mobile-section">
      <div className="mobile-planner-stats">
        <div>
          <strong>{summary.total}개</strong>
          <span>{tabLabel} 플래너</span>
        </div>
        <div>
          <strong>{summary.upcomingCount}개</strong>
          <span>다가오는 {tabLabel} 일정</span>
        </div>
        <div>
          <strong>{summary.subjectCount}개</strong>
          <span>과목 수</span>
        </div>
      </div>

      {summary.upcoming.length === 0 ? (
        <p className="mobile-card__meta">예정된 {tabLabel} 일정이 없습니다.</p>
      ) : (
        <ul className="mobile-bullets">
          {summary.upcoming.map((planner) => (
            <li key={planner.id}>
              {formatPlannerDate(planner)} · {planner.title}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function plannerSubtitle(planner) {
  return [planner.roadmapLabel, formatPlannerDate(planner), planner.subject, planner.priority]
    .filter(Boolean)
    .join(' · ');
}

export default function PlannerScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const [plannerType, setPlannerType] = useState(location.state?.plannerType || PLANNER_TYPE.ROADMAP);
  const [notice, setNotice] = useState(location.state?.notice || '');
  const [openSheet, setOpenSheet] = useState(null);
  const [roadmapSource, setRoadmapSource] = useState(null);
  const [pendingMaterialId, setPendingMaterialId] = useState(null);

  const planners = useAsync(() => plannerService.getPlanners(), []);

  const plannersByType = useMemo(() => {
    const list = Array.isArray(planners.data) ? planners.data : [];
    return splitPlannersByType(list.map(toPlannerSummary));
  }, [planners.data]);

  const visiblePlanners = plannersByType[plannerType];
  const summary = summarizePlanners(visiblePlanners);

  const tabs = [
    { key: PLANNER_TYPE.ROADMAP, label: `로드맵 플래너 ${plannersByType[PLANNER_TYPE.ROADMAP].length}` },
    { key: PLANNER_TYPE.USER, label: `사용자 플래너 ${plannersByType[PLANNER_TYPE.USER].length}` },
  ];

  const loadRoadmapSource = useSubmit(async (material) => {
    setPendingMaterialId(material.materialId);

    try {
      const roadmap = assertRoadmapSucceeded(await materialService.getRoadmap(material.materialId));
      if (!canCreatePlanners(roadmap)) throw new Error(ROADMAP_DAYS_REQUIRED_MESSAGE);

      setRoadmapSource({ material, roadmap });
      setOpenSheet(SHEET.CREATE_FROM_ROADMAP);
    } finally {
      setPendingMaterialId(null);
    }
  });

  const showCreatedPlanners = (result) => {
    setOpenSheet(null);
    setRoadmapSource(null);
    setNotice(result.message);
    setPlannerType(PLANNER_TYPE.ROADMAP);
    planners.reload().catch(() => {});
  };

  return (
    <MobileScreen title="플래너">
      <SubTabs tabs={tabs} activeKey={plannerType} onChange={setPlannerType} />

      {notice && (
        <p className="mobile-notice mobile-section" role="status">
          {notice}
        </p>
      )}

      <ScreenState query={planners} loadingLabel="플래너를 불러오는 중입니다">
        <>
          <PlannerSummaryCard plannerType={plannerType} summary={summary} />

          {visiblePlanners.length === 0 ? (
            <EmptyState message={`${TAB_LABEL[plannerType]} 플래너가 없습니다.`} />
          ) : (
            <ul className="mobile-list">
              {visiblePlanners.map((planner) => (
                <li key={planner.id}>
                  <ListRow
                    icon={planner.type === PLANNER_TYPE.ROADMAP ? <Route size={20} /> : <CalendarCheck size={20} />}
                    title={planner.title}
                    subtitle={plannerSubtitle(planner)}
                    meta={planner.plannedMinutes > 0 ? formatMinutes(planner.plannedMinutes) : undefined}
                    onClick={() => navigate(`/planner/${planner.id}`)}
                  />
                </li>
              ))}
            </ul>
          )}
        </>
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
              subtitle="학습자료의 84일 로드맵을 일자별 플래너로 변환합니다"
              onClick={() => {
                loadRoadmapSource.clearError();
                setOpenSheet(SHEET.PICK_MATERIAL);
              }}
            />
          </li>
        </ul>
      </BottomSheet>

      <BottomSheet
        title="로드맵 선택"
        isOpen={openSheet === SHEET.PICK_MATERIAL}
        onClose={() => setOpenSheet(null)}
      >
        {loadRoadmapSource.errorMessage && (
          <p className="mobile-auth__error">{loadRoadmapSource.errorMessage}</p>
        )}
        <RoadmapSourcePicker
          loadingMaterialId={pendingMaterialId}
          onSelect={(material) => loadRoadmapSource.submit(material).catch(() => {})}
        />
      </BottomSheet>

      <RoadmapPlannerSheet
        isOpen={openSheet === SHEET.CREATE_FROM_ROADMAP}
        onClose={() => setOpenSheet(null)}
        materialId={roadmapSource?.material?.materialId}
        materialTitle={roadmapSource?.material?.title}
        roadmap={roadmapSource?.roadmap}
        onCreated={showCreatedPlanners}
      />
    </MobileScreen>
  );
}
