import React from 'react';
import { CheckCircle2, Circle, EyeOff } from 'lucide-react';
import Button from '../../../components/Button';
import ScreenState from '../../../components/ScreenState';
import { planAnalysisService } from '../../../../services/api';
import { describeApiError, useAsync, useSubmit } from '../../../data/useAsync';

const EMPTY_PROGRESS = { totalCount: 0, completedCount: 0, percent: 0 };

function hasAnalysis(analysis) {
  return Boolean(analysis) && analysis.empty !== true;
}

function sourceLabel(item) {
  if (item.sourceType === 'PDF') return item.pageNumber ? `PDF p.${item.pageNumber}` : 'PDF';
  if (item.sourceType === 'PLANNER') return 'Planner';
  return item.sourceType || '출처';
}

function analysisFailureMessage(error) {
  const body = error?.response?.data;
  return body?.summary || body?.message || describeApiError(error);
}

function ChecklistItem({ item, isBusy, onToggle, onHide }) {
  return (
    <li className="mobile-archive-check">
      <button
        type="button"
        className="mobile-roadmap__step"
        aria-pressed={Boolean(item.completed)}
        disabled={isBusy}
        onClick={onToggle}
      >
        {item.completed ? (
          <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
        ) : (
          <Circle size={20} className="mobile-roadmap__check" />
        )}
        <span>
          <strong>{item.text}</strong>
          <span>{sourceLabel(item)}</span>
        </span>
      </button>
      <button type="button" className="mobile-row__more" aria-label="완료 처리 후 숨기기" disabled={isBusy} onClick={onHide}>
        <EyeOff size={18} />
      </button>
    </li>
  );
}

export default function MaterialChecklistCard({ materialId, hideWhenEmpty = false }) {
  const analysis = useAsync(() => planAnalysisService.get(materialId), [materialId]);

  const runAnalysis = useSubmit(async () => {
    const result = await planAnalysisService.analyze(materialId);
    if (result?.errorCode) throw new Error(result.summary || 'AI 계획 분석에 실패했습니다. 다시 시도해 주세요.');
    analysis.setData(result);
  });

  const patchItem = useSubmit(async (itemId, patch) => {
    const result = await planAnalysisService.patchItem(itemId, patch);
    analysis.setData(result);
  });

  const data = analysis.data;
  if (hideWhenEmpty && analysis.isSuccess && !hasAnalysis(data)) return null;

  const items = (Array.isArray(data?.items) ? data.items : []).filter((item) => !item.hidden);
  const progress = data?.progress || EMPTY_PROGRESS;
  const runError = runAnalysis.error ? analysisFailureMessage(runAnalysis.error) : null;

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">문장 단위 체크리스트</h3>

      <ScreenState query={analysis} loadingLabel="계획 분석을 불러오는 중입니다">
        {hasAnalysis(data) ? (
          <>
            {data.summary && <p className="mobile-paragraph">{data.summary}</p>}
            <p className="mobile-card__meta mobile-archive-gap">
              진행률 {progress.percent}% ({progress.completedCount}/{progress.totalCount})
            </p>
            <div className="mobile-progress">
              <span style={{ width: `${Math.max(0, Math.min(100, progress.percent || 0))}%` }} />
            </div>

            {items.length === 0 ? (
              <p className="mobile-state__text">표시할 항목이 없습니다. 모든 항목을 완료했거나 숨겼습니다.</p>
            ) : (
              <ul className="mobile-list">
                {items.map((item) => (
                  <ChecklistItem
                    key={item.id}
                    item={item}
                    isBusy={patchItem.isSubmitting}
                    onToggle={() => patchItem.submit(item.id, { completed: !item.completed }).catch(() => {})}
                    onHide={() => patchItem.submit(item.id, { completed: true, hidden: true }).catch(() => {})}
                  />
                ))}
              </ul>
            )}
          </>
        ) : (
          <p className="mobile-state__text">아직 분석 결과가 없습니다. AI 계획 분석으로 문장을 체크리스트로 만들어 보세요.</p>
        )}
      </ScreenState>

      {patchItem.errorMessage && <p className="mobile-auth__error mobile-archive-gap">{patchItem.errorMessage}</p>}
      {runError && <p className="mobile-auth__error mobile-archive-gap">{runError}</p>}

      <Button
        fullWidth
        variant={hasAnalysis(data) ? 'ghost' : 'primary'}
        isLoading={runAnalysis.isSubmitting}
        onClick={() => runAnalysis.submit().catch(() => {})}
      >
        {hasAnalysis(data) ? '다시 분석' : 'AI 계획 분석'}
      </Button>
    </section>
  );
}
