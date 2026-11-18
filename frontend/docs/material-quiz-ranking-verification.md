# 자료(PDF) 퀴즈 랭킹 — 구현 검증 기록 (Android)

> 목적: Termux 에서 작업한 `f1caa8bc`("WIP: preserve Android PDF quiz ranking")를 **처음부터 다시 만들지 않고**
> 보존·검증한 결과를 남긴다. 검증 결과 **구현 결함이 없어 소스 변경은 하지 않았다.** 이 문서는 검증·인계 기록이다.
> 계약/백엔드 분석 원문은 `material-quiz-ranking-contract.md` 를 본다.

## 1. 기준

| 항목 | 값 |
|---|---|
| 기준 커밋 | `f1caa8bc` (부모 `b7da1b4c`) |
| 검증 브랜치 | `feature/android-pdf-quiz-ranking-finalize` (origin/android-features 미접촉) |
| 기준 커밋의 변경 파일 | 8개 — 아래 §2 |
| 소스 변경 | **없음** (검증만 수행) |

## 2. 기존 구현 파일 (f1caa8bc)

| 파일 | 역할 |
|---|---|
| `src/mobile/screens/archive/materialRankingModel.js` (신규) | 순수 함수 모델: 탭 구성, 응답 정규화, 오류 분류, 경쟁 순위/동점/메달, 기능 플래그 |
| `src/mobile/screens/archive/tabs/RankingTab.jsx` (신규) | 랭킹 UI. 퀴즈 선택 → 퀴즈별 랭킹 조회·렌더 |
| `src/mobile/__tests__/materialRanking.test.mjs` (신규) | R1~R16(+R13b) 17개 단위 테스트 |
| `docs/material-quiz-ranking-contract.md` (신규) | 서버 계약 제안 + 백엔드 분석 |
| `src/mobile/screens/archive/DocumentMaterialTabs.jsx` (수정) | `documentTabs()` 적용, `ranking` 케이스 + `<RankingTab key={materialId}>` |
| `src/mobile/screens/archive/tabs/QuizTab.jsx` (수정) | `quizLabel` export 추가(랭킹 탭 재사용). 기존 로직 무변경 |
| `src/services/api.js` (수정) | `getQuizRanking(materialId, quizId, { limit })` 추가 |
| `src/mobile/mobile.css` (수정) | `.mobile-ranking__*` 스타일 추가 |

## 3. 검증 결과

| 검증 | 명령 | 결과 |
|---|---|---|
| 모바일 전체 단위 테스트 | `npm --prefix frontend run test:mobile` | **PASS** — 461 pass / 0 fail |
| 랭킹 전용 테스트 | `node --test src/mobile/__tests__/materialRanking.test.mjs` | **PASS** — 17/17 (R1~R16, R13b) |
| 모바일 ESLint | `npm --prefix frontend run lint:mobile` (`--max-warnings 0`) | **PASS** — 경고 0 |
| 모바일 프로덕션 빌드 | `npm run build:mobile` | **PASS** — `dist-mobile/` 생성 |
| Capacitor 동기화 | `npx cap sync android` | **PASS** — 웹 자산 복사 + 플러그인 7개 정상 |
| 회귀 (퀴즈 생성/응시/채점/오답/탭 이동) | R16 + 기존 테스트 | **PASS** |
| Gradle (`testDebugUnitTest`/`lintDebug`/`assembleDebug`) | — | **NOT TESTED** — 검증 환경에 JDK/Android SDK 미검증(도구 부재, 코드 오류 아님) |

### 결함 조사 (수정 0건)
- `RankingTab` 의 모든 import(`isQuizFailed`, `newestQuizzesFirst`, `quizLabel`, `useAsync`, `ScreenState`, `getQuizzes`) 존재·시그니처 일치.
- `onRetry={ranking.reload}` 는 공용 `ScreenState.jsx` 와 동일 컨벤션 → 단독 수정 시 오히려 불일치. 유지.
- `normalizeRanking`/`withCompetitionRanks`/`me` 병합을 R7·R8·R10 경로로 교차 검증 — 정상.
- 점수 클램프를 하지 않는 것은 "점수 권위는 서버" 원칙(앱이 점수를 계산·조작하지 않음)에 부합하는 의도된 동작.

## 4. 랭킹 격리 보장 (검증됨)
- **PDF별**: `<RankingTab key={materialId}>` 리마운트 + `normalizeRanking` 이 응답 `materialId` 불일치 시 거부.
- **퀴즈별**: `<QuizRanking key={materialId-selectedQuizId}>` 상태 초기화 + `quizId` 불일치 응답 거부.
- **동시성**: `useAsync` 의 requestId/mounted 가드로 지연·stale 응답 무시, 언마운트 안전.
- **식별자 보호**: 응답에서 `userId`/`email` 폐기, `isMe` 만 서버 JWT 기준, 공백 닉네임은 `익명`.

## 5. 서버 연동 상태 — BLOCKED
- `MaterialController.java` 에 `/ranking` 매핑 **없음**(list/create/submit/score/delete 만 존재) 확인.
- 계약 문서의 백엔드 분석(Redis HASH `studybridge:quiz:{quizId}:scores`, 재응시 덮어쓰기, TTL 180일/쓰기갱신, `deleteForQuiz` DEL)이 실제 `MaterialQuizScoreService` 와 **일치** 확인.
- 현재 `loadOwnedQuiz` 는 소유자 전용 → 퀴즈당 응시자 최대 1명. 다중 사용자 랭킹은 참여 범위(소유자/그룹/공개) **제품 결정 선결** 필요.
- EC2 구현 체크리스트: 계약 문서 §2~§6 참조(ZSET 랭킹 키, `GET .../ranking` 매핑, `loadAccessibleQuiz`, 비즈니스 404 `code` 포함, 삭제/탈퇴 정리, userId·email 응답 금지).

## 6. 배포 영향
- 랭킹 탭은 `VITE_FEATURE_MATERIAL_RANKING=true` 일 때만 노출. 현재 릴리스 빌드는 이 값을 설정하지 않아 **탭 숨김**.
- feature 브랜치 push 는 어떤 워크플로우도 트리거하지 않음(`android-release.yml`/`android-ci.yml` 은 `android-features` 대상). **APK 자동 릴리스 없음.**
- 서버 배포·통합 검증 후 `android-release.yml`/`android-ci.yml` 의 모바일 빌드 env 에 플래그를 추가해 켠다.

## 7. 최종 판정 (분리)
1. **Android 랭킹 UI·클라이언트 구현: 완료** — 테스트·ESLint·빌드·cap sync 통과, PDF/퀴즈별 격리, 서버 미구현 안전 처리, 회귀 없음.
2. **실제 서버 기반 다중 사용자 랭킹 서비스: BLOCKED** — 서버 `/ranking` API 및 참여 범위 정책 미정. 서버 구현 후 플래그만 켜면 연동.
