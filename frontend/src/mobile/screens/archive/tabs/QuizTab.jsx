import React, { useMemo, useState } from 'react';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { useAsync, useSubmit } from '../../../data/useAsync';
import { gradeQuiz, toQuizQuestions } from '../quizModel';

const DIFFICULTY_OPTIONS = [
  { key: 'easy', label: '쉬움' },
  { key: 'normal', label: '보통' },
  { key: 'hard', label: '어려움' },
];

function QuestionCard({ question, index, selected, onSelect, isRevealed }) {
  return (
    <li className="mobile-card mobile-section">
      <p className="mobile-quiz__stem">
        {index + 1}. {question.stem}
      </p>

      <ul className="mobile-quiz__options">
        {question.options.map((option, optionIndex) => {
          const isSelected = selected === optionIndex;
          const isAnswer = isRevealed && optionIndex === question.answerIndex;
          const isWrongPick = isRevealed && isSelected && optionIndex !== question.answerIndex;

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
                onClick={() => onSelect(optionIndex)}
              >
                {option}
              </button>
            </li>
          );
        })}
      </ul>

      {isRevealed && question.explanation && (
        <p className="mobile-quiz__explanation">{question.explanation}</p>
      )}
    </li>
  );
}

export default function QuizTab({ materialId }) {
  const quiz = useAsync(() => materialService.getQuizzes(materialId), [materialId]);
  const [difficulty, setDifficulty] = useState('normal');
  const [questionCount, setQuestionCount] = useState(5);
  const [selections, setSelections] = useState({});
  const [isRevealed, setRevealed] = useState(false);

  const questions = useMemo(() => {
    const list = Array.isArray(quiz.data) ? quiz.data : quiz.data ? [quiz.data] : [];
    return toQuizQuestions(list[list.length - 1] || null);
  }, [quiz.data]);

  const generateQuiz = useSubmit(async () => {
    await materialService.generateQuiz(materialId, {
      difficulty,
      questionCount: Number(questionCount),
      pageRange: '전체',
    });
    setSelections({});
    setRevealed(false);
    await quiz.reload();
  });

  const result = gradeQuiz(questions, selections);

  return (
    <ScreenState query={quiz} loadingLabel="퀴즈를 불러오는 중입니다">
      <>
        <section className="mobile-card mobile-section">
          <div className="mobile-toolbar">
            <select
              className="mobile-select"
              aria-label="난이도"
              value={difficulty}
              onChange={(event) => setDifficulty(event.target.value)}
            >
              {DIFFICULTY_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>

            <select
              className="mobile-select"
              aria-label="문항 수"
              value={questionCount}
              onChange={(event) => setQuestionCount(event.target.value)}
            >
              {[5, 10, 15, 20].map((count) => (
                <option key={count} value={count}>
                  {count}문항
                </option>
              ))}
            </select>
          </div>

          <Button
            fullWidth
            isLoading={generateQuiz.isSubmitting}
            onClick={() => generateQuiz.submit().catch(() => {})}
          >
            퀴즈 생성
          </Button>

          {generateQuiz.errorMessage && (
            <p className="mobile-auth__error">{generateQuiz.errorMessage}</p>
          )}
        </section>

        {questions.length === 0 ? (
          <EmptyState message="아직 생성된 퀴즈가 없습니다. 난이도와 문항 수를 정해 퀴즈를 만들어보세요." />
        ) : (
          <>
            <ul className="mobile-list">
              {questions.map((question, index) => (
                <QuestionCard
                  key={question.id}
                  question={question}
                  index={index}
                  selected={selections[index]}
                  isRevealed={isRevealed}
                  onSelect={(optionIndex) =>
                    setSelections((previous) => ({ ...previous, [index]: optionIndex }))
                  }
                />
              ))}
            </ul>

            <Button fullWidth variant="secondary" onClick={() => setRevealed((value) => !value)}>
              {isRevealed
                ? `정답 숨기기 (${result.correct}/${result.total})`
                : `채점하기 (${result.answered}/${result.total} 응답)`}
            </Button>
          </>
        )}
      </>
    </ScreenState>
  );
}
