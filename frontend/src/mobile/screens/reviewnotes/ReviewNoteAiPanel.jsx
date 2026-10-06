import React from 'react';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import { reviewNoteService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { cleanText, explanationSummary } from './reviewNoteModel';

function retryQuestionsOf(response) {
  return Array.isArray(response?.questions) ? response.questions : [];
}

function QuestionExplanation({ question, number }) {
  const correctAnswer = question.correctAnswer ?? question.correct_answer;

  return (
    <li className="mobile-card">
      <p className="mobile-quiz__stem">
        {number}. {cleanText(question.question)}
      </p>
      <p className="mobile-review__answer">정답: {cleanText(correctAnswer)}</p>
      {question.explanation && <p className="mobile-paragraph">{cleanText(question.explanation)}</p>}
    </li>
  );
}

export default function ReviewNoteAiPanel({ reviewNoteId, note }) {
  const retry = useAsync(() => reviewNoteService.retry(reviewNoteId), [reviewNoteId]);
  const summary = explanationSummary(note);
  const questions = retryQuestionsOf(retry.data);

  return (
    <section className="mobile-section">
      {summary && (
        <div className="mobile-review__callout mobile-section">
          <strong>전체 AI 해설 요약</strong>
          <p className="mobile-paragraph">{cleanText(summary)}</p>
        </div>
      )}

      <ScreenState query={retry} loadingLabel="AI 해설을 불러오는 중입니다">
        {questions.length === 0 ? (
          <EmptyState message="표시할 문제별 해설이 없습니다. PDF 오답노트에서 상세 해설을 확인할 수 있습니다." />
        ) : (
          <ul className="mobile-list">
            {questions.map((question, index) => (
              <QuestionExplanation key={index} question={question} number={index + 1} />
            ))}
          </ul>
        )}
      </ScreenState>
    </section>
  );
}
