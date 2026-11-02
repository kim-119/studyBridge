package kr.co.studybridge.app.ui

import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.ReminderAlertStyle
import kr.co.studybridge.app.reminder.ReminderDay
import org.junit.Assert.assertEquals
import org.junit.Test

class ReminderFormTest {

    @Test
    fun repeatLabelSummarizesSelectedDays() {
        assertEquals("한 번만", ReminderMessages.repeatLabel(emptySet()))
        assertEquals("매일", ReminderMessages.repeatLabel(ReminderDay.entries.toSet()))
        assertEquals(
            "평일",
            ReminderMessages.repeatLabel(
                setOf(ReminderDay.MONDAY, ReminderDay.TUESDAY, ReminderDay.WEDNESDAY, ReminderDay.THURSDAY, ReminderDay.FRIDAY),
            ),
        )
        assertEquals("주말", ReminderMessages.repeatLabel(setOf(ReminderDay.SUNDAY, ReminderDay.SATURDAY)))
        assertEquals("월 수 일", ReminderMessages.repeatLabel(setOf(ReminderDay.SUNDAY, ReminderDay.WEDNESDAY, ReminderDay.MONDAY)))
    }

    @Test
    fun alertStyleRadioMappingRoundTrips() {
        ReminderAlertStyle.entries.forEach { style ->
            assertEquals(style, ReminderAlertStyleOptions.styleOf(ReminderAlertStyleOptions.radioIdOf(style)))
        }
        assertEquals(4, ReminderAlertStyle.entries.map(ReminderAlertStyleOptions::radioIdOf).toSet().size)
    }

    @Test
    fun unknownRadioSelectionFallsBackToSoundAndVibration() {
        assertEquals(ReminderAlertStyle.SOUND_AND_VIBRATION, ReminderAlertStyleOptions.styleOf(-1))
        assertEquals(ReminderAlertStyle.SILENT, ReminderAlertStyleOptions.styleOf(R.id.reminder_alert_silent))
    }
}
