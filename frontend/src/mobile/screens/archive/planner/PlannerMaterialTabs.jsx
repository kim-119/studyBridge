import React, { useState } from 'react';
import { CalendarDays } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import SubTabs from '../../../components/SubTabs';
import PlannerPlanAnalysisSection from '../../planner/PlannerPlanAnalysisSection';
import LearningNavigatorCard from './LearningNavigatorCard';
import MaterialChecklistCard from './MaterialChecklistCard';
import PlannerMemoCard from './PlannerMemoCard';

// 웹(ArchiveDetail 플래너 학습 도구)과 같은 3탭: AI 계획 분석 / AI 학습 내비게이터 / 메모.
// 예전 "다음 학습"(next-learning·recommendations) 화면은 웹과 같이 AI 학습 내비게이터로 대체한다.
export const PLANNER_TABS = [
  { key: 'analysis', label: 'AI 계획 분석' },
  { key: 'next', label: 'AI 학습 내비게이터' },
  { key: 'memo', label: '메모' },
];

function AnalysisTab({ material }) {
  if (material.plannerId == null) return <MaterialChecklistCard materialId={material.materialId} />;

  return (
    <>
      <PlannerPlanAnalysisSection plannerId={material.plannerId} />
      <MaterialChecklistCard materialId={material.materialId} hideWhenEmpty />
    </>
  );
}

export default function PlannerMaterialTabs({ material }) {
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState(PLANNER_TABS[0].key);

  return (
    <>
      {material.plannerId != null && (
        <button
          type="button"
          className="mobile-button mobile-button--action mobile-button--block mobile-section"
          onClick={() => navigate(`/planner/${material.plannerId}`)}
        >
          <CalendarDays size={16} />
          플래너 열기
        </button>
      )}

      <SubTabs tabs={PLANNER_TABS} activeKey={activeTab} onChange={setActiveTab} />

      {activeTab === 'analysis' && <AnalysisTab material={material} />}
      {activeTab === 'next' && (
        <LearningNavigatorCard
          plannerId={material.plannerId ?? null}
          onOpenPlanner={(plannerId) => navigate(plannerId != null ? `/planner/${plannerId}` : '/planner/new')}
          onOpenChecklist={() => setActiveTab('analysis')}
          onOpenSchedule={() => navigate('/weekly-schedule')}
        />
      )}
      {activeTab === 'memo' && <PlannerMemoCard materialId={material.materialId} />}
    </>
  );
}
