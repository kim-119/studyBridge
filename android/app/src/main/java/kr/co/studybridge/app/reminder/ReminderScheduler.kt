package kr.co.studybridge.app.reminder

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.os.Build
import kr.co.studybridge.app.notification.StudyPendingIntents
import java.util.TimeZone

enum class ReminderPrecision {
    EXACT,
    INEXACT,
}

data class ScheduledReminder(val reminderId: Int, val triggerAtMillis: Long, val precision: ReminderPrecision)

class ReminderScheduler(
    private val context: Context,
    private val clock: () -> Long = System::currentTimeMillis,
    private val timeZone: () -> TimeZone = TimeZone::getDefault,
) {

    private val alarmManager: AlarmManager? = context.getSystemService(AlarmManager::class.java)
    private val canceller = ReminderCanceller(context)

    fun canScheduleExactAlarms(): Boolean {
        val manager = alarmManager ?: return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        return manager.canScheduleExactAlarms()
    }

    fun apply(reminder: StudyReminder): ScheduledReminder? {
        if (!reminder.enabled) {
            canceller.cancelScheduledAlarms(reminder.id)
            return null
        }
        val triggerAt = ReminderTimeCalculator.nextTriggerMillis(reminder, clock(), timeZone())
        return scheduleAt(reminder.id, triggerAt, StudyPendingIntents.reminderAlarm(context, reminder.id))
    }

    fun scheduleAfterFiring(reminder: StudyReminder, firedAtMillis: Long): ScheduledReminder? {
        if (!reminder.enabled || !reminder.isRepeating) return null
        val triggerAt = ReminderTimeCalculator.nextTriggerAfterFiring(reminder, firedAtMillis, timeZone())
        return scheduleAt(reminder.id, triggerAt, StudyPendingIntents.reminderAlarm(context, reminder.id))
    }

    fun scheduleSnooze(reminderId: Int): ScheduledReminder? {
        val triggerAt = clock() + SNOOZE_DELAY_MS
        return scheduleAt(reminderId, triggerAt, StudyPendingIntents.reminderSnoozeAlarm(context, reminderId))
    }

    fun cancel(reminderId: Int) {
        canceller.cancelEverything(reminderId)
    }

    fun applyAll(reminders: List<StudyReminder>): List<ScheduledReminder> =
        reminders.mapNotNull(::apply)

    fun cancelAll(reminders: List<StudyReminder>) {
        reminders.forEach { cancel(it.id) }
    }

    private fun scheduleAt(reminderId: Int, triggerAtMillis: Long, operation: PendingIntent): ScheduledReminder? {
        val manager = alarmManager ?: return null
        val precision = if (canScheduleExactAlarms()) ReminderPrecision.EXACT else ReminderPrecision.INEXACT

        return try {
            if (precision == ReminderPrecision.EXACT) {
                manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAtMillis, operation)
            } else {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAtMillis, operation)
            }
            ScheduledReminder(reminderId, triggerAtMillis, precision)
        } catch (error: SecurityException) {
            manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, triggerAtMillis, operation)
            ScheduledReminder(reminderId, triggerAtMillis, ReminderPrecision.INEXACT)
        }
    }

    companion object {
        const val SNOOZE_DELAY_MS = 10 * 60 * 1000L

        fun from(context: Context): ReminderScheduler = ReminderScheduler(context.applicationContext)
    }
}
