package kr.co.studybridge.app.tile

import kr.co.studybridge.app.study.StudyAction
import kr.co.studybridge.app.study.StudyIssue
import kr.co.studybridge.app.study.StudyPhase
import kr.co.studybridge.app.study.StudySnapshot
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StudyTileDisplaysTest {

    private val studying = StudySnapshot.EMPTY.copy(phase = StudyPhase.STUDYING, startedAtMillis = 1L)
    private val idle = StudySnapshot.EMPTY.copy(phase = StudyPhase.IDLE)

    @Test
    fun onlyServerConfirmedPersonalSessionIsShownAsStudying() {
        val display = StudyTileDisplays.of(studying, hasUsableSession = true, isWorking = false)

        assertEquals(StudyTileMode.STUDYING, display.mode)
        assertEquals("공부 중", display.label)
        assertTrue(display.isActive)
        assertEquals(StudyAction.STOP, display.clickAction)
    }

    @Test
    fun idleOrUnknownStateOffersStart() {
        listOf(idle, StudySnapshot.EMPTY).forEach { snapshot ->
            val display = StudyTileDisplays.of(snapshot, hasUsableSession = true, isWorking = false)
            assertEquals(StudyTileMode.START, display.mode)
            assertFalse(display.isActive)
            assertEquals(StudyAction.START, display.clickAction)
        }
    }

    @Test
    fun missingSessionShowsLoginRequiredAndKeepsIntendedAction() {
        val whileIdle = StudyTileDisplays.of(idle, hasUsableSession = false, isWorking = false)
        val whileStudying = StudyTileDisplays.of(studying, hasUsableSession = false, isWorking = false)

        assertEquals("로그인 필요", whileIdle.label)
        assertEquals(StudyAction.START, whileIdle.clickAction)
        assertEquals(StudyAction.STOP, whileStudying.clickAction)
        assertFalse(whileStudying.isActive)
    }

    @Test
    fun connectionErrorIsNotShownAsStudying() {
        val display = StudyTileDisplays.of(studying.copy(issue = StudyIssue.NETWORK), hasUsableSession = true, isWorking = false)

        assertEquals(StudyTileMode.CONNECTION_ERROR, display.mode)
        assertEquals("연결 오류", display.label)
        assertFalse(display.isActive)
        assertEquals(StudyAction.REFRESH, display.clickAction)
    }

    @Test
    fun groupSessionIsNotStoppedFromTile() {
        val display = StudyTileDisplays.of(idle.copy(phase = StudyPhase.GROUP_STUDYING), hasUsableSession = true, isWorking = false)

        assertEquals(StudyTileMode.GROUP_STUDYING, display.mode)
        assertEquals(StudyAction.REFRESH, display.clickAction)
    }

    @Test
    fun workingStateIgnoresClicks() {
        val display = StudyTileDisplays.of(idle, hasUsableSession = true, isWorking = true)

        assertEquals(StudyTileMode.WORKING, display.mode)
        assertNull(display.clickAction)
    }

    @Test
    fun everyModeHasSubtitle() {
        StudyTileMode.entries.forEach { mode ->
            val subtitle = StudyTileDisplays.subtitleOf(StudyTileDisplay(mode, "", false, null))
            assertTrue(subtitle.isNotBlank())
        }
    }
}
