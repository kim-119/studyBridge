# 검증 보고서 (VERIFICATION_REPORT)

- 작성일: 2026-11-18
- 검증 환경: AWS EC2(Ubuntu 24.04, x86_64), OpenJDK 21.0.13, Node v20.20.2, npm 10.8.2, Python 3.12.3, Docker 29.1 / Compose v2.26
- 대상
  - 웹·백엔드·AI: `integration/llm-clean-to-main` (병합 커밋 `3d897e0b` + 후속 커밋)
  - Android: `integration/android-features-to-main` (병합 커밋 `2daff22b`)
- 표기: **PASS** = 직접 실행해 통과, **FAIL** = 직접 실행해 실패, **기존 실패** = 병합 전 브랜치에도 동일하게 존재, **미실행** = 실행하지 않음(사유 기재)

---

## 1. 요약

| 영역 | 항목 | 결과 |
|---|---|---|
| Frontend | `npm ci` | PASS |
| Frontend | `npm run build` (웹 프로덕션 빌드) | PASS |
| Frontend | `npm run lint` (전체) | **실행 불가 — 기존 문제**: 웹 영역 ESLint 설정 파일 없음(`origin/main`·`origin/LLM-clean` 동일). CI에서도 실행하지 않음 |
| Frontend | `npm run lint:mobile` | PASS |
| Frontend | 모바일 단위 테스트(`node --test src/mobile/__tests__/*.test.mjs`) | 병합 직후 435/438 → **원인 수정 후 438/438 PASS** (§3.1) |
| Frontend | `npm run build:mobile` + `mobile-bundle-guard.sh` | PASS |
| Backend | `./gradlew clean build` (컴파일 + 단위 테스트 + bootJar) | **PASS — 694 tests, 0 failures, 0 errors, 25 skipped** |
| AI | `python -m compileall fastapi` | PASS |
| AI | `pytest tests` (Mock 기반, 실서버 미접속) | 1506 passed / 27 failed / 4 collection errors — **기존 실패** (§3.2) |
| Infra | `docker compose -f docker-compose.yml -f docker-compose.override.yml config` | PASS (서비스: spring, openvidu, coturn, db, redis) |
| Android | 모바일 단위 테스트(통합 브랜치) | **550/550 PASS** |
| Android | GitHub Actions `StudyBridge Android CI` (동일 트리 `b0da9427`) | success (2026-11-02 실행 기록) |
| Android | 로컬 Gradle Debug 빌드 / `cap sync` | **미실행** (§3.3) |
| Android | PR #122 GitHub Actions `Mobile bundle and debug APK` (`cap sync`·Gradle `testDebugUnitTest`·`lintDebug`·`assembleDebug`·화면공유 APK 검증, 헤드 `2daff22b`) | **PASS** |
| CI | PR #121 `ci.yml` 전체(백엔드 빌드·테스트, 프론트, FastAPI, Docker 이미지 빌드, 헤드 `9b82f7c5`) | **PASS** (1차 실행은 Maven Central `429 Too Many Requests`로 백엔드 잡 실패 → 실패 잡 재실행 후 통과) |
| Android | 실기기 설치·동작 | **미실행** — 검증 환경에 Android 기기 없음 |
| Android | 서명 Release 빌드 | **미실행** — keystore는 GitHub Secrets에만 존재 |
| 보안 | 통합 트리 비밀값 정규식 스캔 | 신규 노출 없음, 기존 예시 파일 1건 교체 (§4) |
| AI 실서버 | ai07 실서버 계약 검증 | **미실행** — 운영 서버 대상 시험은 승인 범위 밖 |

## 2. 병합 무결성 검증

| 검사 | 방법 | 결과 |
|---|---|---|
| 미해결 충돌 | `git diff --check`, 충돌 마커 검색 | 없음 |
| AI·운영 코드 보존 | `git diff origin/LLM-clean HEAD -- fastapi ops scripts docs/ai-contracts STUDYBRIDGE_AI.md` | 차이 0 (예시 env 키 교체 제외) |
| LLM-clean 대비 누락 파일 | `git diff --name-status origin/LLM-clean` 의 `D` 32건 | 전부 의도적 제외(빌드 산출물 15, 백업 11, `.vite` 2, psql 잔재 1, 참조 0건 소스 3) |
| main 대비 삭제 파일 | `git diff --name-status origin/main` 의 `D` 2건 | `LearningMate.jsx`, `NextLearningCard.jsx` — LLM-clean에서 의도적으로 삭제된 화면(라우트는 `/studymate` 리다이렉트), 빌드 통과 |
| Android 병합 | `git diff origin/android-features HEAD` | 차이 0 (android-main 고유 변경은 내용 없는 PR 병합 커밋 1개) |

