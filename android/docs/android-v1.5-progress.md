# Android v1.5 진행 기록

- 개발 브랜치: `feature/android-v1.5` (기준 `origin/android-features` = `d6858bb5`)
- 서버 계약 기준: `origin/LLM-clean` = `c005e291` (읽기만 함, 변경 없음)
- 공개 APK: 1.4 / versionCode 5 → 다음 릴리스 1.5 / versionCode 6 (CI 가 공개 `/api/app/version` 기준으로 자동 계산)
- **주의:** `android-features` 에 push 하면 `android-release.yml` 이 서명 APK 를 운영 서버에 자동 배포한다.
  이 브랜치는 PR 로만 합치고, 병합·배포는 사용자 승인 후 진행한다.

## 작업 환경 제약 (Termux Ubuntu proot)

- Node 24 는 `/data/data/com.termux/files/usr/bin` 에 있다(`export PATH=$PATH:/data/data/com.termux/files/usr/bin`).
- Java / Gradle / Android SDK / python3 없음 → Gradle 빌드·Kotlin 테스트·APK 생성은 GitHub Actions 에서만 가능.
- `gh` 미인증 → PR 생성·CI 결과 확인 불가(NOT VERIFIED).
- 메모리 10GB 중 8GB 사용 상태. 2026-10-28 첫 세션에서 `npm run test:mobile`(병렬) 실행 중 `/data` 바인드 마운트가 사라짐.
  → 테스트는 파일 단위로 순차 실행하고, 전체 실행은 `--test-concurrency=1` + `timeout` + 로그 파일로만 한다. 파이프(`| tail`)는 proot 에서 종료되지 않는 경우가 있어 쓰지 않는다.

## 데이터 흐름

```
React(WebView, frontend/src/mobile) ──axios(JWT)──▶ EC2 Spring(/api/**) ──▶ RDS / Redis
        │                                              │
        └─ openvidu-browser(PRIMARY 카메라·마이크) ◀──▶ OpenVidu ◀── screen-token(SCREEN, PC 웹 송출)
                                                       │
화면 분석: 원격 SCREEN <video> 프레임 1장(JPEG) ──▶ POST /api/groups/{g}/screen-ai/analyze ──▶ ai07 VLM(큐·동시성 서버 관리)
```

## 단계별 결과

| 단계 | 상태 | 커밋 |
|---|---|---|
| STEP 1 학습리포트 자동 실행 방지 | 완료(단위·컴포넌트 테스트) | `8e1cd2c2` |
| STEP 2 PDF별 퀴즈 랭킹 | 완료(앱), 운영 서버 배포 여부 미확인 | `ce901079` |
| STEP 3 플래너 → 자료보관함 저장 | 완료 | `91b2e101` |
| STEP 4 자료보관함 레거시 정리 | 완료(보수적) | `b0946257` |
| STEP 5 Android 네이티브 화면공유 송출 | **미구현** — SCREEN 판정 규칙 통일만 완료 | `25ee0f67` |
| STEP 6 VLM 화면 분석 연동 | 완료(수신 화면 분석, Android 송출 화면은 STEP 5 이후) | `bb3970ce` |
| STEP 7 릴리스 후보 | 릴리스 노트 작성·검증, CI/APK 미확인 | 이 문서 커밋 |

### STEP 1 — 학습리포트 자동 실행

- 원인: 그룹방 입장 때 `POST /api/timers/sync/{g}` 호출(heartbeat 없음) + 학습리포트 개인 타이머가 `supportsHeartbeat` 없이 시작하고 heartbeat 를 보내지 않음 →
  서버 reaper 가 90초 무응답 종료를 못 하고 24시간 STARTED 로 남음. 서버는 `c005e291` 에서 구버전 sync 를 '연결만' 으로 바꿈.
