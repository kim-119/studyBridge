import React from 'react';
import ScreenState from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';

function TextList({ title, items }) {
  if (!items || items.length === 0) return null;

  return (
    <section className="mobile-section">
      <h3 className="mobile-section__title">{title}</h3>
      <ul className="mobile-bullets">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export default function SummaryTab({ materialId }) {
  const summary = useAsync(() => materialService.getSummary(materialId), [materialId]);
  const data = summary.data;

  return (
    <ScreenState
      query={summary}
      loadingLabel="요약을 불러오는 중입니다"
      emptyWhen={(value) => !value || (!value.overview && !value.summary && !value.key_points?.length)}
      emptyMessage="아직 생성된 요약이 없습니다."
    >
      <>
        {(data?.overview || data?.summary) && (
          <section className="mobile-card mobile-section">
            <p className="mobile-paragraph">{data.overview || data.summary}</p>
          </section>
        )}

        {data?.keywords?.length > 0 && (
          <ul className="mobile-chips mobile-section">
            {data.keywords.map((keyword) => (
              <li key={keyword}>#{keyword}</li>
            ))}
          </ul>
        )}

        <TextList title="핵심 포인트" items={data?.key_points} />
        <TextList title="학습 포인트" items={data?.learningPoints} />
        <TextList title="실습 팁" items={data?.practicePoints} />
        <TextList title="확인 질문" items={data?.studyQuestions} />
      </>
    </ScreenState>
  );
}