## 3. 실패 및 미실행 상세

### 3.1 모바일 테스트 3건 실패 → 수정 (병합으로 드러난 문제)
- 실패: `groupRuntime.test.mjs` T6, T7, T7-1 (그룹 자료 업로드)
- 원인: LLM-clean이 `groupService.uploadQuizMaterial`을 전역 `axios.post`에서 공통 `api` 인스턴스(401 자동 갱신 포함)로 변경. main의 모바일 테스트는 전역 `axios.post`만 모킹.
- 판단: 기능 회귀가 아니라 테스트가 구현 세부에 결합된 문제. LLM-clean 구현이 운영 중인 코드이며 토큰 갱신 측면에서 더 안전함.
- 조치: 테스트 모킹을 두 구현 모두 같은 기준(절대 URL, FormData, Authorization, 서버 오류 메시지)으로 검증하도록 보강(`e94cd1bc`).
- 확인: 통합 브랜치 438/438, `origin/main` 원본 구현에서도 수정 테스트 10/10 통과.

### 3.2 FastAPI pytest 기존 실패
`fastapi/` 디렉터리는 `origin/LLM-clean`과 내용이 동일하므로 아래 결과는 병합과 무관한 기존 상태입니다.

| 파일 | 건수 | 성격 |
|---|---|---|
| `test_major_analysis_{enrichment,image_pages,pages,pdf_ocr}.py` | 수집 오류 4 | 테스트가 참조하는 `_attach_page_schema` 등이 현재 코드에 없음(테스트가 코드보다 앞섬) |
| `test_ai07_production_handoff_v2.py` | 18 | ai07 운영 인계용 계약 테스트 — EC2 코드와 기대값 불일치 |
| `test_realtime_quiz_answer_consistency.py` | 3 | |
| `test_redis_retry.py`, `test_mode_contract_streams.py`, `test_mindmap_semantic_graph.py` | 각 2 | 일부는 로컬 Ollama(`localhost:11434`) 접속 시도 |

후속 조치: AI 담당자가 테스트-코드 불일치를 정리해야 합니다(이번 통합 범위 밖).

### 3.3 Android 로컬 Gradle 빌드 미실행 사유
- 검증 서버 루트 디스크 사용률 95%(여유 약 4.4GB). Android Gradle 8.14 배포본 + AGP + libwebrtc 의존성 다운로드(수 GB)는 운영 서비스(같은 디스크)의 502 장애 위험이 있음.
- Capacitor CLI 8은 Node 22가 필요하나 검증 환경은 Node 20.
- 대체 근거: 통합 브랜치 트리가 `origin/android-features`(`b0da9427`)와 동일하며, 해당 SHA의 GitHub Actions `StudyBridge Android CI`(Gradle `testDebugUnitTest`·`lintDebug`·`assembleDebug`, 화면공유 APK 검증 포함)가 성공했습니다. `android-main` 대상 PR에서도 같은 워크플로가 다시 실행됩니다.

## 4. 보안 검증

| 항목 | 결과 |
|---|---|
| 통합 트리 정규식 스캔(AWS 키, 개인키 헤더, `sk-`, `tvly-`, GitHub 토큰 등) | 테스트 픽스처의 가짜 값만 검출. 실제 비밀값 없음 |
| 추적되는 `.env`/키스토어/`.pem`/`key.properties` | 없음 |
| 예시 env 파일 | `fastapi/.env.example`, `fastapi/.env copy.example`의 `AI_SERVER_API_KEY`가 과거 커밋에 노출된 값과 동일 → 플레이스홀더로 교체(`3be12073`). 현재 운영 값과는 다름(지문 비교) |
| **Git 이력 내 비밀값** | **심각** — 상세는 [BRANCH_MERGE_REPORT.md §7](BRANCH_MERGE_REPORT.md#7-보안-검사-결과) |

비밀값 비교는 값 대신 SHA-256 지문 앞 12자리로만 수행했으며 어떤 값도 출력·기록하지 않았습니다.

## 5. 재현 명령

```bash
# Frontend
cd frontend && npm ci && npm run build && npm run lint:mobile
node --test src/mobile/__tests__/*.test.mjs        # 루트에서 npm ci 선행(Capacitor 패키지)
MOBILE_API_BASE_URL=https://studybridge.co.kr VITE_API_BASE_URL=https://studybridge.co.kr npm run build:mobile
cd .. && MOBILE_API_BASE_URL=https://studybridge.co.kr bash .github/scripts/mobile-bundle-guard.sh

# Backend
cd backend && ./gradlew clean build

# AI
python -m compileall fastapi
cd fastapi && python -m pytest -q --continue-on-collection-errors tests

# Infra
docker compose -f docker-compose.yml -f docker-compose.override.yml config -q
```
