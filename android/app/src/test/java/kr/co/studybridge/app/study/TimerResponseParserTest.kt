package kr.co.studybridge.app.study

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TimerResponseParserTest {

    private val seoulNoon = 1_793_156_400_000L

    @Test
    fun serverLocalDateTimeIsReadAsSeoulTime() {
        assertEquals(seoulNoon, TimerResponseParser.parseServerDateTime("2026-10-28T12:00:00"))
        assertEquals(seoulNoon + 500, TimerResponseParser.parseServerDateTime("2026-10-28T12:00:00.5"))
        assertEquals(seoulNoon, TimerResponseParser.parseServerDateTime("2026-10-28T12:00"))
        assertEquals(seoulNoon, TimerResponseParser.parseServerDateTime(org.json.JSONArray("[2026,10,28,12,0,0]")))
        assertNull(TimerResponseParser.parseServerDateTime("not a date"))
        assertNull(TimerResponseParser.parseServerDateTime(null))
    }

    @Test
    fun activePersonalSessionIsParsed() {
        val session = TimerResponseParser.parseSession(
            """{"id":91,"userId":3,"groupStudyId":null,"startTime":"2026-10-28T12:00:00","endTime":null,"status":"STARTED","lastHeartbeatAt":null}""",
        )!!

        assertEquals(91L, session.id)
        assertEquals(seoulNoon, session.startedAtMillis)
        assertTrue(session.isActive)
        assertTrue(session.isPersonal)
    }

    @Test
    fun groupAndEndedSessionsAreDistinguished() {
        val group = TimerResponseParser.parseSession("""{"id":5,"groupStudyId":44,"startTime":"2026-10-28T12:00:00"}""")!!
        val ended = TimerResponseParser.parseSession(
            """{"id":6,"startTime":"2026-10-28T12:00:00","endTime":"2026-10-28T12:30:00","durationSeconds":1800}""",
        )!!

        assertFalse(group.isPersonal)
        assertEquals(44L, group.groupStudyId)
        assertFalse(ended.isActive)
        assertEquals(1800L, ended.durationSeconds)
    }

    @Test
    fun emptyBodyMeansNoSession() {
        assertNull(TimerResponseParser.parseSession(null))
        assertNull(TimerResponseParser.parseSession(""))
        assertNull(TimerResponseParser.parseSession("""{"id":1}"""))
    }

    @Test
    fun todaySecondsDefaultsToZero() {
        assertEquals(4200L, TimerResponseParser.parseTodaySeconds("""{"userId":3,"todaySeconds":4200}"""))
        assertEquals(0L, TimerResponseParser.parseTodaySeconds("""{"userId":3}"""))
        assertEquals(0L, TimerResponseParser.parseTodaySeconds(null))
    }
}