- 변경: 그룹방 sync 호출 제거(그룹방 경과 시간은 기존 로컬 `roomClock`), 개인 타이머 `supportsHeartbeat=true` + 30초 heartbeat,
  204·다른 세션이면 서버 재조회, 백그라운드 복귀 재조회, 종료 `USER_STOP`, 그룹 세션은 분리 표시·heartbeat 안 함, 경과는 서버 시각 기준.
- 파일: `screens/report/studySessionModel.js`(신규), `StudyTimerPanel.jsx`, `room/StudyRoomView.jsx`, `services/api.js#timerService`.
- 앱 강제 종료: 서버 reaper 가 마지막 heartbeat 시각으로 종료(손실 ≤ 30초) → 재실행 시 서버에 활성 세션이 없으면 실행 중으로 표시하지 않음.
- 로그아웃 시 진행 중 개인 세션을 종료하지 않는다(웹과 동일). heartbeat 가 끊기면 서버가 종료한다.

### STEP 2 — PDF별 퀴즈 랭킹

- 서버(`1f19e937`): `GET /api/materials/{m}/quiz/{q}/ranking?limit=1..100`, 정책 `BEST_SCORE`, Redis Lua 로 원자 갱신(ZADD GT) →
  동시 제출·중복 요청 무결성은 서버 책임. 공유: `GET /api/groups/{g}/shared-materials`, `GET /api/materials/{m}/shared-quizzes`.
- **확정 정책과의 차이(보고):** 서버 동점 처리 = 최고점 내림차순 → 같은 점수는 같은 순위(1,1,3) → 표시 순서는 먼저 달성한 사람.
  - 정답률 기준: 점수 = round(정답/채점문항×100) 이라 같은 퀴즈에서 정답률과 점수는 같은 기준이다(별도 효과 없음).
  - **풀이 시간: 서버가 저장·응답하지 않음** → 앱에서 표시·정렬 불가. 필요하면 EC2 변경: 제출 요청에 풀이 시간 측정(서버 기준 시작 시각 발급 권장),
    StoredScore 에 bestDurationMs 추가, ZSET 점수 인코딩에 시간 역순 반영, RankingEntry 에 `durationSeconds` 추가.
  - 앱은 서버 순서를 바꾸지 않는다(안정 정렬, rank 그대로).
- 플래그: `android-release.yml`, `android-ci.yml` 의 `npm run build:mobile` 단계에 `VITE_FEATURE_MATERIAL_RANKING: "true"`.
- 운영 배포 확인: 비인증 요청은 경로와 무관하게 401 이라 운영 엔드포인트 존재를 확인하지 못함(NOT VERIFIED).
  서버에 경로가 없으면 앱은 '서버 준비 중' 안내(404 code 없음)로 동작한다.
- **남은 제품 공백:** 그룹 멤버가 '남의 공유 PDF 퀴즈를 응시'하는 UI 와, 소유자가 PDF 를 그룹에 공유하는 UI 가 웹·Android 모두 없다
  (`POST /api/materials/{m}/shares`, `shared-quizzes` + 기존 submit 으로 구현 가능). 현재는 소유자 응시 기록 중심으로 랭킹이 보인다.

### STEP 3 — 플래너 → 자료보관함

- 기존 `plannerService.archive` → `POST /api/planners/{id}/archive` 재사용. 서버가 소유권 검증, 같은 플래너 재저장 시 같은 Material 갱신, 미리보기 PDF 재생성.
- 응답 `materialId` 로 `/archive/{materialId}` 이동, 성공 안내는 router state 로 전달. 이미 보관한 플래너는 '자료보관함 갱신'.

### STEP 4 — 자료보관함 레거시

