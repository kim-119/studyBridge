package kr.co.studybridge.app.reminder

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar
import java.util.TimeZone

class ReminderTimeCalculatorTest {

    private val seoul = TimeZone.getTimeZone("Asia/Seoul")
    private val newYork = TimeZone.getTimeZone("America/New_York")

    private fun reminder(hour: Int, minute: Int, days: Set<ReminderDay> = emptySet()) = StudyReminder(
        id = 1,
        title = "",
        hour = hour,
        minute = minute,
        repeatDays = days,
        enabled = true,
        alertStyle = ReminderAlertStyle.SOUND_AND_VIBRATION,
    )

    private fun millis(zone: TimeZone, year: Int, month: Int, day: Int, hour: Int, minute: Int): Long =
        Calendar.getInstance(zone).apply {
            clear()
            set(year, month - 1, day, hour, minute, 0)
        }.timeInMillis

    private fun localFields(zone: TimeZone, epochMillis: Long): List<Int> {
        val calendar = Calendar.getInstance(zone).apply { timeInMillis = epochMillis }
        return listOf(
            calendar.get(Calendar.YEAR),
            calendar.get(Calendar.MONTH) + 1,
            calendar.get(Calendar.DAY_OF_MONTH),
            calendar.get(Calendar.HOUR_OF_DAY),
            calendar.get(Calendar.MINUTE),
        )
    }

    @Test
    fun oneTimeReminderFiresLaterTodayWhenTimeIsAhead() {
        val now = millis(seoul, 2026, 11, 2, 9, 0)

        val next = ReminderTimeCalculator.nextTriggerMillis(reminder(21, 30), now, seoul)

        assertEquals(listOf(2026, 11, 2, 21, 30), localFields(seoul, next))
    }

    @Test
    fun oneTimeReminderMovesToTomorrowWhenTimeHasPassedOrIsNow() {
        val now = millis(seoul, 2026, 11, 2, 21, 30)

        val next = ReminderTimeCalculator.nextTriggerMillis(reminder(21, 30), now, seoul)

        assertEquals(listOf(2026, 11, 3, 21, 30), localFields(seoul, next))
    }

    @Test
    fun repeatingReminderSkipsUnselectedDays() {
        val mondayNight = millis(seoul, 2026, 11, 2, 23, 0)
        val fridayOnly = reminder(7, 0, setOf(ReminderDay.FRIDAY))

        val next = ReminderTimeCalculator.nextTriggerMillis(fridayOnly, mondayNight, seoul)

        assertEquals(listOf(2026, 11, 6, 7, 0), localFields(seoul, next))
    }

    @Test
    fun repeatingReminderOnSameWeekdayWrapsToNextWeek() {
        val mondayAfterTime = millis(seoul, 2026, 11, 2, 8, 0)
        val mondayOnly = reminder(7, 0, setOf(ReminderDay.MONDAY))

        val next = ReminderTimeCalculator.nextTriggerMillis(mondayOnly, mondayAfterTime, seoul)

        assertEquals(listOf(2026, 11, 9, 7, 0), localFields(seoul, next))
    }

    @Test
    fun afterFiringTheNextTriggerIsNeverOnTheSameLocalDate() {
        val everyDay = reminder(7, 0, ReminderDay.entries.toSet())
        val firedAt = millis(seoul, 2026, 11, 2, 7, 0) + 1500

        val next = ReminderTimeCalculator.nextTriggerAfterFiring(everyDay, firedAt, seoul)

        assertEquals(listOf(2026, 11, 3, 7, 0), localFields(seoul, next))
    }

    @Test
    fun springForwardGapMovesReminderToFirstValidTimeThatDay() {
        val beforeGap = millis(newYork, 2026, 3, 8, 0, 0)

        val next = ReminderTimeCalculator.nextTriggerMillis(reminder(2, 30), beforeGap, newYork)

        assertEquals(listOf(2026, 3, 8, 3, 30), localFields(newYork, next))
        assertTrue(next > beforeGap)
    }

    @Test
    fun fallBackOverlapDoesNotFireTwiceOnTheSameNight() {
        val everyDay = reminder(1, 30, ReminderDay.entries.toSet())
        val evening = millis(newYork, 2026, 10, 31, 22, 0)

        val firstTrigger = ReminderTimeCalculator.nextTriggerMillis(everyDay, evening, newYork)
        val afterFirst = ReminderTimeCalculator.nextTriggerAfterFiring(everyDay, firstTrigger, newYork)

        assertEquals(listOf(2026, 11, 1, 1, 30), localFields(newYork, firstTrigger))
        assertEquals(listOf(2026, 11, 2, 1, 30), localFields(newYork, afterFirst))
    }

    @Test
    fun timeZoneChangeKeepsLocalWallClockTime() {
        val now = millis(seoul, 2026, 11, 2, 9, 0)
        val daily = reminder(20, 0, ReminderDay.entries.toSet())

        val inSeoul = ReminderTimeCalculator.nextTriggerMillis(daily, now, seoul)
        val inNewYork = ReminderTimeCalculator.nextTriggerMillis(daily, now, newYork)

        assertEquals(20, localFields(seoul, inSeoul)[3])
        assertEquals(20, localFields(newYork, inNewYork)[3])
        assertNotEquals(inSeoul, inNewYork)
    }

    @Test
    fun nextTriggerIsAlwaysWithinAWeek() {
        val now = millis(seoul, 2026, 12, 31, 23, 59)
        val sundayOnly = reminder(0, 0, setOf(ReminderDay.SUNDAY))

        val next = ReminderTimeCalculator.nextTriggerMillis(sundayOnly, now, seoul)

        assertTrue(next > now)
        assertTrue(next - now <= 7L * 24 * 60 * 60 * 1000)
        assertEquals(listOf(2027, 1, 3, 0, 0), localFields(seoul, next))
    }
}
