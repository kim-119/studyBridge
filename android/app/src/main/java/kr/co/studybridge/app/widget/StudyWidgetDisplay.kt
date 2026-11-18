package kr.co.studybridge.app.widget

import kr.co.studybridge.app.study.StudyIssue
import kr.co.studybridge.app.study.StudyPhase
import kr.co.studybridge.app.study.StudySessionCoordinator
import kr.co.studybridge.app.study.StudySnapshot
import kr.co.studybridge.app.study.StudyTimeText
import java.util.TimeZone

enum class WidgetPrimaryButton {
    START,
    STOP,
    OPEN_APP,
}

data class StudyWidgetDisplay(
    val statusText: String,
    val todayText: String,
    val showsChronometer: Boolean,
    val chronometerStartMillis: Long?,
    val primaryButton: WidgetPrimaryButton,
)

object StudyWidgetDisplays {

    fun of(snapshot: StudySnapshot, hasUsableSession: Boolean, nowMillis: Long, timeZone: TimeZone): StudyWidgetDisplay {
        val todayText = todayTextOf(snapshot, nowMillis)
        val startedAt = snapshot.startedAtMillis

        val needsAppSignIn = !hasUsableSession || snapshot.issue == StudyIssue.LOGIN_REQUIRED
        if (needsAppSignIn && snapshot.phase == StudyPhase.STUDYING && startedAt != null) {
            return StudyWidgetDisplay("공부 중 · 앱을 열어 상태를 확인해 주세요", todayText, true, startedAt, WidgetPrimaryButton.OPEN_APP)
        }
        if (needsAppSignIn) {
            return StudyWidgetDisplay("앱을 열면 공부 버튼을 쓸 수 있어요", todayText, false, null, WidgetPrimaryButton.OPEN_APP)
        }
        if (snapshot.phase == StudyPhase.STUDYING && startedAt != null) {
            val status = "공부 중 · ${StudyTimeText.clockLabel(startedAt, timeZone)} 시작"
            return StudyWidgetDisplay(withIssue(status, snapshot.issue), todayText, true, startedAt, WidgetPrimaryButton.STOP)
        }
        if (snapshot.phase == StudyPhase.GROUP_STUDYING) {
            return StudyWidgetDisplay(withIssue("그룹 스터디 진행 중", snapshot.issue), todayText, false, null, WidgetPrimaryButton.OPEN_APP)
        }
        return StudyWidgetDisplay(withIssue("공부를 시작해 보세요", snapshot.issue), todayText, false, null, WidgetPrimaryButton.START)
    }

    private fun todayTextOf(snapshot: StudySnapshot, nowMillis: Long): String {
        val seconds = snapshot.todayCompletedSeconds
        val isToday = snapshot.todayDateKey == StudySessionCoordinator.serverDateKey(nowMillis)
        return if (seconds != null && isToday) {
            "오늘 공부 ${StudyTimeText.durationLabel(seconds)}"
        } else {
            "오늘 공부 기록 확인 중"
        }
    }

    private fun withIssue(status: String, issue: StudyIssue): String = when (issue) {
        StudyIssue.NETWORK, StudyIssue.SERVER -> "$status (연결 오류)"
        StudyIssue.NONE, StudyIssue.LOGIN_REQUIRED -> status
    }
}