- `screens/archive/` 29개 파일(이전 보고 28개 + PR #108 이후 랭킹 파일) 전부 운영 import 가 있어 파일 삭제 없음.
- 삭제: `quizModel.js` 의 클라이언트 채점 함수 7개(운영 참조 0건, 서버 채점 `materialQuizModel.js` 로 대체됨)와 그 테스트.
- 유지(판단 보류): `utils/webrtc/iceServers.js#parseConnectionMetadata` — STEP 5 이후 참조 0건이나 공용 utils 라 이번에는 남김.

### STEP 5 — Android 네이티브 화면공유 송출 (미구현)

**완료한 부분:** SCREEN 인식 규칙 통일(`screens/groupstudy/connectionIdentity.js`).
- 기존 충돌: Android 는 `connection.data` 의 첫 번째 파싱 가능 세그먼트(clientData, 위조 가능)로 userId 를 읽고 SCREEN 은 `typeOfVideo` 만 봄.
  웹(LLM-clean `utils/videoConnection.js`)은 마지막 세그먼트 serverData(Spring 발급)의 `kind` 를 신뢰.
- 확정 규칙: serverData(`app=studybridge`)가 있으면 userId·kind 는 그것만 신뢰. SCREEN = `serverData.kind==='SCREEN'` 이거나,
  그렇지 않은 연결(PRIMARY·레거시)은 `typeOfVideo==='SCREEN'` 일 때만. CUSTOM/IPCAM/누락은 카메라.
  → 네이티브 libwebrtc 송출이 typeOfVideo 를 CUSTOM 으로 보내도 SCREEN 으로 표시되고, 기존 PC 화면공유 수신은 그대로.

**미구현 사유:** 이 환경에 JDK/Android SDK 가 없어 Kotlin·libwebrtc 코드를 컴파일·실행·실기기 검증할 수 없다.
검증 없이 MediaProjection/Foreground Service 코드를 릴리스 후보에 넣으면 1.5 전체 빌드·심사 위험이 커서 넣지 않았다.

**설계(다음 작업):**
- 서버 계약: `POST /api/groups/{g}/video/screen-token` `{ primaryConnectionId, clientInstanceId, deviceType:'ANDROID' }`
  → SCREEN 토큰(serverData kind=SCREEN, ownerConnectionId=내 PRIMARY). 오류 code: `NOT_GROUP_MEMBER`, `CONNECTION_OWNER_MISMATCH`,
  `INVALID_CONNECTION_ID`, `PRIMARY_NOT_ACTIVE`(409), `SCREEN_ALREADY_ACTIVE`(409). 종료 안전망 `DELETE /api/groups/{g}/video/screen/{connectionId}`.
  그룹당 2명 제한은 서버 정책 — 클라이언트는 서버 오류를 그대로 안내.
- 구성: WebView(PRIMARY 유지) → Capacitor 플러그인 `ScreenSharePlugin.start({ token, iceServers })` →
  `ScreenShareService`(Foreground Service, `foregroundServiceType="mediaProjection"`) → `MediaProjection` → `ScreenCapturerAndroid`(libwebrtc)
  → OpenVidu 2.x JSON-RPC(WebSocket: joinRoom → publishVideo(typeOfVideo=SCREEN, hasAudio=false) → onIceCandidate) 별도 연결.
- Manifest: `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_MEDIA_PROJECTION`(Android 14+), `POST_NOTIFICATIONS`(13+).
- Android 14+ 순서: `createScreenCaptureIntent()` 동의 → **동의 결과를 받은 뒤** FGS 시작(type=mediaProjection) → `getMediaProjection()`.
  동의 토큰은 1회용, `MediaProjection.Callback.onStop`(시스템 '공유 중지'·화면 잠금 등)에서 즉시 정리.
- 상태 머신: `IDLE → REQUESTING_CONSENT → STARTING_SERVICE → FETCHING_TOKEN → CONNECTING → PUBLISHING → STOPPING → IDLE`,
  어느 단계 실패든 `STOPPING` 으로: track.dispose → capturer.stopCapture → peerConnection.close → WS close → DELETE screen/{connectionId} → stopForeground.
- 회전/해상도: `onConfigurationChanged` 에서 `capturer.changeCaptureFormat(w,h,fps)`. 네트워크 변경: ICE restart 1회 후 실패 시 종료·안내(재시작은 사용자 조작).
- 프로세스 강제 종료: 서버 OpenVidu 연결 타임아웃 + 다음 실행 시 `GET /video/connections` 로 내 SCREEN 잔존 확인 후 DELETE.
- FLAG_SECURE 화면은 시스템이 검게 송출 — 우회하지 않음.
- 검증 필요(실기기): Android 10/13/14/15, PC↔Android 양방향, 2명 제한, 카메라·마이크 동시, 백그라운드·회전·권한 취소.

### STEP 6 — VLM 화면 분석

- 기존 EC2 API 재사용(`GroupScreenAiController`): shares / consent / analyze / cancel. ai07 큐·동시성·사용자당 진행 1건·분당 6회·스트림 일치·동의는 서버가 검증.
- Android(수신자): 그룹방 채팅/AI 패널 '화면 분석' 탭. 원격 SCREEN `<video>` 의 현재 프레임 1장을 canvas → JPEG(긴 변 1280, 1MB 한도) 로 보내고 보관하지 않음.
  선택 영역은 고정 스냅샷 위 드래그 → 정규화 좌표 → 원본 해상도로 잘라 전송(프레임 동기화).
- WebView 캡처 가능성: 원격 WebRTC MediaStream 은 교차 출처 리소스가 아니라 canvas 가 오염되지 않는다(Chromium 동작). **실기기 미검증.**
- Android 를 공유자로 하는 동의 UI(`PUT consent`)는 STEP 5(Android 송출) 이후 필요.

## 테스트 기록

각 명령은 `frontend/` 에서 실행, 로그는 세션 scratchpad `logs/`.

| 대상 | 명령 | 결과 |
|---|---|---|
| STEP 1 모델/패널/입장 | `node --test src/mobile/__tests__/{studySessionModel,studyTimerPanel,groupTypeEntry}.test.mjs` | PASS 7/7, 8/8, 5/5 |
| STEP 2 | `materialRanking`, `materialRankingPolicy`, `sharedMaterialRanking` | PASS 17/17, 8/8, 5/5 |
| STEP 3 | `plannerArchive`, `plannerAdapter`, `plannerRuntime` | PASS 6/6, 17/17, 6/6 |
| STEP 4 | `quizModel`, `quizSubmission`, `materialQuizModel`, `materialQuizMobile`, `reviewNoteRetrySubmission` | PASS |
| STEP 5 | `screenShareReceive`, `groupStudyModel`, `groupMediaJoin`, `participantRoster`, `participantsPanel` | PASS |
| STEP 6 | `screenAiModel`, `screenAnalysisFlow` | PASS 10/10, 5/5 |
| 모바일 lint | `npm run lint:mobile` | PASS(경고 0) |
| 릴리스 노트 | `node .github/scripts/validate-release-notes.mjs --version 1.5 ...` | PASS(6항목) |
| 전체 모바일 테스트 | `node --test --test-concurrency=1 src/mobile/__tests__/*.test.mjs` | PASS 506/506 (66초) |
| Gradle / APK / Kotlin 테스트 | — | NOT RUN(도구 없음, CI 위임) |
| 실기기 / PC↔Android / 동시성 A~D | — | NOT RUN(운영 부하 테스트 금지, 격리 환경 없음) |

## 재개 명령

```bash
cd /data/data/com.termux/files/home/studyBridge
git switch feature/android-v1.5 && git log --oneline origin/android-features..HEAD
export PATH=$PATH:/data/data/com.termux/files/usr/bin
cd frontend && timeout 300 node --test src/mobile/__tests__/<이름>.test.mjs > /tmp/<이름>.log 2>&1; echo $?
# push(배포 트리거 없음): git push -u origin feature/android-v1.5
# PR: gh auth login 후 gh pr create --base android-features --head feature/android-v1.5
```
