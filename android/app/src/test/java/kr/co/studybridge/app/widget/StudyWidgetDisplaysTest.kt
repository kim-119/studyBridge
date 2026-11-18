package kr.co.studybridge.app.widget

import kr.co.studybridge.app.study.StudyIssue
import kr.co.studybridge.app.study.StudyPhase
import kr.co.studybridge.app.study.StudySessionCoordinator
import kr.co.studybridge.app.study.StudySnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.TimeZone

class StudyWidgetDisplaysTest {

    private val seoul = TimeZone.getTimeZone("Asia/Seoul")
    private val today = StudySessionCoordinator.serverDateKey(NOW)
    private val idleToday = StudySnapshot.EMPTY.copy(
        phase = StudyPhase.IDLE,
        todayCompletedSeconds = 3_900L,
        todayDateKey = today,
    )

    @Test
    fun idleWidgetShowsServerTotalAndStartButton() {
        val display = StudyWidgetDisplays.of(idleToday, hasUsableSession = true, nowMillis = NOW, timeZone = seoul)

        assertEquals("오늘 공부 1시간 5분", display.todayText)
        assertEquals(WidgetPrimaryButton.START, display.primaryButton)
        assertFalse(display.showsChronometer)
    }

    @Test
    fun studyingWidgetCountsFromServerStartTime() {
        val startedAt = NOW - 15 * 60_000L
        val display = StudyWidgetDisplays.of(
            idleToday.copy(phase = StudyPhase.STUDYING, startedAtMillis = startedAt),
            hasUsableSession = true,
            nowMillis = NOW,
            timeZone = seoul,
        )

        assertTrue(display.showsChronometer)
        assertEquals(startedAt, display.chronometerStartMillis)
        assertEquals(WidgetPrimaryButton.STOP, display.primaryButton)
        assertEquals("공부 중 · 오전 11:45 시작", display.statusText)
    }

    @Test
    fun totalFromPreviousDayIsNotShownAsToday() {
        val display = StudyWidgetDisplays.of(
            idleToday.copy(todayDateKey = "2026-10-27"),
            hasUsableSession = true,
            nowMillis = NOW,
            timeZone = seoul,
        )

        assertEquals("오늘 공부 기록 확인 중", display.todayText)
    }

    @Test
    fun withoutUsableSessionWidgetOnlyOpensApp() {
        val display = StudyWidgetDisplays.of(idleToday, hasUsableSession = false, nowMillis = NOW, timeZone = seoul)

        assertEquals(WidgetPrimaryButton.OPEN_APP, display.primaryButton)
        assertFalse(display.showsChronometer)
    }

    @Test
    fun confirmedStudyKeepsCountingEvenWhenTokenExpired() {
        val display = StudyWidgetDisplays.of(
            idleToday.copy(phase = StudyPhase.STUDYING, startedAtMillis = NOW - 60_000L, issue = StudyIssue.LOGIN_REQUIRED),
            hasUsableSession = false,
            nowMillis = NOW,
            timeZone = seoul,
        )

        assertTrue(display.showsChronometer)
        assertEquals(WidgetPrimaryButton.OPEN_APP, display.primaryButton)
    }

    @Test
    fun connectionErrorIsVisible() {
        val display = StudyWidgetDisplays.of(
            idleToday.copy(issue = StudyIssue.NETWORK),
            hasUsableSession = true,
            nowMillis = NOW,
            timeZone = seoul,
        )

        assertTrue(display.statusText.contains("연결 오류"))
    }

    companion object {
        private const val NOW = 1_793_156_400_000L
    }
}
