import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../components/Button';
import ScreenState, { EmptyState } from '../../../components/ScreenState';
import { materialService, reviewNoteService } from '../../../../services/api';
import { backgroundTasks } from '../../../data/backgroundTasks';
import { describeApiError, useAsync, useSubmit } from '../../../data/useAsync';
import { useBackgroundTask } from '../../../data/useBackgroundTask';
import ConfirmAction from '../../groupstudy/ConfirmAction';
import { aiExceptionMessage, aiFailureMessage } from '../aiResponseModel';
import { formatDate } from '../archiveDomain';
import { reviewNotePath } from '../archiveNavigation';
import {
  DEFAULT_QUESTION_COUNT,
  GENERATING_MESSAGE,
  describeServerScore,
  materialQuizTaskKey,
  mergeGeneratedQuiz,
  startMaterialQuizGeneration,
} from '../materialQuizGeneration';
import {
  QUESTION_OUTCOME,
  countOutcomes,
  firstOptionId,
  hasAnySelection,
  isQuizFailed,
  needsReviewNote,
  outcomeOf,
  resultsByQuestionId,
  selectionsFromResult,
  toPublicQuestions,
  toReviewNoteAnswers,
  toSubmissionAnswers,
} from '../materialQuizModel';
import { newestQuizzesFirst } from '../quizModel';

const DIFFICULTY_OPTIONS = ['쉬움', '보통', '어려움'];
const QUESTION_COUNT_OPTIONS = [5, 10, 15, 20];

const OUTCOME_LABEL = {
  [QUESTION_OUTCOME.CORRECT]: '정답',
  [QUESTION_OUTCOME.WRONG]: '오답',
  [QUESTION_OUTCOME.UNANSWERED]: '미응답',
};

function aiErrorText(error) {
  return error?.userMessage || aiExceptionMessage(error) || describeApiError(error);
}

function serverMessageOf(submitState) {
  return submitState.error?.response?.data?.message || submitState.errorMessage;
}

function quizLabel(quiz, index) {
  const count = toPublicQuestions(quiz).length;
  const lastScore = typeof quiz.lastResult?.score === 'number' ? `최근 ${quiz.lastResult.score}점` : null;
  const parts = [formatDate(quiz.createdAt), quiz.difficulty, count ? `${count}문항` : null, lastScore].filter(Boolean);
  return `${index === 0 ? '최신 · ' : ''}${parts.join(' · ') || `퀴즈 ${quiz.quizId}`}`;
}

