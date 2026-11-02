package kr.co.studybridge.app.reminder

import java.util.Calendar
import java.util.TimeZone

object ReminderTimeCalculator {

    private const val DAYS_TO_SEARCH = 8

    fun nextTriggerMillis(reminder: StudyReminder, nowMillis: Long, timeZone: TimeZone): Long =
        findTrigger(reminder, nowMillis, timeZone, firstDayOffset = 0)

    fun nextTriggerAfterFiring(reminder: StudyReminder, firedAtMillis: Long, timeZone: TimeZone): Long =
        findTrigger(reminder, firedAtMillis, timeZone, firstDayOffset = 1)

    private fun findTrigger(
        reminder: StudyReminder,
        referenceMillis: Long,
        timeZone: TimeZone,
        firstDayOffset: Int,
    ): Long {
        for (dayOffset in firstDayOffset until firstDayOffset + DAYS_TO_SEARCH) {
            val candidate = candidateOn(reminder, referenceMillis, timeZone, dayOffset)
            val isLater = candidate.timeInMillis > referenceMillis
            if (isLater && reminder.firesOn(candidate.get(Calendar.DAY_OF_WEEK))) {
                return candidate.timeInMillis
            }
        }
        error("No trigger found for reminder ${reminder.id}")
    }

    private fun candidateOn(
        reminder: StudyReminder,
        referenceMillis: Long,
        timeZone: TimeZone,
        dayOffset: Int,
    ): Calendar {
        val day = Calendar.getInstance(timeZone).apply {
            timeInMillis = referenceMillis
            add(Calendar.DAY_OF_YEAR, dayOffset)
        }
        return Calendar.getInstance(timeZone).apply {
            clear()
            isLenient = true
            set(
                day.get(Calendar.YEAR),
                day.get(Calendar.MONTH),
                day.get(Calendar.DAY_OF_MONTH),
                reminder.hour,
                reminder.minute,
                0,
            )
        }
    }
}
