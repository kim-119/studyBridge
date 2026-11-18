import test from 'node:test';
import assert from 'node:assert/strict';
import {
  RANKING_STATE,
  RANKING_STATE_MESSAGE,
  RETRYABLE_RANKING_STATES,
  classifyRankingError,
  describeAccuracy,
  normalizeRanking,
  tiedRanks,
} from '../screens/archive/materialRankingModel.js';

// 서버(EC2 MaterialQuizScoreService)가 최고점·순위를 계산한다. 아래는 각 시나리오에서 서버가 돌려줄 응답 픽스처이며,
// 앱이 그 결과를 재집계·재정렬하지 않고 그대로 표시하는지 검증한다(서버 무결성 자체는 EC2 MaterialQuizRankingRedisIT 담당).
const httpError = (status, data = {}) => ({ response: { status, data } });
const ids = { materialId: 10, quizId: 100 };

function entry(rank, nickname, score, { correctCount, totalQuestions = 10, attemptCount = 1, isMe = false } = {}) {
  return { rank, nickname, score, correctCount: correctCount ?? score / 10, totalQuestions, attemptCount, isMe };
}

function view(entries, { me = null, ...rest } = {}) {
  return normalizeRanking({ ...ids, totalParticipants: entries.length, entries, me, ...rest }, ids);
}

test('P1 A 60→90→70 재응시: 서버 최고점 90 과 응시 3회를 그대로 표시한다', () => {
  const afterFirst = view([entry(1, 'A', 60, { isMe: true })]);
  assert.equal(afterFirst.me.score, 60);

  const afterSecond = view([entry(1, 'A', 90, { attemptCount: 2, isMe: true })]);
  assert.equal(afterSecond.me.score, 90);

  const afterThird = view([entry(1, 'A', 90, { attemptCount: 3, isMe: true })]);
  assert.equal(afterThird.me.score, 90, '낮은 재응시 점수(70)로 내려가지 않는다');
  assert.equal(afterThird.me.attemptCount, 3);
  assert.equal(afterThird.entries.length, 1, '사용자당 1건');
});

test('P2 B 95점은 A(90) 보다 위, 미응시 C 는 목록에 없다', () => {
  const ranking = view([entry(1, 'B', 95), entry(2, 'A', 90, { isMe: true })]);
  assert.deepEqual(
    ranking.entries.map((row) => [row.rank, row.nickname]),
    [
      [1, 'B'],
      [2, 'A'],
    ]
  );
  assert.equal(ranking.entries.some((row) => row.nickname === 'C'), false);
  assert.equal(ranking.totalParticipants, 2);
});

test('P3 미응시 본인은 me=null 이고 내 순위 행을 만들지 않는다', () => {
  const ranking = view([entry(1, 'B', 95)], { me: null });
  assert.equal(ranking.me, null);
  assert.equal(ranking.meOutsideList, false);
});

test('P4 동점은 서버 정책(같은 점수=같은 순위, 먼저 달성한 사람이 위)의 순서를 바꾸지 않는다', () => {
  // 서버는 늦게 달성한 "나중" 을 아래에 둔다. 앱이 닉네임·정답률·응시 횟수로 재정렬하면 안 된다.
  const ranking = view([
    entry(1, '먼저', 90, { attemptCount: 5 }),
    entry(1, '나중', 90, { attemptCount: 1 }),
    entry(3, '셋째', 80),
  ]);
  assert.deepEqual(
    ranking.entries.map((row) => [row.rank, row.nickname]),
    [
      [1, '먼저'],
      [1, '나중'],
      [3, '셋째'],
    ]
  );
  assert.deepEqual([...tiedRanks(ranking.entries)], [1]);
});

test('P5 PDF A 응답은 PDF B 화면에 쓰지 않는다', () => {
  assert.throws(() =>
    normalizeRanking({ materialId: 11, quizId: 100, entries: [entry(1, 'A', 90)] }, { materialId: 10, quizId: 100 })
  );
});

test('P6 정답률은 최고점 달성 시 정답 수/채점 문항 수로 표시만 한다', () => {
  assert.equal(describeAccuracy({ correctCount: 7, totalQuestions: 9 }), '정답률 78%');
  assert.equal(describeAccuracy({ correctCount: null, totalQuestions: 10 }), null);
  assert.equal(describeAccuracy({ correctCount: 0, totalQuestions: 0 }), null);
});

test('P7 응답 상태 분류: 200 외 400/401/403/404 QUIZ_NOT_FOUND/429/5xx 를 구분한다', () => {
  const cases = [
    [httpError(400, { code: 'INVALID_LIMIT' }), RANKING_STATE.BAD_REQUEST],
    [httpError(401), RANKING_STATE.UNAUTHORIZED],
    [httpError(403, { code: 'FORBIDDEN' }), RANKING_STATE.FORBIDDEN],
    [httpError(404, { code: 'QUIZ_NOT_FOUND' }), RANKING_STATE.QUIZ_NOT_FOUND],
    [httpError(404, { code: 'MATERIAL_NOT_FOUND' }), RANKING_STATE.NOT_FOUND],
    [httpError(429), RANKING_STATE.RATE_LIMITED],
    [httpError(500), RANKING_STATE.SERVER_ERROR],
    [httpError(503, { code: 'RANKING_UNAVAILABLE' }), RANKING_STATE.SERVER_ERROR],
    [{ status: 502 }, RANKING_STATE.SERVER_ERROR],
  ];
  for (const [error, expected] of cases) assert.equal(classifyRankingError(error), expected);

  for (const state of Object.values(RANKING_STATE)) {
    if (state === RANKING_STATE.ERROR) continue;
    assert.ok(RANKING_STATE_MESSAGE[state], `${state} 안내 문구`);
  }
  assert.deepEqual(
    [...RETRYABLE_RANKING_STATES].sort(),
    [RANKING_STATE.ERROR, RANKING_STATE.RATE_LIMITED, RANKING_STATE.SERVER_ERROR].sort()
  );
});

test('P8 퀴즈 없음(QUIZ_NOT_FOUND)과 응시자 없음(빈 entries)은 다른 상태다', () => {
  assert.equal(classifyRankingError(httpError(404, { code: 'QUIZ_NOT_FOUND' })), RANKING_STATE.QUIZ_NOT_FOUND);
  const empty = view([]);
  assert.deepEqual(empty.entries, []);
  assert.equal(empty.totalParticipants, 0);
});
