import React, { useMemo, useState } from 'react';
import { CalendarCheck, Route } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { PLANNER_TYPE, isTodayPlanner, toPlannerSummary } from './plannerAdapter';

const PLANNER_TABS = [
  { key: PLANNER_TYPE.USER, label: '내 플래너' },
  { key: PLANNER_TYPE.ROADMAP, label: '로드맵' },
];

export default function PlannerScreen() {
  const navigate = useNavigate();
  const [plannerType, setPlannerType] = useState(PLANNER_TYPE.USER);

  const planners = useAsync(() => plannerService.getPlanners(plannerType), [plannerType]);

  const items = useMemo(() => {
    const list = Array.isArray(planners.data) ? planners.data : planners.data?.content || [];
    return list.map(toPlannerSummary);
  }, [planners.data]);

  const todayPlanners = items.filter((planner) => isTodayPlanner(planner));

  return (
    <MobileScreen title="플래너">
      <SubTabs tabs={PLANNER_TABS} activeKey={plannerType} onChange={setPlannerType} />

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">오늘의 학습 계획</p>
        <p className="mobile-stat">{todayPlanners.length}건</p>
        <p className="mobile-card__meta">전체 {items.length}건</p>
      </section>

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
                  meta={planner.progress.total > 0 ? `${planner.progress.ratio}%` : undefined}
                  onClick={() => navigate(`/planner/${planner.id}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="플래너 만들기" onClick={() => navigate('/planner/new')} />
    </MobileScreen>
  );
}
