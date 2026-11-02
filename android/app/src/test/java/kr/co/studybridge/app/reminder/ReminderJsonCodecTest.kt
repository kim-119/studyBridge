package kr.co.studybridge.app.reminder

import org.junit.Assert.assertEquals
import org.junit.Test

class ReminderJsonCodecTest {

    @Test
    fun encodeThenDecodeKeepsEveryField() {
        val reminders = listOf(
            StudyReminder(3, "영어 단어", 6, 45, setOf(ReminderDay.SATURDAY, ReminderDay.MONDAY), true, ReminderAlertStyle.SILENT),
            StudyReminder(4, "", 23, 0, emptySet(), false, ReminderAlertStyle.SOUND_ONLY),
        )

        assertEquals(reminders, ReminderJsonCodec.decode(ReminderJsonCodec.encode(reminders)))
    }

    @Test
    fun decodeSkipsEntriesWithoutIdOrTime() {
        val json = """[{"id":0,"hour":7,"minute":0},{"id":5,"hour":7},{"id":6,"hour":30,"minute":0},{"id":7,"hour":7,"minute":5}]"""

        val decoded = ReminderJsonCodec.decode(json)

        assertEquals(listOf(7), decoded.map { it.id })
        assertEquals(ReminderAlertStyle.SOUND_AND_VIBRATION, decoded.single().alertStyle)
    }

    @Test
    fun decodeIgnoresUnknownDays() {
        val json = """[{"id":1,"hour":7,"minute":0,"repeatDays":["MON","HOLIDAY"],"enabled":true}]"""

        assertEquals(setOf(ReminderDay.MONDAY), ReminderJsonCodec.decode(json).single().repeatDays)
    }

    @Test
    fun decodeOfEmptyOrBrokenTextIsEmpty() {
        assertEquals(emptyList<StudyReminder>(), ReminderJsonCodec.decode(null))
        assertEquals(emptyList<StudyReminder>(), ReminderJsonCodec.decode(""))
        assertEquals(emptyList<StudyReminder>(), ReminderJsonCodec.decode("[{"))
    }
}
