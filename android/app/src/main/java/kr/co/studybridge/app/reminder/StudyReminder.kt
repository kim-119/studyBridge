package kr.co.studybridge.app.reminder

import java.util.Calendar

const val NEW_REMINDER_ID = 0
const val DEFAULT_REMINDER_TITLE = "공부할 시간이에요"
const val MAX_REMINDER_TITLE_LENGTH = 40

enum class ReminderDay(val calendarDay: Int, val storageKey: String, val shortLabel: String) {
    MONDAY(Calendar.MONDAY, "MON", "월"),
    TUESDAY(Calendar.TUESDAY, "TUE", "화"),
    WEDNESDAY(Calendar.WEDNESDAY, "WED", "수"),
    THURSDAY(Calendar.THURSDAY, "THU", "목"),
    FRIDAY(Calendar.FRIDAY, "FRI", "금"),
    SATURDAY(Calendar.SATURDAY, "SAT", "토"),
    SUNDAY(Calendar.SUNDAY, "SUN", "일");

    companion object {
        fun fromCalendarDay(calendarDay: Int): ReminderDay =
            entries.first { it.calendarDay == calendarDay }

        fun fromStorageKey(storageKey: String): ReminderDay? =
            entries.firstOrNull { it.storageKey == storageKey }
    }
}

enum class ReminderAlertStyle(val storageKey: String) {
    SOUND_AND_VIBRATION("SOUND_AND_VIBRATION"),
    SOUND_ONLY("SOUND_ONLY"),
    VIBRATION_ONLY("VIBRATION_ONLY"),
    SILENT("SILENT");

    companion object {
        fun fromStorageKey(storageKey: String?): ReminderAlertStyle =
            entries.firstOrNull { it.storageKey == storageKey } ?: SOUND_AND_VIBRATION
    }
}

data class StudyReminder(
    val id: Int,
    val title: String,
    val hour: Int,
    val minute: Int,
    val repeatDays: Set<ReminderDay>,
    val enabled: Boolean,
    val alertStyle: ReminderAlertStyle,
) {
    val isRepeating: Boolean get() = repeatDays.isNotEmpty()

    val displayTitle: String get() = title.trim().ifEmpty { DEFAULT_REMINDER_TITLE }

    fun firesOn(calendarDay: Int): Boolean =
        !isRepeating || ReminderDay.fromCalendarDay(calendarDay) in repeatDays
}

enum class ReminderValidationError {
    HOUR_OUT_OF_RANGE,
    MINUTE_OUT_OF_RANGE,
    TITLE_TOO_LONG,
}

object ReminderValidator {

    fun validate(reminder: StudyReminder): List<ReminderValidationError> {
        val errors = mutableListOf<ReminderValidationError>()
        if (reminder.hour !in 0..23) errors += ReminderValidationError.HOUR_OUT_OF_RANGE
        if (reminder.minute !in 0..59) errors += ReminderValidationError.MINUTE_OUT_OF_RANGE
        if (reminder.title.trim().length > MAX_REMINDER_TITLE_LENGTH) {
            errors += ReminderValidationError.TITLE_TOO_LONG
        }
        return errors
    }
}
