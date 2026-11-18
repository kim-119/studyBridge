# Android 네이티브 전체 화면공유 (v1.6 후보)

> 상태: **구현·자동 테스트 완료, 실기기 미검증 → v1.5 릴리스에는 포함하지 않음(빌드에서 제외)**
> 브랜치: `feature/android-v1.5` (PR #112). 기본 빌드·릴리스 워크플로는 `:screenshare` 모듈을 넣지 않는다.

## 1. 구조

```
WebView(React)                              Android 네이티브(:screenshare)                     EC2 / OpenVidu
──────────────                              ─────────────────────────────                     ──────────────
PRIMARY(카메라·마이크, openvidu-browser) ──────────────────────────────────────────────────▶ OpenVidu (그대로)
useNativeScreenShare
 1 GET  video/connections (슬롯 사전 확인) ─────────────────────────────────────────────────▶ Spring
 2 requestConsent ───────────▶ ScreenSharePlugin → createScreenCaptureIntent(시스템 선택창)
 3 POST video/screen-token(primaryConnectionId, ANDROID) ─────────────────────────────────────▶ Spring(슬롯·소유 검증, 30초 예약)
 4 start(token, iceServers) ─▶ ScreenShareService(FGS type=mediaProjection)
                                 startForeground → getMediaProjection → registerCallback
                                 DisplayCapturer(VirtualDisplay 1개, AUTO_MIRROR) → VideoSource(screencast)
                                 ScreenPublisher: OkHttp WS JSON-RPC ── joinRoom/publishVideo(SCREEN)/ICE ──▶ OpenVidu SCREEN Connection
 5 stateChange 이벤트 ◀────────  starting/connecting/publishing/stopping/idle(reason)
 6 idle(reason) → DELETE video/screen/{connectionId} (멱등 슬롯 반환) ────────────────────────▶ Spring
```

- 화면 범위: MediaProjection 전체 디스플레이. 앱 종류별 캡처 코드나 허용 목록 없음 → 브라우저·게임·PDF 뷰어·홈 화면 등 시스템이 허용하는 모든 화면.
  Android 14 QPR2+ 의 시스템 선택창(전체 화면/단일 앱)은 앱이 바꾸지 않는다. FLAG_SECURE 화면은 시스템이 검게 송출(우회 없음).
- 앱 전환·백그라운드: 송출은 Foreground Service + 별도 PeerConnection 이라 Activity/WebView 상태와 무관. 공유 중 알림에 '공유 중지'.
- 회전·해상도 변경: DisplayManager 리스너 → 같은 VirtualDisplay `resize` + `streamPropertyChanged(videoDimensions)` (Android 14+ 는 재생성 금지).
- 정지 화면: 1초간 새 프레임이 없으면 `SurfaceTextureHelper.forceFrame()` 으로 마지막 프레임 재전송(새 시청자 첫 화면 보장).
- 송출 품질: 긴 변 1280px(16배수), 15fps, 서버 `maxSendKbps`(기본 2500) 상한, `MAINTAIN_RESOLUTION`(글자 선명도 우선).

## 2. 서버 계약 (EC2 `GroupVideoCallService`, 변경 없음)

| 항목 | 서버 동작 |
|---|---|
| 인증 | JWT(Spring Security) |
| 그룹 권한 | JOINED 멤버만, 아니면 403 `NOT_GROUP_MEMBER` |
| PRIMARY 귀속 | `primaryConnectionId` 가 active 이고 serverData(userId=나, kind=PRIMARY), 아니면 409 `PRIMARY_NOT_ACTIVE` / 403 `CONNECTION_OWNER_MISMATCH` |
| 슬롯 | 방 단위 잠금 안에서 그룹당 `openvidu.screen-share.max-per-group`(기본 2) · 사용자당 1개. 409 `SCREEN_SHARE_LIMIT_REACHED` / `SCREEN_ALREADY_ACTIVE` / `SCREEN_START_IN_PROGRESS` |
| 예약 | 발급 후 30초(`pending-ttl-ms`) 안에 접속하지 않으면 슬롯으로 보지 않음 → **동의를 먼저 받고 토큰을 받는다** |
| 분류 | serverData `kind=SCREEN`, `ownerConnectionId` = 내 PRIMARY. 웹·Android 수신자는 serverData 로 판정 |
| 정리 | 만료 예약·주인 없는(orphan) SCREEN·한도 초과를 주기적으로 닫음. `DELETE video/screen/{id}` 멱등 |
| 카메라 인원 | 화면공유 슬롯과 별개(SCREEN 은 참여 인원에 더해지지 않음) |

서버 변경 필요 사항: **없음**(기존 계약으로 구현 가능).

## 3. 종료·정리 (모두 한 번만 실행, 중복 요청은 무시)

| 원인 | 감지 | 사유(reason) |
|---|---|---|
| 앱 '공유 중지'·알림 '공유 중지' | ACTION_STOP | user-stopped |
| 시스템 공유 중지(상태 칩·권한 회수) | MediaProjection.Callback.onStop | permission-revoked |
| 네트워크 단절 | PeerConnection DISCONNECTED 15초 유예 후 / FAILED / ping 3회 무응답 / WS 실패 | network-lost |
| 서버 종료(정책 정리·강제 해제) | WS 종료, participantEvicted/Unpublished/Left(내 연결) | server-closed |
| 연결 실패 | joinRoom/publishVideo 오류, 25초 안에 미연결 | connection-failed |
| 앱 작업 종료·서비스 종료 | stopWithTask / onDestroy | app-closed |
| 그룹스터디 퇴장 | 그룹방 화면 언마운트 → stop | user-stopped |

정리 순서: leaveRoom·WS close → PeerConnection → VideoTrack → 캡처(VirtualDisplay·Surface) → VideoSource → SurfaceTextureHelper
→ PeerConnectionFactory → AudioDeviceModule → EGL → MediaProjection.stop → stopForeground/stopSelf → (JS) `DELETE video/screen/{id}`.

자동 재연결: 하지 않는다. 네트워크가 끊기면 안전하게 종료하고 사용자가 다시 시작한다
(Android 14+ 는 MediaProjection 동의를 재사용할 수 없어, 무단 재시작은 정책 위반이다). 짧은 끊김은 ICE 가 15초 안에 스스로 회복하면 유지.

## 4. 빌드

```bash
cd android
./gradlew assembleDebug                      # 기본(=v1.5 릴리스 구성): 화면공유 미포함
./gradlew assembleDebug -PsbScreenShare=true # 실기기 검증용: 화면공유 포함
./gradlew :screenshare:testDebugUnitTest :screenshare:lintDebug
```

CI(`android-ci.yml`)가 두 APK 를 모두 만든다: `studybridge-app-debug`(미포함 확인 가드), `studybridge-app-debug-screenshare`.

CI 실측(커밋 `861a96cc`, run 40783885680): `:screenshare` compileDebugKotlin·testDebugUnitTest·lintDebug PASS,
기본 Debug APK 18.8MB(libwebrtc 없음 확인), 화면공유 포함 Debug APK 69.7MB(libwebrtc `.so` 4개 ABI 비압축 저장).
v1.6 전 크기 조정 후보: `ndk.abiFilters`(arm64-v8a, armeabi-v7a, x86_64) 또는 `jniLibs.useLegacyPackaging`.
v1.6 에서 켜려면 `android-release.yml` 의 `assembleRelease` 에 `-PsbScreenShare=true` 를 넣고 미포함 가드를 포함 확인으로 바꾼다.

## 5. 실기기 검증 체크리스트 (모두 NOT RUN — 이 환경에 기기 없음)

준비: CI artifact `studybridge-app-debug-screenshare` 설치(디버그 서명이라 운영 1.4 와 서명이 달라 기존 앱 삭제 후 설치), 같은 그룹에 PC 1대 + Android 2대.

| ID | 항목 | 기대 결과 | 결과 |
|---|---|---|---|
| A | StudyBridge 내부 화면 공유 | PC·Android B 에 화면 타일 표시 | NOT RUN |
| B | Chrome 화면 공유 | 앱 전환 후에도 송출 유지 | NOT RUN |
| C | 다른 설치 앱(메신저·PDF·코드 편집기) | 표시, FLAG_SECURE 앱은 검은 화면 | NOT RUN |
| D | 게임 앱 | 15fps 로 표시, 앱 끊김 없음 | NOT RUN |
| E | 앱 전환 후 공유 유지 | StudyBridge→Chrome→게임→PDF→홈→StudyBridge 동안 끊김 없음 | NOT RUN |
| F | 홈 화면 공유 | 표시 | NOT RUN |
| G | 화면 회전 | 가로/세로 전환 후 비율 맞게 계속 송출 | NOT RUN |
| H | PC 에서 Android 공유 수신 | 웹 화면공유 스테이지에 표시(kind=SCREEN) | NOT RUN |
| I | 다른 Android 에서 수신 | 화면공유 타일·전체화면 | NOT RUN |
| J | 그룹당 2명 제한 | 세 번째 시도는 동의창 전에 '최대 2명' 안내 | NOT RUN |
| K | 종료 시 슬롯 반환 | 종료 직후 다른 사람이 시작 가능 | NOT RUN |
| L | 권한 취소(상태 칩 '공유 중지') | 정상 종료, 안내, 슬롯 반환 | NOT RUN |
| M | 네트워크 단절 | 15초 유예 후 종료·안내, 재시작 가능 | NOT RUN |
| N | 카메라·마이크 회귀 | 공유 중에도 카메라·마이크·스피커 정상 | NOT RUN |
| O | VLM 화면 분석 | 공유자 허용 후 PC/Android 수신자가 분석 | NOT RUN |
| P | 백그라운드 전환·복귀 | 복귀 시 '공유 중' 상태 유지·중지 가능 | NOT RUN |

추가 확인: Android 10/13/14/15 각각, 알림 권한 거부 시 동작, 앱 강제 종료 후 서버 슬롯 정리(서버 orphan 정리 주기), 메모리(30분 공유).
