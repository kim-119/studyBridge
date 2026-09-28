import React from 'react';
import Button from '../../components/Button';
import { EmptyState } from '../../components/ScreenState';
import { describeApiError } from '../../data/useAsync';
import {
  VARIANT_COUNTS,
  VARIANT_LEVELS,
  cleanText,
  correctChoiceText,
  difficultyLabel,
  isCorrectChoice,
  similarQuestionStatus,
  wrongQuestionNumbers,
} from './reviewNoteModel';
import { canRequestMissing, missingRequestMessage, variantCountMessage } from './variantCountModel';

const STATUS_TONE = { 정답: 'done', 오답: 'alert', '풀이 전': 'idle' };

function variantErrorMessage(error) {
  const data = error?.response?.data;
  const serverMessage = data?.message || data?.error || (typeof data === 'string' ? data : '');
  if (serverMessage) return `유사문제를 생성하지 못했습니다: ${serverMessage}`;
  return describeApiError(error);
}

function choiceClassName({ isPicked, showCorrect, showWrongPick }) {
  return [
    'mobile-quiz__option',
    isPicked ? 'is-selected' : '',
    showCorrect ? 'is-correct' : '',
    showWrongPick ? 'is-wrong' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

function VariantSettings({ note, settings, onChange }) {
  const update = (field) => (value) => onChange({ ...settings, [field]: value });

  return (
    <div className="mobile-review__settings">
      <label className="mobile-review__setting">
        <span className="mobile-field__label">대상 오답</span>
        <select
          className="mobile-select"
          value={settings.wrongQuestionId}
          onChange={(event) => update('wrongQuestionId')(Number(event.target.value))}
        >
          {wrongQuestionNumbers(note).map((number) => (
            <option key={number} value={number}>
              {number}번 오답
            </option>
          ))}
        </select>
      </label>

      <label className="mobile-review__setting">
        <span className="mobile-field__label">문항 수</span>
        <select
          className="mobile-select"
          value={settings.count}
          onChange={(event) => update('count')(Number(event.target.value))}
        >
          {VARIANT_COUNTS.map((count) => (
            <option key={count} value={count}>
              {count}개
            </option>
          ))}
        </select>
      </label>

      <div className="mobile-review__setting mobile-review__setting--wide">
        <span className="mobile-field__label">난이도</span>
        <div className="mobile-review__levels" role="radiogroup" aria-label="난이도">
          {VARIANT_LEVELS.map((level) => (
            <button
              key={level.value}
              type="button"
              role="radio"
              aria-checked={settings.difficulty === level.value}
              className={settings.difficulty === level.value ? 'is-active' : ''}
              onClick={() => update('difficulty')(level.value)}
            >
              {level.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function SimilarQuestionList({ questions, activeId, answers, submitted, onSelect }) {
  return (
    <ul className="mobile-list mobile-section">
      {questions.map((question) => {
        const status = similarQuestionStatus(question, answers[question.id], submitted[question.id]);
        return (
          <li key={question.id}>
            <button
              type="button"
              className={question.id === activeId ? 'mobile-review__item is-active' : 'mobile-review__item'}
              onClick={() => onSelect(question.id)}
            >
              <span className="mobile-review__badges">
                <span className="mobile-review__badge">{question.number}번</span>
                {question.difficulty && (
                  <span className="mobile-review__badge mobile-review__badge--muted">
                    {difficultyLabel(question.difficulty)}
                  </span>
                )}
                <span className={`mobile-review__badge mobile-review__badge--${STATUS_TONE[status]}`}>
                  {status}
                </span>
              </span>
              <span className="mobile-review__item-text">{cleanText(question.question)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function SimilarQuestionResult({ question, pickedIndex }) {
  const picked = question.choices[pickedIndex];
  const isRight = picked != null && isCorrectChoice(picked, pickedIndex, question.answer);

  return (
    <div className="mobile-review__result">
      <p className={isRight ? 'mobile-review__verdict is-right' : 'mobile-review__verdict is-wrong'}>
        {isRight ? '정답입니다!' : '오답입니다.'}
      </p>
      <p className="mobile-review__answer">정답: {cleanText(correctChoiceText(question))}</p>
      {question.explanation && (
        <p className="mobile-paragraph">해설: {cleanText(question.explanation)}</p>
      )}
      {question.variationPoint && (
        <p className="mobile-review__callout">
          <strong>변형 포인트 </strong>
          {cleanText(question.variationPoint)}
        </p>
      )}
    </div>
  );
}

function SimilarQuestionSolver({ question, pickedIndex, isSubmitted, onPick, onSubmit }) {
  return (
    <div className="mobile-card mobile-review__solver">
      <p className="mobile-quiz__stem">
        {question.number}. {cleanText(question.question)}
      </p>

      {question.choices.length === 0 ? (
        <p className="mobile-card__meta">이 문제에는 선택지가 없습니다.</p>
      ) : (
        <ul className="mobile-quiz__options">
          {question.choices.map((choice, index) => {
            const isChoiceCorrect = isCorrectChoice(choice, index, question.answer);
            return (
              <li key={`${question.id}-${index}`}>
                <button
                  type="button"
                  className={choiceClassName({
                    isPicked: pickedIndex === index,
                    showCorrect: isSubmitted && isChoiceCorrect,
                    showWrongPick: isSubmitted && pickedIndex === index && !isChoiceCorrect,
                  })}
                  disabled={isSubmitted}
                  onClick={() => onPick(index)}
                >
                  {index + 1}. {cleanText(choice)}
                </button>
              </li>
            );
          })}
        </ul>
      )}

      {isSubmitted ? (
        <SimilarQuestionResult question={question} pickedIndex={pickedIndex} />
      ) : (
        <Button fullWidth disabled={pickedIndex == null} onClick={onSubmit}>
          제출
        </Button>
      )}
    </div>
  );
}

function VariantCountNotice({ countCheck, missingResult, isBusy, requestMissing }) {
  const message = variantCountMessage(countCheck);
  if (!message && !missingResult) return null;

  return (
    <div className="mobile-review__count-notice" role="status">
      {message && <p className="mobile-review__warning mobile-review__count-warning">{message}</p>}
      {missingResult && (
        <p className="mobile-card__meta mobile-review__count-result">{missingRequestMessage(missingResult)}</p>
      )}
      {canRequestMissing(countCheck) && (
        <Button
          variant="secondary"
          fullWidth
          isLoading={requestMissing.isSubmitting}
          disabled={isBusy}
          onClick={() => requestMissing.submit().catch(() => {})}
        >
          부족분 {countCheck.missing}문제 다시 생성
        </Button>
      )}
      {requestMissing.error && (
        <p className="mobile-auth__error">{variantErrorMessage(requestMissing.error)}</p>
      )}
    </div>
  );
}

export default function ReviewNoteVariantPanel({ note, variant }) {
  const { session, countCheck, missingResult, generate, requestMissing, isBusy } = variant;
  const { questions, answers, submitted, activeId, hasResult, usedFallback } = session;
  const activeQuestion = questions.find((question) => question.id === activeId) || null;

  return (
    <section className="mobile-section">
      <VariantSettings note={note} settings={session.settings} onChange={variant.changeSettings} />

      <Button
        fullWidth
        isLoading={generate.isSubmitting}
        disabled={isBusy}
        onClick={() => generate.submit().catch(() => {})}
      >
        {hasResult ? '유사문제 새로 생성' : '유사문제 생성'}
      </Button>

      {generate.error && <p className="mobile-auth__error">{variantErrorMessage(generate.error)}</p>}

      {!hasResult && !generate.error && !generate.isSubmitting && (
        <p className="mobile-card__meta mobile-review__hint">
          대상 오답과 난이도·문항 수를 선택하고 유사문제를 생성해 보세요.
        </p>
      )}

      {hasResult && (
        <VariantCountNotice
          countCheck={countCheck}
          missingResult={missingResult}
          isBusy={isBusy}
          requestMissing={requestMissing}
        />
      )}

      {hasResult && questions.length === 0 && (
        <EmptyState message="생성된 유사문제가 없습니다. 이 오답노트에는 변형할 원본 오답 문제가 없을 수 있어요." />
      )}

      {questions.length > 0 && (
        <div className="mobile-review__hint">
          {usedFallback && (
            <p className="mobile-review__warning">
              AI 변형을 일시적으로 사용할 수 없어 원본 오답 문제를 다시 출제했습니다.
            </p>
          )}

          <h3 className="mobile-section__title">
            생성된 유사문제 ({questions.length}/{countCheck.requested})
          </h3>
          <SimilarQuestionList
            questions={questions}
            activeId={activeId}
            answers={answers}
            submitted={submitted}
            onSelect={variant.selectQuestion}
          />

          <h3 className="mobile-section__title">유사문제 풀이</h3>
          {activeQuestion ? (
            <SimilarQuestionSolver
              question={activeQuestion}
              pickedIndex={answers[activeQuestion.id]}
              isSubmitted={Boolean(submitted[activeQuestion.id])}
              onPick={(index) => variant.pickAnswer(activeQuestion.id, index)}
              onSubmit={() => variant.submitAnswer(activeQuestion.id)}
            />
          ) : (
            <p className="mobile-card__meta">위 목록에서 풀 문제를 선택하세요.</p>
          )}
        </div>
      )}
    </section>
  );
}
