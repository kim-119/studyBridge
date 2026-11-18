package kr.co.studybridge.app.reminder

import org.json.JSONArray
import org.json.JSONObject

object ReminderJsonCodec {

    private const val FIELD_ID = "id"
    private const val FIELD_TITLE = "title"
    private const val FIELD_HOUR = "hour"
    private const val FIELD_MINUTE = "minute"
    private const val FIELD_REPEAT_DAYS = "repeatDays"
    private const val FIELD_ENABLED = "enabled"
    private const val FIELD_ALERT_STYLE = "alertStyle"

    fun encode(reminders: List<StudyReminder>): String {
        val array = JSONArray()
        reminders.forEach { array.put(encodeReminder(it)) }
        return array.toString()
    }

    fun decode(json: String?): List<StudyReminder> {
        if (json.isNullOrBlank()) return emptyList()
        val array = try {
            JSONArray(json)
        } catch (error: org.json.JSONException) {
            return emptyList()
        }
        return (0 until array.length())
            .mapNotNull { index -> array.optJSONObject(index)?.let(::decodeReminder) }
            .filter { ReminderValidator.validate(it).isEmpty() }
    }

    private fun encodeReminder(reminder: StudyReminder): JSONObject {
        val days = JSONArray()
        ReminderDay.entries
            .filter { it in reminder.repeatDays }
            .forEach { days.put(it.storageKey) }

        return JSONObject()
            .put(FIELD_ID, reminder.id)
            .put(FIELD_TITLE, reminder.title)
            .put(FIELD_HOUR, reminder.hour)
            .put(FIELD_MINUTE, reminder.minute)
            .put(FIELD_REPEAT_DAYS, days)
            .put(FIELD_ENABLED, reminder.enabled)
            .put(FIELD_ALERT_STYLE, reminder.alertStyle.storageKey)
    }

    private fun decodeReminder(json: JSONObject): StudyReminder? {
        val id = json.optInt(FIELD_ID, NEW_REMINDER_ID)
        if (id <= NEW_REMINDER_ID) return null
        if (!json.has(FIELD_HOUR) || !json.has(FIELD_MINUTE)) return null

        val daysJson = json.optJSONArray(FIELD_REPEAT_DAYS) ?: JSONArray()
        val repeatDays = (0 until daysJson.length())
            .mapNotNull { index -> ReminderDay.fromStorageKey(daysJson.optString(index)) }
            .toSet()

        return StudyReminder(
            id = id,
            title = json.optString(FIELD_TITLE, ""),
            hour = json.optInt(FIELD_HOUR, -1),
            minute = json.optInt(FIELD_MINUTE, -1),
            repeatDays = repeatDays,
            enabled = json.optBoolean(FIELD_ENABLED, false),
            alertStyle = ReminderAlertStyle.fromStorageKey(json.optString(FIELD_ALERT_STYLE)),
        )
    }
}
