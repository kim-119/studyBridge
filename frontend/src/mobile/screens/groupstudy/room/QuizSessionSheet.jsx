import React from 'react';
import BottomSheet from '../../../components/BottomSheet';
import Button from '../../../components/Button';
import { QUIZ_PHASE, isQuizActive } from '../quizSessionModel';

function optionClassName(quiz, index) {
  const isSelected = quiz.selectedAnswer === index;
  const isCorrect = quiz.reveal?.correctAnswer === index;
  const isWrongPick = Boolean(quiz.reveal) && isSelected && !isCorrect;

  return ['mobile-quiz__option', isSelected ? 'is-selected' : '', isCorrect ? 'is-correct' : '', isWrongPick ? 'is-wrong' : '']
    .filter(Boolean)
    .join(' ');
}

function QuizProgress({ quiz, remainingSeconds }) {
  const limit = quiz.question.timeLimitSeconds || 30;
  const ratio = Math.min(100, (remainingSeconds / limit) * 100);
  const isCounting = quiz.phase === QUIZ_PHASE.QUESTION || quiz.phase === QUIZ_PHASE.NEXT;

  return (
    <div className="mobile-room-quiz__progress">
      <p className="mobile-card__meta">
        문제 {quiz.question.currentIndex + 1} / {quiz.question.totalQuestions}
        {isCounting && ` · 남은 시간 ${remainingSeconds}초`}
      </p>
      {isCounting && (
        <span className="mobile-prejoin__meter">
          <span style={{ width: `${ratio}%` }} />
        </span>
      )}
    </div>
  );
}

function Scoreboard({ scoreboard, userId }) {
  return (
    <section className="mobile-section">
      <h3 className="mobile-section__title">실시간 랭킹 (누적 포인트)</h3>
      <ol className="mobile-room-quiz__ranking">
        {scoreboard.map((entry, index) => {
          const isMe = Number(entry.userId) === Number(userId);
          return (
            <li key={entry.userId ?? index} className={isMe ? 'is-me' : ''}>
              <span>{index + 1}위</span>
              <span className="mobile-room-quiz__player">
                {entry.displayName}
                {isMe && ' (나)'}
              </span>
              <span>{entry.points} P</span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function PhaseMessage({ quiz }) {
  if (quiz.phase === QUIZ_PHASE.REVEAL && quiz.reveal) {
    return (
      <p className="mobile-room-quiz__notice">
        정답은 보기 {Number(quiz.reveal.correctAnswer) + 1}입니다. 포인트가 반영되었습니다.
      </p>
    );
  }

  if (quiz.phase === QUIZ_PHASE.ENDED) {
    return <p className="mobile-room-quiz__notice">모든 문제가 종료되었습니다. 최종 점수판을 확인하세요.</p>;
  }

  if (quiz.hasSubmitted) {
    return <p className="mobile-field__hint">제출 완료. 제한 시간이 끝나면 정답이 공개됩니다.</p>;
  }

  return null;
}

export default function QuizSessionSheet({ room, userId }) {
  const { quiz } = room;
  if (!isQuizActive(quiz)) return null;

  const isEnded = quiz.phase === QUIZ_PHASE.ENDED;

  return (
    <BottomSheet title={quiz.question.quizTitle || '실시간 퀴즈'} isOpen onClose={room.dismissQuiz}>
      <QuizProgress quiz={quiz} remainingSeconds={room.quizRemainingSeconds} />
      <p className="mobile-quiz__stem">{quiz.question.questionText}</p>

      {!isEnded && (
        <ul className="mobile-quiz__options">
          {quiz.question.options.map((option, index) => (
            <li key={`${quiz.question.questionId}-${index}`}>
              <button
                type="button"
                className={optionClassName(quiz, index)}
                disabled={!room.canAnswerQuiz}
                onClick={() => room.submitAnswer(index)}
              >
                {index + 1}. {option}
              </button>
            </li>
          ))}
        </ul>
      )}

      <PhaseMessage quiz={quiz} />
      {room.quizError && <p className="mobile-auth__error">{room.quizError}</p>}
      {quiz.scoreboard && <Scoreboard scoreboard={quiz.scoreboard} userId={userId} />}

      {isEnded && (
        <Button fullWidth variant="secondary" onClick={room.dismissQuiz}>
          퀴즈 종료
        </Button>
      )}
    </BottomSheet>
  );
}
