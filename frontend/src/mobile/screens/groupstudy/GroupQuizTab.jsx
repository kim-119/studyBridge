import React, { useMemo, useState } from 'react';
import { Play } from 'lucide-react';
import Button from '../../components/Button';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import { useGroupSocket } from './useGroupSocket';

const PHASE_LABEL = {
  WAITING: '대기 중',
  QUESTION: '문제 풀이',
  REVEAL: '정답 공개',
  FINISHED: '종료',
};

export default function GroupQuizTab({ groupId }) {
  const { userId } = useAuth();
  const [session, setSession] = useState(null);
  const [selected, setSelected] = useState(null);
  const [socketError, setSocketError] = useState(null);

  const quizzes = useAsync(() => groupService.getGroupQuizzes(groupId), [groupId]);
  const currentSession = useAsync(() => groupService.getQuizSession(groupId), [groupId]);

  const socket = useGroupSocket(
    groupId,
    useMemo(
      () => ({
        'quiz/session': (payload) => setSession(payload),
        'quiz/question': (payload) => {
          setSelected(null);
          setSession((previous) => ({ ...(previous || {}), ...payload, phase: 'QUESTION' }));
        },
        'quiz/next': (payload) => {
          setSelected(null);
          setSession((previous) => ({ ...(previous || {}), ...payload }));
        },
        'quiz/timer': (payload) =>
          setSession((previous) => ({ ...(previous || {}), remainingSeconds: payload?.remainingSeconds })),
        'quiz/reveal': (payload) =>
          setSession((previous) => ({ ...(previous || {}), ...payload, phase: 'REVEAL' })),
        'quiz/error': (payload) => setSocketError(payload?.message || '퀴즈를 시작하지 못했습니다.'),
      }),
      []
    )
  );

  const active = session || currentSession.data;

  const startQuiz = (quizId) => {
    setSocketError(null);
    const sent = socket.publish('quiz/start', { quizId, userId: Number(userId) });
    if (!sent) setSocketError('실시간 연결이 준비되지 않았습니다. 잠시 후 다시 시도해주세요.');
  };

  const submitAnswer = (answerIndex) => {
    setSelected(answerIndex);
    socket.publish('quiz/submit', {
      userId: Number(userId),
      questionId: active?.questionId,
      submittedAnswer: answerIndex,
      timeTakenSeconds: Math.max(0, (active?.timeLimitSeconds ?? 0) - (active?.remainingSeconds ?? 0)),
    });
  };

  if (active && active.phase && active.phase !== 'FINISHED') {
    return (
      <section>
        <div className="mobile-card mobile-section">
          <p className="mobile-card__meta">
            {[PHASE_LABEL[active.phase] || active.phase,
              active.currentIndex != null && active.totalQuestions
                ? `${active.currentIndex + 1}/${active.totalQuestions}`
                : null,
              active.remainingSeconds != null ? `${active.remainingSeconds}초` : null]
              .filter(Boolean)
              .join(' · ')}
          </p>

          <p className="mobile-quiz__stem">{active.questionText}</p>

          <ul className="mobile-quiz__options">
            {(active.options || []).map((option, index) => {
              const isAnswer = active.phase === 'REVEAL' && index === active.correctAnswer;
              const isWrongPick = active.phase === 'REVEAL' && selected === index && !isAnswer;

              return (
                <li key={`${active.questionId}-${index}`}>
                  <button
                    type="button"
                    className={[
                      'mobile-quiz__option',
                      selected === index ? 'is-selected' : '',
                      isAnswer ? 'is-correct' : '',
                      isWrongPick ? 'is-wrong' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    disabled={active.phase !== 'QUESTION' || selected != null}
                    onClick={() => submitAnswer(index)}
                  >
                    {option}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {socketError && <p className="mobile-auth__error">{socketError}</p>}
      </section>
    );
  }

  return (
    <ScreenState query={quizzes} loadingLabel="퀴즈를 불러오는 중입니다">
      <>
        {!socket.isConnected && (
          <p className="mobile-chat__status">실시간 연결을 준비하는 중입니다</p>
        )}

        {socketError && <p className="mobile-auth__error">{socketError}</p>}

        {(quizzes.data || []).length === 0 ? (
          <EmptyState message="공유된 퀴즈가 없습니다. 웹에서 학습자료 기반 퀴즈를 먼저 생성해주세요." />
        ) : (
          <ul className="mobile-list">
            {(quizzes.data || []).map((quiz) => (
              <li key={quiz.quizId ?? quiz.id}>
                <ListRow
                  title={quiz.title || quiz.quizTitle || '그룹 퀴즈'}
                  subtitle={quiz.questionCount ? `${quiz.questionCount}문항` : undefined}
                  trailing={
                    <Button variant="ghost" onClick={() => startQuiz(quiz.quizId ?? quiz.id)}>
                      <Play size={16} />
                      시작
                    </Button>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </>
    </ScreenState>
  );
}
