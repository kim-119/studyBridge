import React from 'react';
import ScreenState from '../../../components/ScreenState';
import {
  aiFailureMessage,
  isAiFailure,
  isTextMissingFailure,
  textStatusMessage,
} from '../aiResponseModel';
import {
  coreContentText,
  detailedContentText,
  summaryKeywords,
  summaryList,
  summaryOverview,
} from '../summaryModel';

function TextBlock({ title, text, emptyMessage }) {
  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">{title}</h3>
      {text ? <p className="mobile-paragraph">{text}</p> : <p className="mobile-state__text">{emptyMessage}</p>}
    </section>
  );
}

function BulletBlock({ title, items }) {
  if (items.length === 0) return null;

  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">{title}</h3>
      <ul className="mobile-bullets">
        {items.map((item, index) => (
          <li key={`${index}-${item.slice(0, 24)}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function SummaryFailure({ summary, onRetry }) {
  return (
    <section className="mobile-section">
      <p className="mobile-auth__error" role="alert">
        {aiFailureMessage(summary)}
        {summary.errorCode && <span className="mobile-archive-code">오류 코드: {summary.errorCode}</span>}
      </p>
      {isTextMissingFailure(summary) && (
        <p className="mobile-notice mobile-section">
          이미지 기반 PDF, 빈 양식 PDF, 스캔본 PDF처럼 텍스트 레이어가 없는 문서는 요약할 수 없습니다. 선택 가능한
          텍스트가 포함된 PDF를 업로드하면 요약 품질이 가장 좋습니다.
        </p>
      )}
      <button type="button" className="mobile-button mobile-button--ghost" onClick={onRetry}>
        다시 불러오기
      </button>
    </section>
  );
}

function SummaryContent({ summary, material }) {
  const keywords = summaryKeywords(summary, material);
  const warning = textStatusMessage(summary.textStatus);

  return (
    <>
      {warning && <p className="mobile-notice mobile-section">{warning}</p>}

      <TextBlock
        title="문서 개요"
        text={summaryOverview(summary)}
        emptyMessage="요약 내용이 아직 생성되지 않았습니다."
      />

      <section className="mobile-section">
        <h3 className="mobile-section__title">핵심 키워드</h3>
        {keywords.length > 0 ? (
          <ul className="mobile-chips">
            {keywords.map((keyword) => (
              <li key={keyword}>#{keyword}</li>
            ))}
          </ul>
        ) : (
          <p className="mobile-state__text">핵심 키워드가 아직 생성되지 않았습니다.</p>
        )}
      </section>

      <TextBlock
        title="핵심 내용"
        text={coreContentText(summary)}
        emptyMessage="핵심 내용이 아직 생성되지 않았습니다."
      />
      <TextBlock
        title="세부 핵심 내용"
        text={detailedContentText(summary)}
        emptyMessage="세부 핵심 내용이 아직 생성되지 않았습니다."
      />

      <BulletBlock title="학습 포인트" items={summaryList(summary, 'learningPoints')} />
      <BulletBlock title="실습 관점 정리" items={summaryList(summary, 'practicePoints')} />
      <BulletBlock title="AI 학습 질문" items={summaryList(summary, 'studyQuestions')} />
    </>
  );
}

export default function SummaryTab({ summaryQuery, material }) {
  return (
    <ScreenState
      query={summaryQuery}
      loadingLabel="문서 내용을 분석하고 있습니다"
      emptyWhen={(value) => !value}
      emptyMessage="요약 응답이 비어 있습니다. 다시 불러와 주세요."
    >
      {isAiFailure(summaryQuery.data) ? (
        <SummaryFailure summary={summaryQuery.data} onRetry={() => summaryQuery.reload().catch(() => {})} />
      ) : (
        <SummaryContent summary={summaryQuery.data || {}} material={material} />
      )}
    </ScreenState>
  );
}