function optionClassName({ isSelected, isGraded, isCorrectOption }) {
  return [
    'mobile-quiz__option',
    isSelected ? 'is-selected' : '',
    isGraded && isCorrectOption ? 'is-correct' : '',
    isGraded && isSelected && !isCorrectOption ? 'is-wrong' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

function QuestionCard({ question, index, selectedOptionId, questionResult, isGraded, onSelect }) {
  const outcome = outcomeOf(questionResult);
  const correctOptionId = isGraded ? firstOptionId(questionResult?.correctOptionIds) : null;
  const correctOption = question.options.find((option) => option.optionId === correctOptionId);

  return (
    <li className="mobile-card">
      {isGraded && <span className={`mobile-quiz__outcome is-${outcome}`}>{OUTCOME_LABEL[outcome]}</span>}
      <p className="mobile-quiz__stem">
        {index + 1}. {question.stem}
      </p>

      <ul className="mobile-quiz__options">
        {question.options.map((option) => (
          <li key={`${question.questionId}-${option.optionId}`}>
            <button
              type="button"
              className={optionClassName({
                isSelected: selectedOptionId === option.optionId,
                isGraded,
                isCorrectOption: option.optionId === correctOptionId,
              })}
              aria-pressed={selectedOptionId === option.optionId}
              disabled={isGraded}
              onClick={() => onSelect(option.optionId)}
            >
              {option.text}
            </button>
          </li>
        ))}
      </ul>

      {isGraded && outcome !== QUESTION_OUTCOME.CORRECT && correctOption && (
        <p className="mobile-quiz__explanation">정답: {correctOption.text}</p>
      )}
      {isGraded && questionResult?.explanation && (
        <p className="mobile-quiz__explanation">해설: {questionResult.explanation}</p>
      )}
    </li>
  );
}

function ScoreSummary({ result, outcomeCounts }) {
  return (
    <section className="mobile-card mobile-section">
      <h3 className="mobile-section__title">{describeServerScore(result)}</h3>
      <dl className="mobile-quiz__result">
        <div>
          <dt>정답</dt>
          <dd>{outcomeCounts.correct}</dd>
        </div>
        <div>
          <dt>오답</dt>
          <dd>{outcomeCounts.wrong}</dd>
        </div>
        <div>
          <dt>미응답</dt>
          <dd>{outcomeCounts.unanswered}</dd>
        </div>
      </dl>
    </section>
  );
}

function QuizGenerator({ generation, onGenerate }) {
  const [difficulty, setDifficulty] = useState('보통');
  const [questionCount, setQuestionCount] = useState(DEFAULT_QUESTION_COUNT);

  return (
    <section className="mobile-card mobile-section">
      <div className="mobile-toolbar">
        <select
          className="mobile-select"
          aria-label="난이도"
          value={difficulty}
          disabled={generation.isGenerating}
          onChange={(event) => setDifficulty(event.target.value)}
        >
          {DIFFICULTY_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>

        <select
          className="mobile-select"
          aria-label="문항 수"
          value={questionCount}
          disabled={generation.isGenerating}
          onChange={(event) => setQuestionCount(event.target.value)}
        >
          {QUESTION_COUNT_OPTIONS.map((count) => (
            <option key={count} value={count}>
              {count}문항
            </option>
          ))}
        </select>
      </div>

      <Button
        fullWidth
        isLoading={generation.isGenerating}
        onClick={() => onGenerate({ difficulty, questionCount })}
      >
        {generation.isFailed ? '다시 시도' : '새 퀴즈 생성'}
      </Button>

      {generation.isGenerating && (
        <p className="mobile-field__hint mobile-archive-gap" role="status" data-quiz-generation="generating">
          {GENERATING_MESSAGE} 다른 화면으로 이동해도 생성은 계속됩니다.
        </p>
      )}
      {generation.isFailed && (
        <p className="mobile-auth__error mobile-archive-gap" role="alert" data-quiz-generation="failed">
          {aiErrorText(generation.error)}
        </p>
      )}
    </section>
  );
}

function refreshQuizzesQuietly(materialId, setData) {
  materialService
    .getQuizzes(materialId)
    .then(setData)
    .catch((error) => console.warn('퀴즈 목록을 새로 고치지 못했습니다.', error));
}

function useMaterialQuizGeneration(materialId, quizzes, onQuizReady) {
  const generation = useBackgroundTask(materialQuizTaskKey(materialId));
  const [generated, setGenerated] = useState(null);
  const onQuizReadyRef = useRef(onQuizReady);
  onQuizReadyRef.current = onQuizReady;
  const { isReady, isFailed, result, reset } = generation;
  const { reload, setData } = quizzes;

  useEffect(() => {
    if (!isReady) return;
    setGenerated({ materialId, quiz: result });
    onQuizReadyRef.current(result?.quizId ?? null);
    reset();
    refreshQuizzesQuietly(materialId, setData);
  }, [isReady, result, reset, materialId, setData]);

  useEffect(() => {
    if (isFailed) reload().catch(() => {});
  }, [isFailed, reload]);

  const generate = (options) => {
    startMaterialQuizGeneration(backgroundTasks, {
      materialId,
      options,
      generateQuiz: materialService.generateQuiz,
    }).catch((error) => console.warn('자료 퀴즈 생성에 실패했습니다.', error));
  };

  const isCurrentQuiz = generated?.materialId === materialId && generated.quiz?.quizId != null;
  const generatedQuiz = isCurrentQuiz ? generated.quiz : null;
  return { generation, generate, generatedQuiz };
}

function quizListQueryOf(quizzes, generatedQuiz) {
  if (!generatedQuiz) return quizzes;
  return { ...quizzes, isLoading: false, isError: false };
}

function ReviewNoteAction({ quiz, material, questions, selections }) {
  const navigate = useNavigate();
  const [createdNote, setCreatedNote] = useState(null);

  const createReviewNote = useSubmit(async () => {
    const note = await reviewNoteService.createFromQuiz(quiz.quizId, toReviewNoteAnswers(questions, selections), {
      materialId: Number(material.materialId),
      materialTitle: material.title,
      difficulty: quiz.difficulty,
    });
    setCreatedNote(note);
  });

  if (createdNote?.id != null) {
    return (
      <Button fullWidth variant="action" onClick={() => navigate(reviewNotePath(createdNote.id))}>
        오답노트 보기
      </Button>
    );
  }

  return (
    <>
      <Button
        fullWidth
        variant="action"
        isLoading={createReviewNote.isSubmitting}
        onClick={() => createReviewNote.submit().catch(() => {})}
      >
        오답노트 만들기
      </Button>
      {createReviewNote.errorMessage && (
        <p className="mobile-auth__error mobile-archive-gap">{serverMessageOf(createReviewNote)}</p>
      )}
    </>
  );
}

function QuizSheet({ quiz, material, onGraded, onDeleted }) {
  const questions = useMemo(() => toPublicQuestions(quiz), [quiz]);
  const [result, setResult] = useState(quiz.lastResult || null);
  const [selections, setSelections] = useState(() => selectionsFromResult(quiz.lastResult));
  const [validationMessage, setValidationMessage] = useState(null);

  const submitAnswers = useSubmit(async () => {
    const answers = toSubmissionAnswers(questions, selections);
    if (!hasAnySelection(answers)) {
      setValidationMessage('한 문제 이상 답을 선택한 뒤 제출해주세요.');
      return;
    }
    setValidationMessage(null);
    const graded = await materialService.submitQuiz(Number(material.materialId), quiz.quizId, answers);
    setResult(graded);
    setSelections(selectionsFromResult(graded));
    onGraded(quiz.quizId, graded);
  });

  const deleteQuiz = useSubmit(async () => {
    await materialService.deleteQuiz(Number(material.materialId), quiz.quizId);
    onDeleted(quiz.quizId);
  });

  if (isQuizFailed(quiz)) {
    return <p className="mobile-auth__error">{aiFailureMessage(quiz)}</p>;
  }

  if (questions.length === 0) {
    return <EmptyState message="이 퀴즈에는 표시할 문항이 없습니다. 새 퀴즈를 생성해주세요." />;
  }

  const isGraded = Boolean(result);
  const byQuestionId = resultsByQuestionId(result);
  const outcomeCounts = countOutcomes(questions, result);
  const selectedCount = Object.keys(selections).length;

  const selectOption = (questionId, optionId) => {
    if (isGraded) return;
    setSelections((previous) => ({ ...previous, [questionId]: optionId }));
  };

  const restart = () => {
    setSelections({});
    setResult(null);
  };

  return (
    <>
      {isGraded && <ScoreSummary result={result} outcomeCounts={outcomeCounts} />}

      <ul className="mobile-list mobile-section">
        {questions.map((question, index) => (
          <QuestionCard
            key={question.questionId}
            question={question}
            index={index}
            selectedOptionId={selections[question.questionId]}
            questionResult={byQuestionId[question.questionId]}
            isGraded={isGraded}
            onSelect={(optionId) => selectOption(question.questionId, optionId)}
          />
        ))}
      </ul>

      {isGraded ? (
        <div className="mobile-archive-stack">
          {needsReviewNote(outcomeCounts) && typeof quiz.quizId === 'number' && (
            <ReviewNoteAction quiz={quiz} material={material} questions={questions} selections={selections} />
          )}
          <Button fullWidth variant="ghost" onClick={restart}>
            다시 풀기
          </Button>
        </div>
      ) : (
        <Button fullWidth isLoading={submitAnswers.isSubmitting} onClick={() => submitAnswers.submit().catch(() => {})}>
          제출 ({selectedCount}/{questions.length} 응답)
        </Button>
      )}

      {validationMessage && <p className="mobile-auth__error mobile-archive-gap">{validationMessage}</p>}
      {submitAnswers.errorMessage && (
        <p className="mobile-auth__error mobile-archive-gap">{serverMessageOf(submitAnswers)}</p>
      )}

      <div className="mobile-archive-stack mobile-section">
        <ConfirmAction
          label="이 퀴즈 삭제"
          confirmMessage="이 퀴즈와 채점 기록을 삭제할까요? 되돌릴 수 없습니다."
          confirmLabel="삭제"
          isLoading={deleteQuiz.isSubmitting}
          onConfirm={() => deleteQuiz.submit().catch(() => {})}
        />
        {deleteQuiz.errorMessage && <p className="mobile-auth__error">{serverMessageOf(deleteQuiz)}</p>}
      </div>
    </>
  );
}

export default function QuizTab({ material }) {
  const materialId = material.materialId;
  const quizzes = useAsync(() => materialService.getQuizzes(materialId), [materialId]);
  const [selectedQuizId, setSelectedQuizId] = useState(null);
  const [gradedByQuizId, setGradedByQuizId] = useState({});
  const [deletedQuizIds, setDeletedQuizIds] = useState(() => new Set());
  const { generation, generate, generatedQuiz } = useMaterialQuizGeneration(materialId, quizzes, setSelectedQuizId);

  const orderedQuizzes = useMemo(
    () =>
      newestQuizzesFirst(mergeGeneratedQuiz(quizzes.data, generatedQuiz))
        .filter((quiz) => !deletedQuizIds.has(quiz.quizId))
        .map((quiz) => (gradedByQuizId[quiz.quizId] ? { ...quiz, lastResult: gradedByQuizId[quiz.quizId] } : quiz)),
    [quizzes.data, generatedQuiz, deletedQuizIds, gradedByQuizId]
  );

  useEffect(() => {
    const stillExists = orderedQuizzes.some((quiz) => quiz.quizId === selectedQuizId);
    if (!stillExists) setSelectedQuizId(orderedQuizzes[0]?.quizId ?? null);
  }, [orderedQuizzes, selectedQuizId]);

  const selectedQuiz = orderedQuizzes.find((quiz) => quiz.quizId === selectedQuizId) || null;

  const rememberGrade = (quizId, result) => {
    setGradedByQuizId((previous) => ({ ...previous, [quizId]: result }));
  };

  const forgetQuiz = (quizId) => {
    setDeletedQuizIds((previous) => new Set(previous).add(quizId));
  };

  return (
    <>
      <QuizGenerator generation={generation} onGenerate={generate} />

      <ScreenState query={quizListQueryOf(quizzes, generatedQuiz)} loadingLabel="퀴즈를 불러오는 중입니다">
        {isQuizFailed(quizzes.data) ? (
          <p className="mobile-auth__error">{aiFailureMessage(quizzes.data)}</p>
        ) : orderedQuizzes.length === 0 ? (
          <EmptyState message="아직 생성된 퀴즈가 없습니다. 난이도와 문항 수를 정해 퀴즈를 만들어보세요." />
        ) : (
          <>
            {orderedQuizzes.length > 1 && (
              <select
                className="mobile-select mobile-archive-fill mobile-section"
                aria-label="풀 퀴즈 선택"
                value={selectedQuizId ?? ''}
                onChange={(event) => setSelectedQuizId(Number(event.target.value))}
              >
                {orderedQuizzes.map((quiz, index) => (
                  <option key={quiz.quizId} value={quiz.quizId}>
                    {quizLabel(quiz, index)}
                  </option>
                ))}
              </select>
            )}

            {selectedQuiz && (
              <QuizSheet
                key={selectedQuiz.quizId}
                quiz={selectedQuiz}
                material={material}
                onGraded={rememberGrade}
                onDeleted={forgetQuiz}
              />
            )}
          </>
        )}
      </ScreenState>
    </>
  );
}
