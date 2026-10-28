import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  MATERIAL_RANKING_ENABLED,
  RANKING_STATE,
  classifyQuizListError,
  classifyRankingError,
  describeCorrect,
  documentTabs,
  medalOf,
  normalizeRanking,
  tiedRanks,
} from '../screens/archive/materialRankingModel.js';

// 아래 응답은 전부 테스트 픽스처다(운영 번들에 포함되지 않음). 실제 백엔드 통합 검증이 아니다.
const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');
const TABS_SOURCE = read('../screens/archive/DocumentMaterialTabs.jsx');
const RANKING_TAB_SOURCE = read('../screens/archive/tabs/RankingTab.jsx');
const QUIZ_TAB_SOURCE = read('../screens/archive/tabs/QuizTab.jsx');
const API_SOURCE = read('../../services/api.js');
const MODEL_SOURCE = read('../screens/archive/materialRankingModel.js');

function fixture({ materialId = 10, quizId = 100, entries, me = null, totalParticipants } = {}) {
  return {
    materialId,
    quizId,
    totalParticipants,
    entries: entries ?? [
      { rank: 1, nickname: '하늘', score: 100, correctCount: 10, totalQuestions: 10, attemptCount: 2, isMe: false },
      { rank: 2, nickname: '바다', score: 90, correctCount: 9, totalQuestions: 10, attemptCount: 1, isMe: true },
      { rank: 3, nickname: '산', score: 80, correctCount: 8, totalQuestions: 10, attemptCount: 3, isMe: false },
    ],
    me,
  };
}

const httpError = (status, data = {}) => ({ response: { status, data } });

test('R1 랭킹 탭은 퀴즈 바로 오른쪽에 있고 6개 탭이 된다', () => {
  const keys = documentTabs({ rankingEnabled: true }).map((tab) => tab.key);
  assert.deepEqual(keys, ['summary', 'quiz', 'ranking', 'roadmap', 'memo', 'question']);
  assert.equal(documentTabs({ rankingEnabled: true })[2].label, '랭킹');
});

test('R2 서버 API 배포 전(플래그 꺼짐)에는 기존 5개 탭만 노출한다', () => {
  assert.equal(MATERIAL_RANKING_ENABLED, false);
  assert.deepEqual(
    documentTabs({ rankingEnabled: false }).map((tab) => tab.key),
    ['summary', 'quiz', 'roadmap', 'memo', 'question']
  );
  assert.match(MODEL_SOURCE, /import\.meta\.env\.VITE_FEATURE_MATERIAL_RANKING === 'true'/);
});

test('R3 PDF A 의 응답을 PDF B 랭킹으로 쓰지 않는다(materialId 격리)', () => {
  assert.equal(normalizeRanking(fixture({ materialId: 10 }), { materialId: 10, quizId: 100 }).entries.length, 3);
  assert.throws(() => normalizeRanking(fixture({ materialId: 10 }), { materialId: 11, quizId: 100 }));
});

test('R4 같은 PDF 의 다른 퀴즈 점수는 섞이지 않는다(quizId 분리)', () => {
  assert.throws(() => normalizeRanking(fixture({ quizId: 100 }), { materialId: 10, quizId: 101 }));
  assert.match(API_SOURCE, /\/api\/materials\/\$\{materialId\}\/quiz\/\$\{quizId\}\/ranking/);
});

test('R5 PDF·퀴즈가 바뀌면 랭킹 상태를 새로 만든다(이전 PDF 데이터 잔상 없음)', () => {
  assert.match(TABS_SOURCE, /<RankingTab key=\{materialId\}/);
  assert.match(RANKING_TAB_SOURCE, /<QuizRanking key=\{`\$\{materialId\}-\$\{selectedQuizId\}`\}/);
});

test('R6 1·2·3등은 메달, 4등부터는 일반 표시', () => {
  assert.deepEqual([1, 2, 3, 4, 10].map(medalOf), [1, 2, 3, null, null]);
});

test('R7 서버 rank 를 그대로 쓰고 동점은 같은 순위로 표시한다', () => {
  const ranking = normalizeRanking(
    fixture({
      entries: [
        { rank: 3, nickname: 'C', score: 80 },
        { rank: 1, nickname: 'A', score: 90 },
        { rank: 1, nickname: 'B', score: 90 },
      ],
    }),
    { materialId: 10, quizId: 100 }
  );
  assert.deepEqual(ranking.entries.map((entry) => [entry.rank, entry.nickname]), [[1, 'A'], [1, 'B'], [3, 'C']]);
  assert.deepEqual([...tiedRanks(ranking.entries)], [1]);
});

test('R8 rank 가 빠진 응답은 점수 기준 경쟁 순위(1,1,3)로 보완한다', () => {
  const ranking = normalizeRanking(
    fixture({ entries: [{ score: 70 }, { score: 90 }, { score: 90 }, { score: 50 }] }),
    { materialId: 10, quizId: 100 }
  );
  assert.deepEqual(ranking.entries.map((entry) => [entry.rank, entry.score]), [[1, 90], [1, 90], [3, 70], [4, 50]]);
});

test('R9 재응시는 서버가 집계한 응시 횟수·점수를 그대로 표시한다(앱은 점수를 계산하지 않음)', () => {
  const ranking = normalizeRanking(fixture(), { materialId: 10, quizId: 100 });
  assert.equal(ranking.entries[0].attemptCount, 2);
  assert.equal(describeCorrect(ranking.entries[0]), '10/10 정답');
  assert.doesNotMatch(MODEL_SOURCE, /submitQuiz|computeScore/);
  assert.doesNotMatch(RANKING_TAB_SOURCE, /submitQuiz/);
});

