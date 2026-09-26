import React, { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { reviewNoteService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { toQuizQuestions } from '../archive/quizModel';

/**
 * 다시 풀기는 문제당 1회다. 서버가 이미 기록한 결과(retryResults)는 잠그고,
 * 제출 payload 의 index 는 서버 계약에 맞춰 1-based 로 보낸다.
 */
export default function ReviewNoteRetryScreen() {
  const { reviewNoteId } = useParams();
  const navigate = useNavigate();
  const [selections, setSelections] = useState({});
  const [isSubmitted, setSubmitted] = useState(false);

  const retry = useAsync(() => reviewNoteService.retry(reviewNoteId), [reviewNoteId]);

  const questions = useMemo(
    () => toQuizQuestions({ quizzes: retry.data?.questions || [] }),
    [retry.data]
  );

  const lockedIndexes = useMemo(() => {
    const saved = retry.data?.retryResults || [];
    return new Set(saved.map((entry) => Number(entry.index) - 1));
  }, [retry.data]);

  const answeredCount = questions.filter(
    (_, index) => selections[index] != null || lockedIndexes.has(index)
  ).length;

  const submitResults = useSubmit(async () => {
    const results = questions
      .map((question, index) => {
        if (selections[index] == null || lockedIndexes.has(index)) return null;

        return {
          index: index + 1,
          userAnswer: question.options[selections[index]] ?? '',
          correct: selections[index] === question.answerIndex,
        };
      })
      .filter(Boolean);

    if (results.length === 0) return;

    await reviewNoteService.submitRetryResult(reviewNoteId, results);
    setSubmitted(true);
    await retry.reload();
  });

  return (
    <MobileScreen title="다시 풀기" showBackButton>
      <ScreenState
        query={retry}
        loadingLabel="문제를 불러오는 중입니다"
        emptyWhen={() => questions.length === 0}
        emptyMessage="다시 풀 문제가 없습니다."
      >
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">복습 진행률</p>
            <p className="mobile-stat">
              {answeredCount}/{questions.length}
            </p>
            <div className="mobile-progress">
              <span
                style={{
                  width: `${questions.length ? Math.round((answeredCount / questions.length) * 100) : 0}%`,
                }}
              />
            </div>
          </section>

          {questions.length === 0 ? (
            <EmptyState message="다시 풀 문제가 없습니다." />
          ) : (
            <ul className="mobile-list">
              {questions.map((question, index) => {
                const isLocked = lockedIndexes.has(index);
                const showAnswer = isLocked || isSubmitted;

                return (
                  <li key={question.id} className="mobile-card mobile-section">
                    <p className="mobile-quiz__stem">
                      {index + 1}. {question.stem}
                    </p>

                    <ul className="mobile-quiz__options">
                      {question.options.map((option, optionIndex) => {
                        const isSelected = selections[index] === optionIndex;
                        const isAnswer = showAnswer && optionIndex === question.answerIndex;
                        const isWrongPick = showAnswer && isSelected && !isAnswer;

                        return (
                          <li key={`${question.id}-${optionIndex}`}>
                            <button
                              type="button"
                              className={[
                                'mobile-quiz__option',
                                isSelected ? 'is-selected' : '',
                                isAnswer ? 'is-correct' : '',
                                isWrongPick ? 'is-wrong' : '',
                              ]
                                .filter(Boolean)
                                .join(' ')}
                              disabled={isLocked || isSubmitted}
                              onClick={() =>
                                setSelections((previous) => ({ ...previous, [index]: optionIndex }))
                              }
                            >
                              {option}
                            </button>
                          </li>
                        );
                      })}
                    </ul>

                    {isLocked && <p className="mobile-quiz__explanation">이미 제출한 문항입니다.</p>}
                    {showAnswer && question.explanation && (
                      <p className="mobile-quiz__explanation">{question.explanation}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {submitResults.errorMessage && (
            <p className="mobile-auth__error">{submitResults.errorMessage}</p>
          )}

          <Button
            fullWidth
            isLoading={submitResults.isSubmitting}
            disabled={isSubmitted || Object.keys(selections).length === 0}
            onClick={() => submitResults.submit().catch(() => {})}
          >
            {isSubmitted ? '제출 완료' : '결과 제출'}
          </Button>

          {isSubmitted && (
            <Button
              fullWidth
              variant="secondary"
              onClick={() => navigate(`/review-notes/${reviewNoteId}`, { replace: true })}
            >
              오답노트로 돌아가기
            </Button>
          )}
        </>
      </ScreenState>
    </MobileScreen>
  );
}
