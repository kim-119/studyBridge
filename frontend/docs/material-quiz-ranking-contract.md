# 자료(PDF) 퀴즈 랭킹 — 서버 계약 제안 (Android 클라이언트 기준)

> 상태: **제안(PROPOSED) / 서버 미구현 → Android 랭킹 탭은 BLOCKED, 기능 플래그로 숨김**
> 작성 기준: `android-features` (b7da1b4c). `MaterialQuizService` / `MaterialQuizScoreService` / `QuizDTO` 는
> `origin/LLM-clean` 과 동일함을 확인함. 이 문서는 EC2 담당자가 최종 계약을 정하기 위한 초안이며, 최종 구현이
> 다르면 Android 는 `services/api.js#getQuizRanking` 과 `materialRankingModel.normalizeRanking` 만 맞추면 된다.

## 1. 현재 구조 분석 (변경 없음, 읽기만 함)

| 항목 | 현재 동작 | 랭킹에 미치는 영향 |
|---|---|---|
| 채점 API | `POST /api/materials/{materialId}/quiz/{quizId}/submit` — 서버가 DB 정답 키로 채점 | 점수의 신뢰 근거. 앱은 점수를 계산·제출하지 않는다 |
| 권한 | `loadOwnedQuiz`: 퀴즈 존재(404) → materialId 소속(404) → **자료 소유자만(403)** | **다른 사용자는 응시 자체가 불가** → 퀴즈당 점수는 최대 1명(소유자) |
| 저장소 | Redis HASH `studybridge:quiz:{quizId}:scores`, field=userId, value=StoredScore JSON | 퀴즈 단위 키 → 퀴즈별 랭킹 식별자로 그대로 쓸 수 있음 |
| 재응시 | 같은 (quizId,userId) 는 **최신 제출이 덮어씀**, attempt 만 +1 | 최고점 기록이 남지 않음 → 최고점 랭킹 불가 |
| TTL | 키 전체 180일(`ai.quiz.score-ttl-days`), 쓰기마다 갱신 | 마지막 제출 후 180일 지나면 랭킹 전체 소멸 |
| 삭제 | 퀴즈 삭제 시 `deleteForQuiz` DEL 1회, 자료 삭제 시 `deleteForQuizzes` | 랭킹 키도 같은 시점에 지워야 함 |
| 자료 공개 범위 | `Material` 엔티티에 공개/공유 필드 없음(소유자 전용) | 다중 사용자 참여 범위를 정의할 근거가 아직 없음 |

**결론: 현재 백엔드만으로는 다중 사용자 랭킹을 구성할 수 없다.** 랭킹 조회 API 와 함께
"누가 남의 PDF 퀴즈에 응시할 수 있는가" 라는 제품 정책 결정이 먼저 필요하다(아래 §2). Android 는 이 결정에 의존하지 않도록
서버가 돌려주는 랭킹을 그대로 표시만 한다.

## 2. 참여 범위 (서버/제품 결정 필요 — BLOCKED)

다음 중 하나를 서버가 결정해야 한다. 결정 전에는 응답 entries 가 소유자 1명뿐이어도 계약상 정상이다.

- (A) **소유자 전용 유지**: 랭킹 = 내 응시 기록만. 다중 사용자 기능 아님.
- (B) **그룹 공유 자료**: 자료를 스터디 그룹 리소스로 공유하면 그 그룹 멤버가 응시·랭킹 조회 가능.
  `loadOwnedQuiz` 를 `loadAccessibleQuiz(userId, materialId, quizId)` 로 분리(소유자 또는 공유 그룹 멤버).
- (C) **공개 자료**: `Material.visibility = PRIVATE | GROUP | PUBLIC` 신설.

어느 경우든 **비공개 자료는 소유자 외에 404 가 아니라 403** 을 돌려 기존 정책(존재 유추 방지 순서)을 유지하되,
랭킹 응답 본문에는 다른 사용자의 userId·email 을 절대 넣지 않는다.

