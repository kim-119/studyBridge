import React, { useState } from 'react';
import { CalendarDays } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import SubTabs from '../../../components/SubTabs';
import PlannerNextLearningCard from '../../planner/PlannerNextLearningCard';
import PlannerPlanAnalysisSection from '../../planner/PlannerPlanAnalysisSection';
import MaterialChecklistCard from './MaterialChecklistCard';
import PlanRecommendationsCard from './PlanRecommendationsCard';
import PlannerMemoCard from './PlannerMemoCard';

const PLANNER_TABS = [
  { key: 'analysis', label: '계획 분석' },
  { key: 'next', label: '다음 학습' },
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

function NextTab({ material }) {
  return (
    <>
      {material.plannerId == null ? (
        <p className="mobile-notice mobile-section">
          원본 플래너가 없는 보관 항목이라 다음 학습 순서를 확인할 수 없습니다.
        </p>
      ) : (
        <PlannerNextLearningCard plannerId={material.plannerId} />
      )}
      <PlanRecommendationsCard materialId={material.materialId} />
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
      {activeTab === 'next' && <NextTab material={material} />}
      {activeTab === 'memo' && <PlannerMemoCard materialId={material.materialId} />}
    </>
  );
}
