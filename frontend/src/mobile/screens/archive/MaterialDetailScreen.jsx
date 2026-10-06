import React, { useCallback } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import ScreenState from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { materialService } from '../../../services/api';
import { describeApiError, useAsync, useSubmit } from '../../data/useAsync';
import { MATERIAL_KIND, REVIEW_NOTE_CONTEXT, materialKindOf } from './archiveNavigation';
import DocumentMaterialTabs from './DocumentMaterialTabs';
import DocumentPreview from './DocumentPreview';
import MaterialHeader from './MaterialHeader';
import StudyJournalDetail from './journal/StudyJournalDetail';
import PlannerMaterialTabs from './planner/PlannerMaterialTabs';
import ReviewNoteLinkCard from './tabs/ReviewNoteLinkCard';
import { isExtractionInProgress, useExtractionPolling } from './useExtractionPolling';

function detailContextFrom(searchParams) {
  return searchParams.get('context') === REVIEW_NOTE_CONTEXT ? REVIEW_NOTE_CONTEXT : undefined;
}

function ExtractionWaiting({ pollError }) {
  return (
    <section className="mobile-card mobile-section">
      <div className="mobile-state" role="status">
        <span className="mobile-state__spinner" />
        <p className="mobile-state__text">
          AI가 문서를 분석하고 있습니다. 분석이 끝나면 요약 · 퀴즈 · 로드맵 · 메모 · AI 질문이 자동으로 열립니다.
        </p>
      </div>
      {pollError && (
        <p className="mobile-auth__error">
          분석 상태를 확인하지 못했습니다. 계속 다시 확인합니다. ({describeApiError(pollError)})
        </p>
      )}
    </section>
  );
}

function MaterialBody({ material, kind, pollError, onRefreshUrl }) {
  if (kind === MATERIAL_KIND.STUDY_JOURNAL) return <StudyJournalDetail material={material} />;

  if (kind === MATERIAL_KIND.REVIEW_NOTE) {
    return (
      <>
        <DocumentPreview material={material} onRefreshUrl={onRefreshUrl} />
        <ReviewNoteLinkCard materialId={material.materialId} />
      </>
    );
  }

  if (kind === MATERIAL_KIND.PLANNER) {
    return (
      <>
        <DocumentPreview material={material} onRefreshUrl={onRefreshUrl} />
        <PlannerMaterialTabs material={material} />
      </>
    );
  }

  if (isExtractionInProgress(material)) return <ExtractionWaiting pollError={pollError} />;

  return (
    <>
      <DocumentPreview material={material} onRefreshUrl={onRefreshUrl} />
      <ReviewNoteLinkCard materialId={material.materialId} />
      <DocumentMaterialTabs key={material.materialId} material={material} />
    </>
  );
}

export default function MaterialDetailScreen() {
  const { materialId } = useParams();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const context = detailContextFrom(searchParams);

  const detail = useAsync(() => materialService.getMaterialDetail(materialId, context), [materialId, context]);
  const { setData: setMaterial } = detail;

  const refreshMaterial = useCallback(async () => {
    const fresh = await materialService.getMaterialDetail(materialId, context);
    setMaterial(fresh);
    return fresh;
  }, [materialId, context, setMaterial]);

  const refreshDocumentUrl = useCallback(async () => {
    const fresh = await refreshMaterial();
    return fresh?.s3PresignedUrl || null;
  }, [refreshMaterial]);

  const pollError = useExtractionPolling(detail.data, refreshMaterial);

  const removeMaterial = useSubmit(async () => {
    await materialService.deleteMaterial(materialId);
    navigate('/archive', { replace: true });
  });

  const material = detail.data;
  const kind = materialKindOf(material);

  if (material && kind === MATERIAL_KIND.MINDMAP) {
    return <Navigate to="/archive" replace />;
  }

  return (
    <MobileScreen title={material?.title || '자료'} showBackButton>
      <ScreenState query={detail} loadingLabel="자료를 불러오는 중입니다">
        {material && (
          <>
            <MaterialHeader
              material={material}
              kind={kind}
              isDeleting={removeMaterial.isSubmitting}
              deleteError={removeMaterial.errorMessage}
              onDelete={() => removeMaterial.submit().catch(() => {})}
            />
            <MaterialBody
              material={material}
              kind={kind}
              pollError={pollError}
              onRefreshUrl={refreshDocumentUrl}
            />
          </>
        )}
      </ScreenState>
    </MobileScreen>
  );
}