## 3. 랭킹 식별자와 집계 기준

- 랭킹 단위는 **퀴즈(quizId)** 이다. PDF(materialId) 는 퀴즈의 상위 경로이며, 서버는 `quiz.material.materialId == materialId` 를 검증한다.
- 같은 PDF 라도 퀴즈마다 난이도·문항 수가 달라 **퀴즈 간 점수를 합산·비교하지 않는다.**
- 사용자별 대표 점수: **최고 점수(best)**. 동점이면 그 점수에 **먼저 도달한 시각**이 빠른 사람이 목록상 위(같은 rank 유지).
- 순위 방식: 경쟁 순위(standard competition, 1·1·3). `rank` 는 서버가 계산해 내려준다.
- 점수 = 기존 `computeScore(correct, gradableTotal)` 그대로(0–100). 같은 퀴즈 안에서는 분모가 같으므로 비교 가능.

### 재응시 정책
- 재응시마다 `attemptCount` +1.
- 새 점수 > 기존 best 일 때만 best·bestAt 갱신 → 순위 갱신. 같거나 낮으면 순위 불변(최신 결과 화면은 기존 `/score` 그대로).

### PDF 전체 통합 랭킹 (선택, 이번 범위 아님)
필요 시 별도 엔드포인트로 정의한다. 공정한 기준 후보: 사용자가 응시한 퀴즈들의 best 점수 **평균**을 쓰되
`minQuizzes`(예: PDF 퀴즈 수의 50%) 이상 응시한 사용자만 포함, 응답에 `aggregation: "MEAN_BEST_OVER_ATTEMPTED"` 를 명시.
Android v1 은 통합 랭킹을 표시하지 않는다.

## 4. 필요한 백엔드 변경 (제안)

1. `MaterialQuizScoreService`
   - `StoredScore` 에 `bestScore`, `bestCorrectCount`, `bestAt` 추가(기존 필드 유지 → 하위 호환, `@JsonIgnoreProperties` 이미 있음).
   - ZSET `studybridge:quiz:{quizId}:ranking` 추가. member=userId,
     score = `bestScore * 1e10 + (MAX_EPOCH_SEC - bestAtEpochSec)` (높은 점수 우선, 동점은 먼저 달성한 쪽 우선).
     rank 계산은 같은 bestScore 개수로 경쟁 순위를 산출(`ZCOUNT` 로 상위 점수 수 + 1).
   - `save` 에서 best 갱신 시에만 `ZADD`. HASH 와 ZSET 에 같은 TTL 적용.
   - `deleteForQuiz` 에서 HASH 와 ZSET 을 함께 DEL.
2. `MaterialQuizService`
   - `ranking(userId, materialId, quizId, limit)` 추가. 접근 검증은 §2 결정에 따른 `loadAccessibleQuiz`.
   - 닉네임은 `User.displayName` 을 배치 조회(N+1 금지). 탈퇴 사용자는 `"탈퇴한 사용자"` 로 표시하거나 제외.
3. `MaterialController` — `GET /{materialId}/quiz/{quizId}/ranking` 매핑.
4. 오류 본문에 `code` 추가(§5.3). 기존 `GlobalExceptionHandler.body()` 는 `{status, message}` 만 내므로
   랭킹 전용 예외(또는 code 를 담는 예외 타입)가 필요하다.
5. Redis 장애 시 500 대신 `503 {code: "RANKING_UNAVAILABLE"}` 권장(채점 API 는 기존처럼 막지 않음).

## 5. API 계약 (제안)

### 5.1 요청
```
GET /api/materials/{materialId}/quiz/{quizId}/ranking?limit=50
Authorization: Bearer <JWT>
```
- `limit`: 1–100, 기본 50.

