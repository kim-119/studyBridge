# Android 네이티브 학습 기능 (v1.8 후보)

> 상태: 18개 기능 구현, JVM 단위 테스트 통과, Android 16(API 36) 에뮬레이터에서 운영 서버 대상 동작 확인.
> 실기기·Android 12~15 기기는 아직 확인하지 않았다.
> 브랜치: `feature/android-native-study-productivity` (기준 `origin/android-features` 903d6966).

## 1. 담당과 위치

| ID | 담당 | 기능 | 주요 코드 |
|---|---|---|---|
| J01 | 재홍 | 학습 세션 시작·종료·조회·복구 | `study/StudySessionCoordinator.kt`, `study/StudyTimerApi.kt`, `study/StudyRuntime.kt` |
| J02 | 재홍 | 공부 중 상태 알림 | `notification/StudyNotificationFactory.studying`, `study/StudySurfaces.kt` |
| J03 | 재홍 | 알람 예약·반복·시간대·DST | `reminder/ReminderTimeCalculator.kt`, `reminder/ReminderScheduler.kt`, `reminder/ReminderRestoreReceiver.kt` |
| J04 | 재홍 | 알림 버튼(시작·종료·10분 뒤·앱 열기) | `notification/StudyActionReceiver.kt`, `reminder/ReminderAlarmReceiver.kt` |
| J05 | 재홍 | 빠른 설정 공부 버튼 | `tile/StudyQuickSettingsTileService.kt`, `tile/StudyTileDisplay.kt` |
| J06 | 재홍 | 홈 화면 위젯 | `widget/StudyTimeWidgetProvider.kt`, `widget/StudyWidgetDisplay.kt` |
| B01 | 병준 | 알림 채널 | `notification/StudyNotificationChannels.kt` |
| B02 | 병준 | 기본 알림 생성 | `notification/StudyNotificationFactory.basic`, `StudyNotificationPoster` |
| B03 | 병준 | PendingIntent 식별자 | `notification/StudyPendingIntents.kt` |
| B04 | 병준 | 알람 모델 | `reminder/StudyReminder.kt` |
| B05 | 병준 | 알람 영속 저장 | `reminder/ReminderStore.kt`, `reminder/ReminderJsonCodec.kt` |
| B06 | 병준 | 알람 ID별 취소 | `reminder/ReminderCanceller.kt` |
| Y01 | 영준 | 알람 설정 Activity | `ui/ReminderSettingsActivity.kt`, `ui/ReminderEditActivity.kt` |
| Y02 | 영준 | 시간 선택(12/24시간) | `ReminderEditActivity.showTimePicker`, `ui/ReminderMessages.kt` |
| Y03 | 영준 | 반복 요일 선택 | `activity_reminder_edit.xml`, `ReminderMessages.repeatLabel` |
| Y04 | 영준 | 알림 ON/OFF | `ReminderListAdapter`, `ReminderSettingsActivity.onEnabledChanged` |
| Y05 | 영준 | 소리·진동 선택 | `ui/ReminderAlertStyleOptions.kt`, 채널 4종 |
| Y06 | 영준 | 알람 목록·추가·수정·삭제 | `ui/ReminderListAdapter.kt`, `ReminderSettingsActivity` |

진입점: 앱 `전체 > 학습 알림 설정`(Android 앱에서만 보임) → `StudyBridgeStudyNative.openReminderSettings`.

## 2. 데이터 흐름

```text
알람: 설정 Activity → ReminderValidator → ReminderStore(SharedPreferences, 사용자별 키)
      → ReminderScheduler → AlarmManager → ReminderAlarmReceiver → NotificationManager

공부: 알림 버튼 / 빠른 설정 / 위젯 → StudyActionReceiver·TileService
      → StudyRuntime(단일 스레드, 진행 중 요청 중복 차단) → StudySessionCoordinator
      → Spring /api/timers/current → start | end → /api/study-time/today
      → StudyStatusStore → 알림·타일·위젯 다시 그리기
```

- 서버가 기준이다. 시작 시각·오늘 합계는 서버 응답만 쓰고 로컬 타이머를 따로 두지 않는다.
- 시작 전 `GET /timers/current` 로 진행 중 세션을 확인한다. 개인 세션이 있으면 새로 만들지 않고, 그룹 세션은 바꾸거나 종료하지 않는다.
- 네이티브 시작은 `supportsHeartbeat=false` 다. 앱이 꺼져 있어도 30초 heartbeat 를 보낼 수 없으므로 서버 reaper 대상이 되지 않게 한다.
  학습리포트 화면은 `lastHeartbeatAt` 이 없는 개인 세션에 heartbeat 를 보내지 않는다(`studySessionModel.checkRunningSession`).
  종료하지 않은 heartbeat 없는 세션은 서버 정책대로 24시간 뒤 CANCELLED 된다.

