package kr.co.studybridge.app.ui

import android.app.StatusBarManager
import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.text.format.DateFormat
import androidx.annotation.RequiresApi
import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.ReminderDay
import kr.co.studybridge.app.reminder.ReminderPrecision
import kr.co.studybridge.app.reminder.ScheduledReminder
import kr.co.studybridge.app.reminder.StudyReminder
import kr.co.studybridge.app.study.StudyTimeText
import java.util.TimeZone

object ReminderMessages {

    fun scheduled(context: Context, scheduled: ScheduledReminder): String {
        val whenText = StudyTimeText.dateTimeLabel(scheduled.triggerAtMillis, TimeZone.getDefault())
        val messageRes = when (scheduled.precision) {
            ReminderPrecision.EXACT -> R.string.reminder_scheduled_exact
            ReminderPrecision.INEXACT -> R.string.reminder_scheduled_inexact
        }
        return context.getString(messageRes, whenText)
    }

    fun repeatLabel(reminder: StudyReminder): String = repeatLabel(reminder.repeatDays)

    fun repeatLabel(days: Set<ReminderDay>): String = when {
        days.isEmpty() -> "한 번만"
        days.size == ReminderDay.entries.size -> "매일"
        days == WEEKDAYS -> "평일"
        days == WEEKEND -> "주말"
        else -> ReminderDay.entries.filter { it in days }.joinToString(" ") { it.shortLabel }
    }

    @RequiresApi(Build.VERSION_CODES.TIRAMISU)
    fun tileRequestResult(context: Context, result: Int): String = when (result) {
        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> context.getString(R.string.reminder_tile_added)
        StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> context.getString(R.string.reminder_tile_already_added)
        else -> context.getString(R.string.reminder_tile_not_added)
    }

    private val WEEKDAYS = setOf(
        ReminderDay.MONDAY,
        ReminderDay.TUESDAY,
        ReminderDay.WEDNESDAY,
        ReminderDay.THURSDAY,
        ReminderDay.FRIDAY,
    )
    private val WEEKEND = setOf(ReminderDay.SATURDAY, ReminderDay.SUNDAY)
}

class ReminderDisplayPreferences(
    private val preferences: SharedPreferences,
    private val systemUses24Hour: Boolean,
) {

    fun uses24Hour(): Boolean = preferences.getBoolean(USE_24_HOUR_KEY, systemUses24Hour)

    fun setUses24Hour(enabled: Boolean) {
        preferences.edit().putBoolean(USE_24_HOUR_KEY, enabled).apply()
    }

    companion object {
        private const val PREFERENCES_NAME = "studybridge_reminder_display"
        private const val USE_24_HOUR_KEY = "use_24_hour"

        fun from(context: Context): ReminderDisplayPreferences = ReminderDisplayPreferences(
            context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE),
            DateFormat.is24HourFormat(context),
        )
    }
}
