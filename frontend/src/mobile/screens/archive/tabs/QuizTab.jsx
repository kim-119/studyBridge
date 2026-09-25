import React, { useMemo, useState } from 'react';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { useAsync, useSubmit } from '../../../data/useAsync';

const DIFFICULTY_OPTIONS = [
  { key: 'easy', label: '쉬움' },
  { key: 'normal', label: '보통' },
  { key: 'hard', label: '어려움' },
];

function parseQuestions(quiz) {
  if (Array.isArray(quiz?.quizzes) && quiz.quizzes.length > 0) return quiz.quizzes;

  if (typeof quiz?.quizData === 'string') {
    try {
      const parsed = JSON.parse(quiz.quizData);
      if (Array.isArray(parsed)) return parsed;
      if (Array.isArray(parsed?.quizzes)) return parsed.quizzes;
      if (Array.isArray(parsed?.questions)) return parsed.questions;
    } catch {
      return [];
    }
  }

  return [];
}

function questionOptions(question) {
  const raw = question.options || question.choices || question.answers;
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === 'object') return Object.values(raw);
  return [];
}

function correctAnswerOf(question) {
  return question.answer ?? question.correctAnswer ?? question.correct_answer;
}

function QuestionCard({ question, index, selected, onSelect, isRevealed }) {
  const options = questionOptions(question);
  const answer = correctAnswerOf(question);

  return (
    <li className="mobile-card mobile-section">
      <p className="mobile-quiz__stem">
        {index + 1}. {question.question || question.stem || question.title}
      </p>

      <ul className="mobile-quiz__options">
        {options.map((option, optionIndex) => {
          const value = typeof option === 'string' ? option : option.text ?? String(option);
          const isSelected = selected === optionIndex;
          const isCorrect = isRevealed && String(answer) === String(optionIndex + 1);

          return (
            <li key={value}>
              <button
                type="button"
                className={[
                  'mobile-quiz__option',
                  isSelected ? 'is-selected' : '',
                  isCorrect ? 'is-correct' : '',
                ]
                  .filter(Boolean)
                  .join(' ')}
                onClick={() => onSelect(optionIndex)}
              >
                {value}
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

  const latestQuiz = useMemo(() => {
    const list = Array.isArray(quiz.data) ? quiz.data : quiz.data ? [quiz.data] : [];
    return list[list.length - 1] || null;
  }, [quiz.data]);

  const questions = useMemo(() => parseQuestions(latestQuiz), [latestQuiz]);

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

  const correctCount = questions.reduce((total, question, index) => {
    const answer = correctAnswerOf(question);
    return String(answer) === String((selections[index] ?? -1) + 1) ? total + 1 : total;
  }, 0);

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
                  key={question.question || question.stem || index}
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
              {isRevealed ? `정답 숨기기 (${correctCount}/${questions.length})` : '채점하기'}
            </Button>
          </>
        )}
      </>
    </ScreenState>
  );
}
