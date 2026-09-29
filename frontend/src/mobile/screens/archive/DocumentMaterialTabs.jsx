import React, { useState } from 'react';
import SubTabs from '../../components/SubTabs';
import { materialService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { useBackDismiss } from '../../platform/useBackDismiss';
import MemoTab from './tabs/MemoTab';
import QuestionTab from './tabs/QuestionTab';
import QuizTab from './tabs/QuizTab';
import RoadmapTab from './tabs/RoadmapTab';
import SummaryTab from './tabs/SummaryTab';
import { isExtractionFailed } from './useExtractionPolling';

const DOCUMENT_TABS = [
  { key: 'summary', label: '요약' },
  { key: 'quiz', label: '퀴즈' },
  { key: 'roadmap', label: '로드맵' },
  { key: 'memo', label: '메모' },
  { key: 'question', label: 'AI 질문' },
];

const AI_TAB_KEYS = new Set(['summary', 'quiz', 'question']);

function ExtractionFailedNotice() {
  return (
    <p className="mobile-auth__error">
      PDF 텍스트 추출에 실패해 AI 기능을 사용할 수 없습니다. 텍스트가 포함된 PDF로 다시 업로드해주세요.
    </p>
  );
}

export default function DocumentMaterialTabs({ material }) {
  const materialId = material.materialId;
  const [activeTab, setActiveTab] = useState(DOCUMENT_TABS[0].key);
  useBackDismiss(activeTab !== DOCUMENT_TABS[0].key, () => setActiveTab(DOCUMENT_TABS[0].key));
  const isAiAvailable = !isExtractionFailed(material);

  const summary = useAsync(() => materialService.getSummary(materialId), [materialId], {
    immediate: isAiAvailable,
  });

  const renderActiveTab = () => {
    if (!isAiAvailable && AI_TAB_KEYS.has(activeTab)) return <ExtractionFailedNotice />;

    switch (activeTab) {
      case 'quiz':
        return <QuizTab material={material} />;
      case 'roadmap':
        return <RoadmapTab materialId={materialId} />;
      case 'memo':
        return <MemoTab material={material} />;
      case 'question':
        return <QuestionTab key={materialId} materialId={materialId} textStatus={summary.data?.textStatus} />;
      default:
        return <SummaryTab summaryQuery={summary} material={material} />;
    }
  };

  return (
    <>
      <SubTabs tabs={DOCUMENT_TABS} activeKey={activeTab} onChange={setActiveTab} />
      {renderActiveTab()}
    </>
  );
}
