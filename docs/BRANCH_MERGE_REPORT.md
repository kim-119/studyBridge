# 브랜치 통합 보고서 (BRANCH_MERGE_REPORT)

- 작성일: 2026-11-18
- 상태: **통합 브랜치·Draft PR 준비 완료 / 실제 병합은 최종 승인 대기**

| 통합 | SOURCE → TARGET | 통합 브랜치 | PR |
|---|---|---|---|
| 웹·백엔드·AI | `LLM-clean` → `main` | `integration/llm-clean-to-main` | [#121](https://github.com/kim-119/studyBridge/pull/121) (Draft) |
| Android | `android-features` → `android-main` | `integration/android-features-to-main` | [#122](https://github.com/kim-119/studyBridge/pull/122) (Draft) |

---

## 1. 병합 전 상태 (백업)

| 브랜치 | 병합 전 HEAD | 백업 태그(원격 push 완료) |
|---|---|---|
| `main` | `d5624760cc6ec4f7b8e155b8bda532e66ca713bc` | `backup/pre-integration-20261118/main` |
| `LLM-clean` | `4db383728eac9b7f6e87de5a99466d1bc9e2ce06` | `backup/pre-integration-20261118/LLM-clean` |
| `android-main` | `413d3cf53fb3f9a734cd7633bf287ef3ac6b8554` | `backup/pre-integration-20261118/android-main` |
| `android-features` | `b0da94272e9683033342c6a037ed87b93ac20af0` | `backup/pre-integration-20261118/android-features` |

| 비교 | merge-base | 앞섬/뒤처짐 |
|---|---|---|
| `main...LLM-clean` | `990d2cfe` | main 고유 52 / LLM-clean 고유 77 |
| `android-main...android-features` | `f3281bea` | android-main 고유 1 / android-features 고유 42 |

- 브랜치 보호 규칙: 네 브랜치 모두 없음(GitHub API 404 "Branch not protected").
- 저장소: **public**, 기본 브랜치 `main`.
- 기존 열린 PR: #107(LLM-clean→main), #116·#117(learning-loop, 머지 금지 표기), #119·#120(STOMP JWT, Draft).
- 참고: EC2 로컬 `android-features`에는 원격에 없는 커밋 `46af8db4`가 있으나, 같은 내용이 원격 `f6baa8f6`으로 반영되어 있어 통합은 **원격 기준**으로 수행했습니다. 로컬 브랜치는 변경하지 않았습니다.

## 2. 웹·백엔드·AI 통합 (`LLM-clean` → `main`)

### 2.1 결과 커밋
| 커밋 | 내용 |
|---|---|
| `3d897e0b` | `merge: integrate LLM-clean into main` (3-way, `--no-ff`) |
| `e94cd1bc` | 모바일 그룹 업로드 테스트를 두 구현 모두 검증하도록 보강 |
| `3be12073` | `fastapi` 예시 env의 `AI_SERVER_API_KEY` 실값 → 플레이스홀더 |
| `4beedaca` 이후 | README·docs·`.env.example` |

### 2.2 핵심 발견: main의 대량 삭제
`main`은 PR #104/#105로 `android-features`를 병합하면서 Android 브랜치 범위 정리 커밋을 함께 받았습니다.

- `567328b4` "Stop tracking docs/, fastapi/, ops/ and scripts/ on the Android branch. **They remain on LLM-clean**"
- `d4be461d` "untrack agent tooling, AI server docs, backups, build output and a stray psql dump; drop five source files reached by no entry or test"

그 결과 merge-base 이후 main 쪽 삭제가 **628개**(fastapi 397+109+…, ops 30, scripts 3 등)였고, 기본 3-way merge를 그대로 쓰면 LLM-clean에서 수정되지 않은 운영 AI 서버 코드 600여 파일이 **조용히 삭제**됩니다(충돌로 표시되는 것은 LLM-clean이 수정한 20개뿐).

### 2.3 충돌 및 해결 근거

| 파일 | 유형 | 해결 | 근거 |
|---|---|---|---|
| `fastapi/**` 18개, `ops/studybridge-ai-healthcheck.sh`, `ops/systemd/studybridge-redis-tunnel.service` | modify/delete | **LLM-clean 수정본 유지** | main 측 삭제는 Android 범위 정리 목적이며 커밋 메시지가 LLM-clean 유지를 명시. 운영 AI 서버 코드 |
| `fastapi/` `ops/` `scripts/` `docs/` `STUDYBRIDGE_AI.md` (충돌 표시 없이 삭제될 파일) | 암묵적 삭제 | **LLM-clean 버전으로 복원** | 위와 동일. 복원 후 LLM-clean 대비 diff 0 |
| `.gitignore` | main 단독 변경 | main 버전 + Android 전용 규칙 4줄(`/docs/ /fastapi/ /ops/ /scripts/`) 제거 | full-stack `main`에서 해당 디렉터리를 무시하면 신규 파일이 추적되지 않음. 비밀값·빌드 산출물·서명 키 무시 규칙은 유지 |
| `frontend/src/services/api.js` | content | **양쪽 통합** | main: `leaveGroup` `searchGroups` `getChatHistory`(Android 그룹 기능), LLM-clean: 초대 링크·퀴즈 랭킹·닉네임. 서로 다른 메서드이며 백엔드 엔드포인트(`/{id}/leave`, `/search`, `/{groupId}/chats/history`) 존재 확인 |
| `frontend/src/utils/groupStudy.js` | add/add | 자동 병합(양쪽 동일 내용) | |
| `CLAUDE.md`, `.claude/agents/*` | delete/delete | 삭제 유지 | 양쪽 모두 추적 제외 결정(`81c70790`: 로컬 전용 규칙) |

### 2.4 의도적으로 복원하지 않은 파일(main 삭제 유지, 32개)
| 분류 | 파일 | 사유 |
|---|---|---|
| 빌드 산출물 | `frontend/dist/**`(15), `frontend/.vite/**`(2) | 빌드 결과물은 추적 대상 아님. 운영 프론트는 CD가 매번 빌드 |
| 백업 | `frontend/_backup/**`(8), `docker-compose*.bak-*`(3) | 백업 파일, `.gitignore` `*.bak-*` 대상 |
| 잔재 | `tgres` | 잘못 커밋된 psql 출력 |
| 미사용 소스 | `AgentNode.jsx`, `graphClustering.js`, `graphMigration.js` | 통합 트리에서 import 0건 확인, 빌드 통과 |

### 2.5 main에서 LLM-clean으로 들어오지 않은(= main에만 있는) 변경
통합 후 `main`은 LLM-clean에 없는 다음 변경을 포함합니다. 모두 추가형이며 **운영(LLM-clean)에는 아직 배포되지 않은 코드**입니다.

| 파일 | 내용 |
|---|---|
| `backend/.../WebSocketConfig.java` | STOMP 브로커 heartbeat 10s/10s + TaskScheduler |
| `GroupStudySocketController.java`, `GroupStudySocketDTO.java` | 채팅 broadcast payload에 저장된 메시지 `id` 포함 |
| `frontend/src/utils/webrtc/iceServers.js` 등 | 서버 발급 임시 TURN 자격증명 우선 사용(모바일) |
| `frontend/src/mobile/**`, `android/**`, `capacitor.config.json` | Android 앱(PR #105 시점) |
| `frontend/package.json` | `build:mobile` 등 스크립트, `pdfjs-dist`, `react-test-renderer` 추가, 미사용 `@aws-sdk/client-s3` 제거 |
| `.github/workflows/*`, `.github/scripts/*` | CI 게이트형 `cd.yml`, 브랜치 범위 검사 `ci.yml`, Android 워크플로 |

### 2.6 파일 변경 통계
- 통합 병합 커밋 vs 병합 전 `main`: 추가 896 / 수정 100 / 삭제 2 (`LearningMate.jsx`, `NextLearningCard.jsx` — LLM-clean에서 의도적 삭제, `/learning-mate`는 `/studymate`로 리다이렉트)
- 통합 병합 커밋 vs `LLM-clean`: 추가 347(Android·모바일·CI) / 수정 13(§2.5) / 삭제 32(§2.4)

## 3. Android 통합 (`android-features` → `android-main`)

| 항목 | 결과 |
|---|---|
| 통합 커밋 | `2daff22b` (`--no-ff`) |
| 충돌 | 없음 — android-main 고유 커밋은 PR #106 병합 커밋(내용 변경 0) 하나 |
| 결과 트리 | `origin/android-features`와 동일 |
| 변경 | 추가 140 / 수정 51 / **삭제 0** (frontend/src 82, android/app 64, android/screenshare 22, release-notes 8, .github 9 …) |
| AndroidManifest | 권한 INTERNET, ACCESS_NETWORK_STATE, CAMERA, RECORD_AUDIO, MODIFY_AUDIO_SETTINGS, POST_NOTIFICATIONS, RECEIVE_BOOT_COMPLETED, SCHEDULE_EXACT_ALARM(+screenshare 모듈: FOREGROUND_SERVICE, FOREGROUND_SERVICE_MEDIA_PROJECTION) |
| 앱 식별자 | `kr.co.studybridge.app` (변경 없음) |
| API 주소 | 빌드 시 `VITE_API_BASE_URL`(CI: `https://studybridge.co.kr`), 네이티브 타이머 `strings_study.xml` 동일 도메인 |
| 웹·백엔드 동반 변경 | `frontend/src/services/api.js`, `utils/groupStudy.js`, `utils/adaptiveNavigator.js` 등 모바일 화면이 쓰는 공용 모듈. 백엔드 소스 변경 없음 |

### 웹 프론트 코드 이원화 주의
`android-main`/`android-features`의 `frontend/`는 `LLM-clean`의 `frontend/`와 별도로 진화합니다(예: 그룹 자료 업로드가 Android 라인은 `axios.post`, LLM-clean은 공통 `api` 인스턴스). 이번 통합 후 `main`의 `android/`·`frontend/src/mobile/`은 **android-main보다 42커밋 뒤처진 상태**입니다. `android-main` → `main` 동기화는 별도 PR로 진행하되, Android 브랜치의 `fastapi/` 등 범위 정리 삭제가 다시 main에 들어가지 않도록 같은 방식(삭제 경로 복원)으로 처리해야 합니다.

## 4. 테스트 결과
요약만 적습니다. 상세는 [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md).

| 항목 | 결과 |
|---|---|
| Backend `gradlew clean build` | PASS — 694 tests / 0 fail / 25 skip |
| Frontend build, build:mobile, lint:mobile, bundle guard | PASS |
| 모바일 테스트 (main 통합) | 438/438 PASS (병합 직후 3건 실패 → 테스트 결합 문제 수정) |
| 모바일 테스트 (android 통합) | 550/550 PASS |
| FastAPI compileall / pytest | PASS / 1506 pass·27 fail·4 error (LLM-clean과 동일한 기존 실패) |
| docker compose config | PASS |
| Android Gradle Debug 빌드·단위 테스트·lint | PR #122 Android CI PASS (로컬은 디스크 95%·Node 22 부재로 미실행) |
| Android 실기기·서명 Release 빌드 | 미실행(기기·keystore 없음) |
| PR #121 GitHub CI(`ci.yml` 전 잡) | PASS (1차 Maven Central 429 → 재실행 통과) |

## 5. 품질 기준 점검

| 기준 | 상태 |
|---|---|
| 필수 빌드 성공 | ✅ (Android 로컬 빌드는 CI 위임) |
| 필수 테스트 성공 | ✅ 백엔드·모바일 / ⚠️ FastAPI 기존 실패 27건(병합 무관) |
| 미해결 충돌 없음 | ✅ |
| 의도하지 않은 파일 삭제 없음 | ✅ (삭제 2+32건 모두 근거 기록) |
| 신규 비밀값 노출 없음 | ✅ (기존 노출 1건 예시 파일에서 제거) |
| README와 코드 일치 | ✅ 기능표는 코드 근거 기반, 부분 구현 명시 |
| CI/CD 영향 검토 | ✅ §6 |
| 롤백 가능 | ✅ 백업 태그 + revert 절차 §8 (실제 revert 리허설은 미실시) |

## 6. CI/CD 영향 분석

### 6.1 병합 시 트리거
| 이벤트 | 실행되는 워크플로 | 운영 영향 |
|---|---|---|
| PR #121 생성/갱신 | `ci.yml`(pull_request → main) | 없음 |
| #121을 `main`에 병합(push main) | `ci.yml`만 | **없음** — `cd.yml`은 `LLM-clean` push 전용, main의 `android-release.yml`은 `android-main` push 전용 |
| PR #122 생성/갱신 | `android-ci.yml`(pull_request → android-main) | 없음 |
| #122를 `android-main`에 병합(push android-main) | `android-ci.yml` | **없음** — 병합 결과의 `android-release.yml` 트리거는 `android-features` push 뿐이며, 게시 단계도 `refs/heads/android-features`에서만 실행 |

→ **두 병합 모두 운영 재배포, APK 게시, 버전 증가를 일으키지 않습니다.** 이중 배포 위험 없음.

### 6.2 현재 운영 경로(변경하지 않음)
- 웹: `LLM-clean` push → `LLM-clean`의 `cd.yml`(CI 대기 게이트 없음) → EC2.
- Android: `android-features` push → `android-release.yml` → 서명 APK → EC2 → S3 `latest`.

### 6.3 배포 브랜치를 `main`으로 옮길 때(별도 승인 필요)
1. `main`의 `cd.yml`은 `LLM-clean`의 `cd.yml`보다 새 버전(CI 성공 대기 `wait-for-ci.sh`, SHA가 `origin/LLM-clean`에 있는지 검증, 배포 후 공개 API 점검, 프론트 심볼릭 링크 롤백, `git stash` 보관)입니다. 배포 브랜치명이 코드 곳곳(`git switch LLM-clean`, SHA 포함 검증)에 하드코딩되어 있어 **트리거만 바꾸면 실패**합니다.
2. EC2 작업 트리(`/home/ubuntu/studyBridge`)는 `LLM-clean` 체크아웃이며 운영 비밀 파일·untracked 산출물이 함께 있습니다. 전환 시 체크아웃 브랜치 변경 계획이 필요합니다.
3. `main`과 `LLM-clean` 양쪽에 CD 트리거를 두면 같은 커밋이 두 번 배포될 수 있으므로, 전환은 "LLM-clean 트리거 제거 + main 트리거 추가"를 한 PR에서 처리해야 합니다.
4. `android-release.yml`의 `validate-release-notes`는 `origin/LLM-clean`의 `appRelease.js`를 참조합니다. LLM-clean을 없애면 함께 수정해야 합니다.
5. 권장 순서: (a) #121 병합 → (b) 일정 기간 `LLM-clean`→`main` 동기화 PR 유지 → (c) 운영 배포 전환 PR(위 1~4 반영, 수동 `workflow_dispatch`로 리허설) → (d) 승인 후 전환.

## 7. 보안 검사 결과

### 7.1 통합 브랜치(현재 트리)
- 정규식 스캔 결과 실제 비밀값 없음(테스트 픽스처의 가짜 `sk-…`, `AKIAIOSFODNN7EXAMPLE` 류만 존재).
- 추적되는 `.env`, `.pem`, `.jks`, `key.properties` 없음.
- `fastapi/.env.example`, `fastapi/.env copy.example`의 `AI_SERVER_API_KEY` 실값(과거 노출 키와 동일, 현재 운영 키와는 다름)을 플레이스홀더로 교체.

### 7.2 Git 이력 (공개 저장소) — **즉시 조치 필요**
값은 출력하지 않고 SHA-256 지문으로 현재 운영 값과 비교했습니다. 아래 커밋은 `origin/main`, `origin/LLM-clean`, `origin/android-features`에서 도달 가능합니다.

| 커밋(날짜) | 파일 | 항목 | 현재 운영 값과 비교 | 위험 |
|---|---|---|---|---|
| `ff9b7999` (2026-06-11) | `fastapi/.env` | AWS Access Key ID | **동일** | 높음 |
| 〃 | 〃 | AWS Secret Access Key | 다름(손상본 가능성) | 높음 — 같은 Key ID 사용 중이므로 키 쌍 교체 필요 |
| 〃 | 〃 | Tavily API Key | **동일** | 중간 |
| 〃 | 〃 | OpenAlex API Key | **동일** | 낮음~중간 |
| 〃 | 〃 | `AI_DATABASE_URL`(DB 접속 문자열, 비밀번호 포함) | **동일** | 높음 |
| 〃 | 〃 | `AI_SERVER_API_KEY` | 다름(교체됨) | 낮음(구 키가 ai07에서 여전히 허용되는지 확인 필요) |
| `57a32a2f` (2026-06-08) | `fastapi/studybridge2026.pem` | SSH 개인키 | EC2 로컬 파일과 **동일** | 높음 — 해당 공개키가 남아 있는 `authorized_keys` 확인 필요 |
| `c87f2555` (2026-05-18) | `.env` | `DB_PASSWORD` | **동일 값**(DB 호스트는 변경됨) | 높음 — 현재 RDS 비밀번호와 같다면 즉시 교체 |

이 커밋들은 이후 삭제되었지만(`577b8a6f`, `d403b198`) 공개 이력에 그대로 남아 있습니다.

**권장 조치(운영 영향이 있어 승인 후 진행)**
1. AWS IAM 액세스 키 비활성화 → 새 키 발급 → EC2 `.env`·`fastapi/.env`·ai07 반영 → 구 키 삭제. CloudTrail에서 비정상 사용 확인.
2. RDS 마스터/앱 계정 비밀번호 교체(`DB_PASSWORD`, `AI_DATABASE_URL`).
3. Tavily·OpenAlex 키 재발급.
4. `studybridge2026.pem` 대응 공개키를 모든 서버 `authorized_keys`에서 제거(9/26 `studybridge-2026b`로 교체된 기록이 있으나 잔존 여부 확인).
5. ai07에서 구 `AI_SERVER_API_KEY` 거부 확인.
6. 키 교체 **후** 이력 정리(git filter-repo + 강제 push)는 모든 협업자 클론·PR·포크에 영향을 주는 이력 재작성이므로, 이번 작업에서는 수행하지 않았습니다. 키를 폐기하면 이력에 남은 값은 무력화되므로 **폐기·재발급이 우선**입니다. GitHub Secret scanning / push protection 활성화도 권장합니다.

### 7.3 애플리케이션 보안 관찰(이번 범위에서 수정하지 않음)
| 항목 | 위치 | 비고 |
|---|---|---|
| 관리자 기본 비밀번호 코드 고정 | `backend/.../config/AdminInitializer.java` | 운영 계정 비밀번호 변경 여부 확인 권장 |
| CORS `*`(credentials off), STOMP `setAllowedOriginPatterns("*")` | `SecurityConfig.java`, `WebSocketConfig.java` | 도메인 화이트리스트 권장 |
| STOMP CONNECT 미인증(사칭 가능) | 그룹 채팅/퀴즈 | PR #119/#120에서 수정 진행 중(Draft) |
| FastAPI는 `AI_SERVER_API_KEY` 미설정 시 인증 생략 | `fastapi/app/core/security.py` | 운영은 설정되어 있음 |
| `docker-compose.yml` 비밀번호 기본값(개발용 placeholder), TURN 공인 IP 기본값 | `docker-compose.yml` | 운영은 `.env`로 덮어씀 |
| `ops/studybridge-fastapi.service` 상단 "DO NOT ENABLE" 주석과 달리 `cd.yml`이 이 유닛을 enable | `ops/`, `cd.yml` | 문서/주석 정합성 확인 필요 |

## 8. 롤백 방법

| 상황 | 명령 |
|---|---|
| #121 병합 후 되돌리기 | `git switch main && git pull && git revert -m 1 <PR#121 병합 커밋> && git push origin main` (이력 보존) |
| #122 병합 후 되돌리기 | `git switch android-main && git pull && git revert -m 1 <PR#122 병합 커밋> && git push origin android-main` |
| 특정 브랜치 원래 SHA 확인 | `git rev-parse backup/pre-integration-20261118/<branch>` (태그) |
| 통합 브랜치 폐기 | PR Close 후 `git push origin --delete integration/<name>` (승인 시) |

`git push --force`, `reset --hard`를 사용하는 복구는 사용하지 않습니다. 운영 배포 롤백은 [DEPLOYMENT.md §6](DEPLOYMENT.md#6-롤백)을 따르며, 이번 병합은 운영 배포를 일으키지 않습니다.
revert 절차는 문서화했으나 실제 리허설은 수행하지 않았습니다.

## 9. 최종 승인 대기 항목
1. PR #121(`integration/llm-clean-to-main` → `main`) 병합 — CI 통과 확인됨
2. PR #122(`integration/android-features-to-main` → `android-main`) 병합 — Android CI 통과 확인됨, 실기기 확인 권장
3. 기존 PR #107(LLM-clean → main) 종료 여부 — #121이 같은 목적을 안전하게 대체
4. **노출 자격증명 폐기·재발급(§7.2)** — 운영 서비스 영향이 있어 일정 협의 필요
5. 운영 배포 트리거 `LLM-clean` → `main` 전환(§6.3) — 별도 계획 PR
6. `android-main` → `main` Android 코드 동기화(§3) — 별도 PR
7. FastAPI 기존 테스트 실패 27건·수집 오류 4건 정리 — AI 담당
