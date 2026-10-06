import React from 'react';
import { RefreshCw } from 'lucide-react';
import Button from '../../../components/Button';
import ScreenState from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { describeApiError, useAsync, useSubmit } from '../../../data/useAsync';
import { aiFailureMessage, isAiFailure } from '../aiResponseModel';
import { summaryOverview } from '../summaryModel';
import { FEEDBACK_SECTIONS, feedbackQualityWarning, parseJournalFeedback } from './journalFeedbackModel';

function TextSection({ title, text }) {
  if (!text) return null;

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">{title}</h3>
      <p className="mobile-paragraph">{text}</p>
    </section>
  );
}

function JournalSummary({ materialId }) {
  const summary = useAsync(() => materialService.getSummary(materialId), [materialId]);
  const overview = summaryOverview(summary.data);

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">AI 요약</h3>
      <ScreenState query={summary} loadingLabel="AI가 학습일지를 분석 중입니다">
        {isAiFailure(summary.data) ? (
          <p className="mobile-auth__error">{aiFailureMessage(summary.data)}</p>
        ) : (
          <p className={overview ? 'mobile-paragraph' : 'mobile-state__text'}>
            {overview || '작성된 학습일지를 바탕으로 분석된 AI 요약이 아직 생성되지 않았습니다.'}
          </p>
        )}
      </ScreenState>
    </section>
  );
}

function StructuredFeedback({ feedback }) {
  const warning = feedbackQualityWarning(feedback);

  return (
    <>
      {warning && <p className="mobile-notice mobile-section">{warning}</p>}
      {feedback.summary && <p className="mobile-paragraph mobile-section">{feedback.summary}</p>}
      {FEEDBACK_SECTIONS.map(({ key, label }) =>
        feedback[key].length === 0 ? null : (
          <div key={key} className="mobile-section">
            <h4 className="mobile-section__title">
              {label} ({feedback[key].length}개)
            </h4>
            <ul className="mobile-bullets">
              {feedback[key].map((item, index) => (
                <li key={`${key}-${index}`}>{item}</li>
              ))}
            </ul>
          </div>
        )
      )}
    </>
  );
}

function FeedbackBody({ feedbackData }) {
  const { structured, lines } = parseJournalFeedback(feedbackData);

  if (structured) return <StructuredFeedback feedback={structured} />;
  if (lines.length === 0) {
    return <p className="mobile-state__text">아직 등록된 AI 피드백이 없습니다. 잠시 후 다시 확인해주세요.</p>;
  }

  return (
    <ol className="mobile-bullets">
      {lines.map((line, index) => (
        <li key={`line-${index}`}>{line}</li>
      ))}
    </ol>
  );
}

function JournalFeedback({ materialId }) {
  const feedback = useAsync(() => materialService.getFeedback(materialId), [materialId]);

  const regenerate = useSubmit(async () => {
    const result = await materialService.regenerateFeedback(materialId);
    feedback.setData(result);
  });

  const regenerateError = regenerate.error
    ? regenerate.error.response?.data?.message || describeApiError(regenerate.error)
    : null;

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">AI 피드백</h3>
      <ScreenState query={feedback} loadingLabel="AI 피드백을 불러오는 중입니다">
        {isAiFailure(feedback.data) ? (
          <p className="mobile-auth__error">{aiFailureMessage(feedback.data)}</p>
        ) : (
          <FeedbackBody feedbackData={feedback.data?.feedbackData} />
        )}
      </ScreenState>

      {regenerateError && <p className="mobile-auth__error mobile-archive-gap">{regenerateError}</p>}

      <Button
        fullWidth
        variant="secondary"
        isLoading={regenerate.isSubmitting}
        onClick={() => regenerate.submit().catch(() => {})}
      >
        <RefreshCw size={16} />
        균형 잡힌 피드백 다시 생성
      </Button>
    </section>
  );
}

export default function StudyJournalDetail({ material }) {
  return (
    <>
      <TextSection title="학습 내용" text={material.learningContent} />
      <TextSection title="다음 계획" text={material.nextPlan} />
      <JournalSummary materialId={material.materialId} />
      <JournalFeedback materialId={material.materialId} />
    </>
  );
}