### 5.2 200 응답
```json
{
  "materialId": 10,
  "quizId": 100,
  "rankingPolicy": "BEST_SCORE",
  "totalQuestions": 10,
  "totalParticipants": 3,
  "generatedAt": "2026-10-28T12:00:00",
  "entries": [
    { "rank": 1, "nickname": "하늘", "score": 100, "correctCount": 10, "totalQuestions": 10, "attemptCount": 2, "achievedAt": "2026-10-27T09:00:00", "isMe": false },
    { "rank": 1, "nickname": "바다", "score": 100, "correctCount": 10, "totalQuestions": 10, "attemptCount": 1, "achievedAt": "2026-10-27T10:00:00", "isMe": true },
    { "rank": 3, "nickname": "산",   "score": 80,  "correctCount": 8,  "totalQuestions": 10, "attemptCount": 3, "achievedAt": "2026-10-26T08:00:00", "isMe": false }
  ],
  "me": { "rank": 1, "nickname": "바다", "score": 100, "correctCount": 10, "totalQuestions": 10, "attemptCount": 1, "isMe": true }
}
```
- `materialId`/`quizId` 는 **필수**. Android 는 요청 값과 다르면 응답을 버린다(PDF·퀴즈 간 혼합 방지).
- `entries` 에 **userId·email·프로필 이미지 URL 등 식별자 금지**. `isMe` 는 서버가 JWT 로 계산.
- `me` 는 요청자가 응시했으면 항상 포함(상위 `limit` 밖이어도), 미응시면 `null`.
- 응시자가 없으면 `entries: []`, `totalParticipants: 0` (404 아님).

### 5.3 오류
| 상황 | 상태 | 본문 `code` | Android 표시 |
|---|---|---|---|
| 자료 없음/삭제됨 | 404 | `MATERIAL_NOT_FOUND` | "자료 또는 퀴즈를 찾을 수 없습니다" |
| 퀴즈 없음/삭제됨/다른 자료 소속 | 404 | `QUIZ_NOT_FOUND` | 동일 |
| 비공개 자료·권한 없음 | 403 | `FORBIDDEN` | "랭킹을 볼 권한이 없습니다" |
| 미로그인 | 401 | — | 기존 토큰 갱신 흐름 |
| Redis 장애 | 503 | `RANKING_UNAVAILABLE` | 오류 + 재시도 |

**중요**: 랭킹 API 의 비즈니스 404 는 반드시 `code` 를 담는다. Android 는 `code` 없는 404(=라우트 미배포)와
405/501 을 "서버 준비 중" 으로 처리하고 앱을 멈추지 않는다.

## 6. 삭제·만료 정책
- 퀴즈 삭제: HASH + ZSET 동시 DEL(기존 `deleteForQuiz` 확장).
- 자료 삭제: 소속 퀴즈 전부에 대해 위와 동일(기존 `deleteForQuizzes` 경로).
- 탈퇴 사용자: HASH field 와 ZSET member 를 제거하는 정리 작업 권장(없으면 닉네임 조회 실패 시 목록에서 제외).
- TTL: 기존 180일·쓰기 시 갱신 유지. 만료되면 랭킹이 빈 상태로 보이는 것이 정상이며, 장기 보존이 필요하면 DB 테이블
  (`material_quiz_best_score(quiz_id, user_id, best_score, best_at, attempt_count)`)로 승격을 권장.

## 7. Android 측 구현 현황
- 탭: `요약 / 퀴즈 / 랭킹 / 로드맵 / 메모 / AI 질문` (`materialRankingModel.documentTabs`).
- 기능 플래그: `VITE_FEATURE_MATERIAL_RANKING=true` 일 때만 탭 노출. **현재 릴리스 빌드는 이 값을 설정하지 않으므로 탭이 숨겨진다.**
  서버 배포·통합 검증 후 `android-release.yml`/`android-ci.yml` 의 모바일 빌드 env 에 추가해 켠다.
- 클라이언트: `materialService.getQuizRanking(materialId, quizId, { limit })`.
- 테스트: `frontend/src/mobile/__tests__/materialRanking.test.mjs` — **픽스처 기반 단위 테스트이며 실제 백엔드 통합 검증이 아니다.**
