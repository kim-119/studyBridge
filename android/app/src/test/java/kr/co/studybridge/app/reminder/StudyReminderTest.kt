package kr.co.studybridge.app.reminder

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar

class StudyReminderTest {

    private val weekdayReminder = StudyReminder(
        id = 1,
        title = "  ",
        hour = 7,
        minute = 30,
        repeatDays = setOf(ReminderDay.MONDAY, ReminderDay.WEDNESDAY),
        enabled = true,
        alertStyle = ReminderAlertStyle.SOUND_ONLY,
    )

    @Test
    fun repeatingReminderFiresOnlyOnSelectedDays() {
        assertTrue(weekdayReminder.isRepeating)
        assertTrue(weekdayReminder.firesOn(Calendar.MONDAY))
        assertTrue(weekdayReminder.firesOn(Calendar.WEDNESDAY))
        assertFalse(weekdayReminder.firesOn(Calendar.SUNDAY))
    }

    @Test
    fun oneTimeReminderFiresOnAnyDay() {
        val oneTime = weekdayReminder.copy(repeatDays = emptySet())
        assertFalse(oneTime.isRepeating)
        Calendar.SUNDAY.rangeTo(Calendar.SATURDAY).forEach { assertTrue(oneTime.firesOn(it)) }
    }

    @Test
    fun blankTitleFallsBackToDefaultMessage() {
        assertEquals(DEFAULT_REMINDER_TITLE, weekdayReminder.displayTitle)
        assertEquals("수학", weekdayReminder.copy(title = " 수학 ").displayTitle)
    }

    @Test
    fun validatorRejectsOutOfRangeTimeAndLongTitle() {
        assertEquals(emptyList<ReminderValidationError>(), ReminderValidator.validate(weekdayReminder))
        assertEquals(listOf(ReminderValidationError.HOUR_OUT_OF_RANGE), ReminderValidator.validate(weekdayReminder.copy(hour = 24)))
        assertEquals(listOf(ReminderValidationError.MINUTE_OUT_OF_RANGE), ReminderValidator.validate(weekdayReminder.copy(minute = -1)))
        assertEquals(
            listOf(ReminderValidationError.TITLE_TOO_LONG),
            ReminderValidator.validate(weekdayReminder.copy(title = "가".repeat(MAX_REMINDER_TITLE_LENGTH + 1))),
        )
    }

    @Test
    fun calendarDaysMapToReminderDaysOneToOne() {
        val mapped = ReminderDay.entries.map { ReminderDay.fromCalendarDay(it.calendarDay) }
        assertEquals(ReminderDay.entries, mapped)
        assertEquals(7, ReminderDay.entries.map { it.storageKey }.toSet().size)
    }

    @Test
    fun unknownAlertStyleFallsBackToSoundAndVibration() {
        assertEquals(ReminderAlertStyle.SOUND_AND_VIBRATION, ReminderAlertStyle.fromStorageKey("LOUD"))
        assertEquals(ReminderAlertStyle.SILENT, ReminderAlertStyle.fromStorageKey("SILENT"))
    }
}
