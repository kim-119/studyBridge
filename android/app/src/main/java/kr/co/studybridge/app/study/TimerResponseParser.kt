package kr.co.studybridge.app.study

import org.json.JSONArray
import org.json.JSONObject
import java.util.Calendar
import java.util.TimeZone

object TimerResponseParser {

    val SERVER_TIME_ZONE: TimeZone = TimeZone.getTimeZone("Asia/Seoul")

    private val LOCAL_DATE_TIME = Regex("""^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?$""")

    fun parseSession(body: String?): TimerSession? {
        if (body.isNullOrBlank()) return null
        val json = JSONObject(body)
        val startedAt = parseServerDateTime(json.opt("startTime")) ?: return null
        return TimerSession(
            id = optLong(json, "id"),
            groupStudyId = optLong(json, "groupStudyId"),
            startedAtMillis = startedAt,
            endedAtMillis = parseServerDateTime(json.opt("endTime")),
            durationSeconds = optLong(json, "durationSeconds"),
        )
    }

    fun parseTodaySeconds(body: String?): Long {
        if (body.isNullOrBlank()) return 0L
        return optLong(JSONObject(body), "todaySeconds") ?: 0L
    }

    fun parseServerDateTime(value: Any?): Long? = when (value) {
        null, JSONObject.NULL -> null
        is Number -> value.toLong()
        is JSONArray -> parseDateTimeArray(value)
        is String -> parseDateTimeText(value)
        else -> null
    }

    private fun parseDateTimeText(text: String): Long? {
        val match = LOCAL_DATE_TIME.matchEntire(text.trim()) ?: return null
        val parts = match.groupValues
        val millis = parts[7].take(3).padEnd(3, '0').toInt()
        return seoulMillis(
            year = parts[1].toInt(),
            month = parts[2].toInt(),
            day = parts[3].toInt(),
            hour = parts[4].toInt(),
            minute = parts[5].toInt(),
            second = parts[6].ifEmpty { "0" }.toInt(),
            millis = millis,
        )
    }

    private fun parseDateTimeArray(array: JSONArray): Long? {
        if (array.length() < 5) return null
        return seoulMillis(
            year = array.optInt(0),
            month = array.optInt(1),
            day = array.optInt(2),
            hour = array.optInt(3),
            minute = array.optInt(4),
            second = array.optInt(5, 0),
            millis = 0,
        )
    }

    private fun seoulMillis(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int, millis: Int): Long =
        Calendar.getInstance(SERVER_TIME_ZONE).apply {
            clear()
            set(year, month - 1, day, hour, minute, second)
            set(Calendar.MILLISECOND, millis)
        }.timeInMillis

    private fun optLong(json: JSONObject, field: String): Long? {
        if (!json.has(field) || json.isNull(field)) return null
        return when (val value = json.get(field)) {
            is Number -> value.toLong()
            is String -> value.toLongOrNull()
            else -> null
        }
    }
}
