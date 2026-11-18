package kr.co.studybridge.app.study

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.TimeZone

class StudyTimeTextTest {

    private val seoul = TimeZone.getTimeZone("Asia/Seoul")

    @Test
    fun studyStartLabelUsesKoreanMeridiem() {
        val seoulAfternoon = 1_793_156_400_000L + (3 * 60 + 30) * 60_000L

        assertEquals("오후 3:30", StudyTimeText.clockLabel(seoulAfternoon, seoul))
        assertEquals("15:30", StudyTimeText.clockLabel(seoulAfternoon, seoul, use24Hour = true))
    }

    @Test
    fun hourMinuteLabelSupportsTwelveAndTwentyFourHourFormats() {
        assertEquals("오전 12:05", StudyTimeText.hourMinuteLabel(0, 5, use24Hour = false))
        assertEquals("오후 12:00", StudyTimeText.hourMinuteLabel(12, 0, use24Hour = false))
        assertEquals("오후 9:30", StudyTimeText.hourMinuteLabel(21, 30, use24Hour = false))
        assertEquals("00:05", StudyTimeText.hourMinuteLabel(0, 5, use24Hour = true))
        assertEquals("21:30", StudyTimeText.hourMinuteLabel(21, 30, use24Hour = true))
    }

    @Test
    fun durationLabelRoundsDownToMinutes() {
        assertEquals("0분", StudyTimeText.durationLabel(0))
        assertEquals("1분 미만", StudyTimeText.durationLabel(59))
        assertEquals("12분", StudyTimeText.durationLabel(12 * 60 + 59))
        assertEquals("2시간", StudyTimeText.durationLabel(7200))
        assertEquals("1시간 5분", StudyTimeText.durationLabel(3900))
    }
}
