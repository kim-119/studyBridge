package kr.co.studybridge.app.study

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

object StudyTimeText {

    private const val SECONDS_PER_MINUTE = 60L
    private const val MINUTES_PER_HOUR = 60L

    fun clockLabel(epochMillis: Long, timeZone: TimeZone, use24Hour: Boolean = false): String {
        val pattern = if (use24Hour) "HH:mm" else "a h:mm"
        val format = SimpleDateFormat(pattern, Locale.KOREAN)
        format.timeZone = timeZone
        return format.format(Date(epochMillis))
    }

    fun hourMinuteLabel(hour: Int, minute: Int, use24Hour: Boolean): String {
        if (use24Hour) return String.format(Locale.KOREAN, "%02d:%02d", hour, minute)
        val period = if (hour < 12) "오전" else "오후"
        val displayHour = when (val hourOfHalfDay = hour % 12) {
            0 -> 12
            else -> hourOfHalfDay
        }
        return String.format(Locale.KOREAN, "%s %d:%02d", period, displayHour, minute)
    }

    fun dateTimeLabel(epochMillis: Long, timeZone: TimeZone): String {
        val format = SimpleDateFormat("M월 d일 (E) a h:mm", Locale.KOREAN)
        format.timeZone = timeZone
        return format.format(Date(epochMillis))
    }

    fun durationLabel(totalSeconds: Long): String {
        val totalMinutes = totalSeconds.coerceAtLeast(0) / SECONDS_PER_MINUTE
        val hours = totalMinutes / MINUTES_PER_HOUR
        val minutes = totalMinutes % MINUTES_PER_HOUR
        return when {
            totalSeconds <= 0L -> "0분"
            totalMinutes == 0L -> "1분 미만"
            hours == 0L -> "${minutes}분"
            minutes == 0L -> "${hours}시간"
            else -> "${hours}시간 ${minutes}분"
        }
    }
}
