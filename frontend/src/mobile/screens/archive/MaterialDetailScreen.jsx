import React, { useState } from 'react';
import { Download, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { materialService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { openExternalUrl } from '../../platform/externalLink';
import { formatDate, formatFileSize } from './archiveDomain';
import DocumentTab from './tabs/DocumentTab';
import MemoTab from './tabs/MemoTab';
import QuestionTab from './tabs/QuestionTab';
import QuizTab from './tabs/QuizTab';
import ReviewNoteLinkCard from './tabs/ReviewNoteLinkCard';
import RoadmapTab from './tabs/RoadmapTab';
import SummaryTab from './tabs/SummaryTab';

const DETAIL_TABS = [
  { key: 'document', label: '문서' },
  { key: 'summary', label: '요약' },
  { key: 'quiz', label: '퀴즈' },
  { key: 'roadmap', label: '로드맵' },
  { key: 'memo', label: '메모' },
  { key: 'question', label: 'AI 질문' },
];

export default function MaterialDetailScreen() {
  const { materialId } = useParams();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState(DETAIL_TABS[0].key);

  const detail = useAsync(() => materialService.getMaterialDetail(materialId), [materialId]);

  const removeMaterial = useSubmit(async () => {
    await materialService.deleteMaterial(materialId);
    navigate('/archive', { replace: true });
  });

  const material = detail.data;

  const renderTab = () => {
    switch (activeTab) {
      case 'summary':
        return <SummaryTab materialId={materialId} />;
      case 'quiz':
        return <QuizTab materialId={materialId} />;
      case 'roadmap':
        return <RoadmapTab materialId={materialId} />;
      case 'memo':
        return <MemoTab materialId={materialId} />;
      case 'question':
        return <QuestionTab materialId={materialId} />;
      default:
        return <DocumentTab material={material} />;
    }
  };

  return (
    <MobileScreen title={material?.title || '자료'} showBackButton>
      <ScreenState query={detail} loadingLabel="자료를 불러오는 중입니다">
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">
              {[formatDate(material?.uploadedAt), formatFileSize(material?.fileSize), material?.materialType]
                .filter(Boolean)
                .join(' · ')}
            </p>

            {material?.keywords && (
              <ul className="mobile-chips">
                {material.keywords
                  .split(',')
                  .map((keyword) => keyword.trim())
                  .filter(Boolean)
                  .map((keyword) => (
                    <li key={keyword}>#{keyword}</li>
                  ))}
              </ul>
            )}

            <div className="mobile-card__actions">
              <Button
                variant="secondary"
                disabled={!material?.s3PresignedUrl}
                onClick={() => openExternalUrl(material.s3PresignedUrl)}
              >
                <Download size={16} />
                다운로드
              </Button>

              <Button
                variant="ghost"
                isLoading={removeMaterial.isSubmitting}
                onClick={() => removeMaterial.submit().catch(() => {})}
              >
                <Trash2 size={16} />
                삭제
              </Button>
            </div>

            {removeMaterial.errorMessage && (
              <p className="mobile-auth__error">{removeMaterial.errorMessage}</p>
            )}
          </section>

          <ReviewNoteLinkCard materialId={materialId} />

          <SubTabs tabs={DETAIL_TABS} activeKey={activeTab} onChange={setActiveTab} />

          {renderTab()}
        </>
      </ScreenState>
    </MobileScreen>
  );
}
