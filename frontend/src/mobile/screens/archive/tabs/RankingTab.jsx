import React, { useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import ScreenState, { EmptyState, ErrorState, LoadingState } from '../../../components/ScreenState';
import { materialService } from '../../../../services/api';
import { useAsync } from '../../../data/useAsync';
import { isQuizFailed } from '../materialQuizModel';
import {
  RANKING_STATE,
  RANKING_STATE_MESSAGE,
  classifyQuizListError,
  classifyRankingError,
  describeCorrect,
  medalOf,
  normalizeRanking,
  tiedRanks,
} from '../materialRankingModel';
import { newestQuizzesFirst } from '../quizModel';
import { quizLabel } from './QuizTab';

function RankingRow({ entry, isTied }) {
  const medal = medalOf(entry.rank);
  const correct = describeCorrect(entry);
  const meta = [correct, entry.attemptCount !== null ? `응시 ${entry.attemptCount}회` : null].filter(Boolean);

  return (
    <li className={entry.isMe ? 'mobile-ranking__row is-me' : 'mobile-ranking__row'} aria-current={entry.isMe || undefined}>
      <span className={medal ? `mobile-ranking__rank is-medal-${medal}` : 'mobile-ranking__rank'}>
        {entry.rank}
        {isTied && <small className="mobile-ranking__tie">공동</small>}
      </span>
      <span className="mobile-ranking__body">
        <span className="mobile-ranking__name">
          <span className="mobile-ranking__nickname" title={entry.nickname}>
            {entry.nickname}
          </span>
          {entry.isMe && <span className="mobile-ranking__me">나</span>}
        </span>
        {meta.length > 0 && <span className="mobile-ranking__meta">{meta.join(' · ')}</span>}
      </span>
      <span className="mobile-ranking__score">{entry.score}점</span>
    </li>
  );
}

function QuizRanking({ materialId, quizId }) {
  const ranking = useAsync(
    async () => normalizeRanking(await materialService.getQuizRanking(materialId, quizId), { materialId, quizId }),
    [materialId, quizId]
  );

  if (ranking.isLoading && !ranking.data) return <LoadingState label="랭킹을 불러오는 중입니다" />;

  if (ranking.isError) {
    const state = classifyRankingError(ranking.error);
    if (state === RANKING_STATE.ERROR) {
      return <ErrorState message={ranking.errorMessage} onRetry={ranking.reload} />;
    }
    return <EmptyState message={RANKING_STATE_MESSAGE[state]} />;
  }

  const { entries, me, meOutsideList, totalParticipants } = ranking.data;
  const tied = tiedRanks(entries);

  return (
    <section className="mobile-section">
      <div className="mobile-ranking__toolbar">
        <span className="mobile-ranking__count">참여 {totalParticipants}명</span>
        <button
          type="button"
          className="mobile-button mobile-button--ghost"
          onClick={() => ranking.reload().catch(() => {})}
          disabled={ranking.isLoading}
        >
          <RefreshCw size={16} />
          {ranking.isLoading ? '갱신 중' : '새로고침'}
        </button>
      </div>

      {entries.length === 0 ? (
        <EmptyState message="아직 이 퀴즈의 응시 기록이 없습니다. 퀴즈를 풀고 첫 순위에 올라보세요." />
      ) : (
        <ol className="mobile-ranking__list">
          {entries.map((entry, index) => (
            <RankingRow key={`${entry.rank}-${index}`} entry={entry} isTied={tied.has(entry.rank)} />
          ))}
        </ol>
      )}

      {meOutsideList && (
        <ol className="mobile-ranking__list mobile-ranking__list--me" aria-label="내 순위">
          <RankingRow entry={me} isTied={false} />
        </ol>
      )}
    </section>
  );
}

export default function RankingTab({ material }) {
  const materialId = material.materialId;
  const quizzes = useAsync(() => materialService.getQuizzes(materialId), [materialId]);
  const [selectedQuizId, setSelectedQuizId] = useState(null);

  const orderedQuizzes = useMemo(
    () => (isQuizFailed(quizzes.data) ? [] : newestQuizzesFirst(quizzes.data).filter((quiz) => !isQuizFailed(quiz))),
    [quizzes.data]
  );

  useEffect(() => {
    if (!orderedQuizzes.some((quiz) => quiz.quizId === selectedQuizId)) {
      setSelectedQuizId(orderedQuizzes[0]?.quizId ?? null);
    }
  }, [orderedQuizzes, selectedQuizId]);

  // 403(비공개 자료)·404(삭제된 자료) 는 재시도해도 같으므로 안내만 하고, 네트워크 오류만 ScreenState 의 재시도로 보낸다.
  const quizListBlocked = quizzes.isError ? classifyQuizListError(quizzes.error) : null;

  return (
    <>
      <h3 className="mobile-section__title mobile-ranking__title">{material.title}</h3>
      <p className="mobile-ranking__hint">
        퀴즈마다 난이도와 문항 수가 달라 랭킹은 퀴즈별로 따로 집계됩니다.
      </p>

      {quizListBlocked && quizListBlocked !== RANKING_STATE.ERROR ? (
        <EmptyState message={RANKING_STATE_MESSAGE[quizListBlocked]} />
      ) : (
        <ScreenState query={quizzes} loadingLabel="퀴즈 목록을 불러오는 중입니다">
          {orderedQuizzes.length === 0 ? (
            <EmptyState message="아직 생성된 퀴즈가 없어 랭킹이 없습니다. 퀴즈 탭에서 퀴즈를 만들어보세요." />
          ) : (
            <>
              {orderedQuizzes.length > 1 && (
                <select
                  className="mobile-select mobile-archive-fill mobile-section"
                  aria-label="랭킹을 볼 퀴즈 선택"
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
              {selectedQuizId !== null && (
                <QuizRanking key={`${materialId}-${selectedQuizId}`} materialId={materialId} quizId={selectedQuizId} />
              )}
            </>
          )}
        </ScreenState>
      )}
    </>
  );
}
