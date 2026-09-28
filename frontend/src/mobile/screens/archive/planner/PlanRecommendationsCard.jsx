import React from 'react';
import Button from '../../../components/Button';
import ScreenState from '../../../components/ScreenState';
import { planAnalysisService } from '../../../../services/api';
import { useAsync, useSubmit } from '../../../data/useAsync';

function recommendationsOf(analysis) {
  return Array.isArray(analysis?.recommendations) ? analysis.recommendations.filter(Boolean) : [];
}

export default function PlanRecommendationsCard({ materialId }) {
  const analysis = useAsync(() => planAnalysisService.get(materialId), [materialId]);
  const hasAnalysis = Boolean(analysis.data) && analysis.data.empty !== true;

  const recommend = useSubmit(async () => {
    const result = await planAnalysisService.recommend(materialId);
    analysis.setData((previous) => ({ ...previous, recommendations: result?.recommendations || [] }));
  });

  const recommendations = recommendationsOf(analysis.data);

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">AI 계획 분석 기반 추천</h3>

      <ScreenState query={analysis} loadingLabel="추천을 불러오는 중입니다">
        {!hasAnalysis ? (
          <p className="mobile-state__text">아직 분석 결과가 없습니다. ‘계획 분석’ 탭에서 AI 계획 분석을 먼저 실행하세요.</p>
        ) : recommendations.length === 0 ? (
          <p className="mobile-state__text">미완료 항목이 없습니다. 모든 학습을 완료했어요.</p>
        ) : (
          <ul className="mobile-bullets">
            {recommendations.map((recommendation, index) => (
              <li key={`${index}-${String(recommendation).slice(0, 24)}`}>{recommendation}</li>
            ))}
          </ul>
        )}
      </ScreenState>

      {recommend.errorMessage && <p className="mobile-auth__error mobile-archive-gap">{recommend.errorMessage}</p>}

      {hasAnalysis && (
        <Button
          fullWidth
          variant="ghost"
          isLoading={recommend.isSubmitting}
          onClick={() => recommend.submit().catch(() => {})}
        >
          새로 추천
        </Button>
      )}
    </section>
  );
}