test('R10 로그인 사용자 행을 강조하고, 목록 밖이면 별도로 보여준다', () => {
  const inList = normalizeRanking(fixture(), { materialId: 10, quizId: 100 });
  assert.equal(inList.me.nickname, '바다');
  assert.equal(inList.meOutsideList, false);

  const outside = normalizeRanking(
    fixture({
      entries: [{ rank: 1, nickname: 'A', score: 100 }],
      me: { rank: 57, nickname: '나', score: 30 },
      totalParticipants: 80,
    }),
    { materialId: 10, quizId: 100 }
  );
  assert.equal(outside.me.rank, 57);
  assert.equal(outside.me.isMe, true);
  assert.equal(outside.meOutsideList, true);
  assert.equal(outside.totalParticipants, 80);
  assert.match(RANKING_TAB_SOURCE, /is-me/);
});

test('R11 사용자 식별자는 버리고 닉네임만 남긴다, 빈 닉네임은 익명', () => {
  const ranking = normalizeRanking(
    fixture({ entries: [{ rank: 1, nickname: '  ', score: 10, userId: 7, email: 'x@y.z' }] }),
    { materialId: 10, quizId: 100 }
  );
  assert.equal(ranking.entries[0].nickname, '익명');
  assert.equal('userId' in ranking.entries[0], false);
  assert.equal('email' in ranking.entries[0], false);
});

test('R12 응시 기록이 없으면 빈 랭킹', () => {
  const ranking = normalizeRanking(fixture({ entries: [] }), { materialId: 10, quizId: 100 });
  assert.equal(ranking.entries.length, 0);
  assert.equal(ranking.me, null);
  assert.equal(ranking.totalParticipants, 0);
});

test('R13 오류 분류: 미배포·삭제·권한 없음·네트워크', () => {
  // Spring 미매핑 라우트 404(code 없음) → 미배포
  assert.equal(classifyRankingError(httpError(404, { error: 'Not Found', path: '/x' })), RANKING_STATE.UNAVAILABLE);
  assert.equal(classifyRankingError(httpError(405)), RANKING_STATE.UNAVAILABLE);
  assert.equal(classifyRankingError(httpError(501)), RANKING_STATE.UNAVAILABLE);
  // 존재하지 않거나 삭제된 PDF·퀴즈
  assert.equal(classifyRankingError(httpError(404, { code: 'MATERIAL_NOT_FOUND' })), RANKING_STATE.NOT_FOUND);
  assert.equal(classifyRankingError(httpError(404, { code: 'QUIZ_NOT_FOUND' })), RANKING_STATE.NOT_FOUND);
  // 다른 사용자의 비공개 자료
  assert.equal(classifyRankingError(httpError(403)), RANKING_STATE.FORBIDDEN);
  // 네트워크 오류·서버 오류는 재시도 가능
  assert.equal(classifyRankingError({ message: 'Network Error' }), RANKING_STATE.ERROR);
  assert.equal(classifyRankingError(httpError(500)), RANKING_STATE.ERROR);
});

test('R13b 존재하지 않는·삭제된 PDF 의 퀴즈 목록 404 는 미배포가 아니라 자료 없음', () => {
  assert.equal(classifyQuizListError(httpError(404, { status: 404, message: '자료를 찾을 수 없습니다.' })), RANKING_STATE.NOT_FOUND);
  assert.equal(classifyQuizListError(httpError(403)), RANKING_STATE.FORBIDDEN);
  assert.equal(classifyQuizListError({ message: 'Network Error' }), RANKING_STATE.ERROR);
  assert.match(RANKING_TAB_SOURCE, /classifyQuizListError\(quizzes\.error\)/);
});

test('R14 잘못된 응답 형식은 예외로 처리한다(화면은 ErrorState)', () => {
  assert.throws(() => normalizeRanking(null, { materialId: 10, quizId: 100 }));
  assert.throws(() => normalizeRanking('<html>', { materialId: 10, quizId: 100 }));
});

test('R15 랭킹 화면: PDF 제목·새로고침·재시도·빈 상태·긴 닉네임 말줄임', () => {
  assert.match(RANKING_TAB_SOURCE, /material\.title/);
  assert.match(RANKING_TAB_SOURCE, /ranking\.reload/);
  assert.match(RANKING_TAB_SOURCE, /onRetry=\{ranking\.reload\}/);
  assert.match(RANKING_TAB_SOURCE, /아직 이 퀴즈의 응시 기록이 없습니다/);
  const css = read('../mobile.css');
  assert.match(css, /\.mobile-ranking__nickname \{[^}]*text-overflow: ellipsis/);
  assert.match(css, /\.mobile-subtabs \{[^}]*overflow-x: auto/);
});

test('R16 기존 퀴즈 탭 응시·채점·오답노트 흐름 회귀 없음', () => {
  assert.match(QUIZ_TAB_SOURCE, /materialService\.submitQuiz|submitQuiz\(/);
  assert.match(QUIZ_TAB_SOURCE, /reviewNoteService\.createFromQuiz/);
  assert.match(QUIZ_TAB_SOURCE, /export default function QuizTab/);
  assert.match(TABS_SOURCE, /case 'quiz':\s*return <QuizTab material=\{material\} \/>/);
});
