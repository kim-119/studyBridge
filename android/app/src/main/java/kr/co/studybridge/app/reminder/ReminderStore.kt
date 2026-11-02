package kr.co.studybridge.app.reminder

import android.content.Context
import android.content.SharedPreferences

interface TextStorage {
    fun read(key: String): String?
    fun write(key: String, value: String)
    fun remove(key: String)
}

class SharedPreferencesTextStorage(private val preferences: SharedPreferences) : TextStorage {

    override fun read(key: String): String? = preferences.getString(key, null)

    override fun write(key: String, value: String) {
        preferences.edit().putString(key, value).commit()
    }

    override fun remove(key: String) {
        preferences.edit().remove(key).commit()
    }
}

class ReminderStore(private val storage: TextStorage) {

    @Synchronized
    fun list(userId: Long): List<StudyReminder> =
        ReminderJsonCodec.decode(storage.read(remindersKey(userId)))
            .sortedWith(compareBy({ it.hour }, { it.minute }, { it.id }))

    @Synchronized
    fun find(userId: Long, reminderId: Int): StudyReminder? =
        list(userId).firstOrNull { it.id == reminderId }

    @Synchronized
    fun save(userId: Long, reminder: StudyReminder): StudyReminder {
        val errors = ReminderValidator.validate(reminder)
        require(errors.isEmpty()) { "Invalid reminder: $errors" }

        val existing = list(userId)
        val saved = if (reminder.id == NEW_REMINDER_ID) {
            reminder.copy(id = nextId(existing))
        } else {
            require(existing.any { it.id == reminder.id }) { "Reminder ${reminder.id} does not exist" }
            reminder
        }

        val updated = existing.filterNot { it.id == saved.id } + saved
        storage.write(remindersKey(userId), ReminderJsonCodec.encode(updated))
        return saved
    }

    @Synchronized
    fun setEnabled(userId: Long, reminderId: Int, enabled: Boolean): StudyReminder? {
        val reminder = find(userId, reminderId) ?: return null
        return save(userId, reminder.copy(enabled = enabled))
    }

    @Synchronized
    fun delete(userId: Long, reminderId: Int): Boolean {
        val existing = list(userId)
        if (existing.none { it.id == reminderId }) return false
        storage.write(remindersKey(userId), ReminderJsonCodec.encode(existing.filterNot { it.id == reminderId }))
        return true
    }

    private fun nextId(existing: List<StudyReminder>): Int {
        val lastIssued = storage.read(LAST_ISSUED_ID_KEY)?.toIntOrNull() ?: NEW_REMINDER_ID
        val nextId = maxOf(lastIssued, existing.maxOfOrNull { it.id } ?: NEW_REMINDER_ID) + 1
        storage.write(LAST_ISSUED_ID_KEY, nextId.toString())
        return nextId
    }

    private fun remindersKey(userId: Long): String = "reminders_user_$userId"

    companion object {
        private const val PREFERENCES_NAME = "studybridge_study_reminders"
        private const val LAST_ISSUED_ID_KEY = "last_issued_reminder_id"

        fun from(context: Context): ReminderStore {
            val preferences = context.applicationContext
                .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)
            return ReminderStore(SharedPreferencesTextStorage(preferences))
        }
    }
}