## 3. 인증

- WebView 가 로그인·토큰 갱신·로그아웃 때 access token 을 `shareSession`/`signOut` 으로 넘긴다(`frontend/src/mobile/platform/nativeStudy.js`).
- 네이티브는 access token 을 기존 Keystore 키로 암호화해 저장하고(`SecureSessionVault.writeAccessToken`), 만료 1분 전부터 쓰지 않는다.
- 네이티브는 refresh token 을 쓰지 않는다. 서버가 refresh 때 토큰을 회전하므로 네이티브가 갱신하면 WebView 세션이 끊긴다.
- 토큰이 없거나 만료·거부되면 요청을 5분간 보류하고 앱을 연다(타일) 또는 "눌러서 앱 열기" 알림을 띄운다(알림·위젯).
  앱이 열리면 `accessTokenRequested` 이벤트로 WebView 가 토큰을 갱신해 넘기고, 보류한 요청을 이어서 실행한다.
- 로그아웃: 토큰·상태 삭제, 그 사용자의 알람 예약 취소. 알람 설정은 사용자별로 남겨 두고 같은 사용자가 다시 로그인하면 예약한다.
- 토큰은 Intent·알림에 넣지 않는다. 학습 동작 수신기는 `exported=false`, PendingIntent 는 모두 명시적 컴포넌트 + `FLAG_IMMUTABLE`.

## 4. 권한과 정책

| 항목 | 처리 |
|---|---|
| `POST_NOTIFICATIONS` | 설정 화면에서 요청. 거부되면 알림 없이 동작하고 상태를 화면에 표시 |
| `SCHEDULE_EXACT_ALARM` | 허용 시 `setExactAndAllowWhileIdle`, 아니면 `setAndAllowWhileIdle`(최대 1시간 지연 안내). `USE_EXACT_ALARM` 은 선언하지 않음 |
| `RECEIVE_BOOT_COMPLETED` | 부팅·앱 업데이트·시간/시간대 변경·정확 알람 권한 변경 시 재예약 |
| Foreground Service | 쓰지 않음. 배터리 최적화 예외 요청 없음 |
| 알림 채널 | 학습 상태 1개 + 알람 4개(소리·진동 / 소리 / 진동 / 무음). 화면공유 채널과 별개 |

## 5. 검증 결과 (2026-11-02, 에뮬레이터 API 36, 운영 서버, 테스트 계정)

- JVM 단위 테스트: 신규 84개 + 기존 8개 통과. 모바일 JS 550개 통과. `lintDebug` 오류 0.
- 확인한 동작: 타일 시작 → 서버 세션 생성, 알림 '공부 종료' → 서버 COMPLETED, 위젯 시작·종료와 오늘 합계 일치,
  학습리포트를 연 뒤 떠나도 네이티브 세션이 유지됨(165초), 중복 탭에도 서버 세션 1개,
  외부 `am broadcast` 로 시작 불가, 오프라인 → '연결 오류', 로그아웃 → 알람 취소·'로그인 필요',
  보류 요청이 로그인 후 실행, 서버가 토큰을 거부하면 세션을 만들지 않음,
  알람: UI 추가·수정·스위치·삭제, 앱 프로세스 종료 후 발생, 반복 재예약, 10분 뒤 알림, 시간대 변경, 정확 알람 권한 전환, 재부팅 후 재예약.
- 확인하지 못한 것: 실기기, Android 12~15, 잠금 화면 타일, 서버 응답 지연(타임아웃은 코드로만), 실제 DST 전환(단위 테스트로만),
  화면공유와 동시 사용(채널·ID 분리는 단위 테스트로만).

## 6. 알려진 제약

- 위젯·타일·알림에서 공부를 시작하려면 최근 30분 안에 앱이 토큰을 넘겼어야 한다. 아니면 앱을 한 번 연다.
- 앱 강제 종료(`설정 > 강제 중지`)는 Android 가 앱의 알람을 모두 지운다. 앱을 다시 열면 토큰 공유 시 재예약된다.
- 스누즈 알람은 재부팅하면 사라진다(정기 알람만 재예약).
