package kr.co.studybridge.app.reminder

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ReminderStoreTest {

    private class InMemoryTextStorage : TextStorage {
        val values = mutableMapOf<String, String>()
        override fun read(key: String): String? = values[key]
        override fun write(key: String, value: String) {
            values[key] = value
        }
        override fun remove(key: String) {
            values.remove(key)
        }
    }

    private val storage = InMemoryTextStorage()
    private val store = ReminderStore(storage)

    private fun draft(hour: Int, minute: Int = 0, title: String = "공부") = StudyReminder(
        id = NEW_REMINDER_ID,
        title = title,
        hour = hour,
        minute = minute,
        repeatDays = setOf(ReminderDay.TUESDAY),
        enabled = true,
        alertStyle = ReminderAlertStyle.VIBRATION_ONLY,
    )

    @Test
    fun savingNewReminderAssignsIdAndPersists() {
        val saved = store.save(USER_A, draft(hour = 21))

        assertTrue(saved.id > NEW_REMINDER_ID)
        assertEquals(listOf(saved), store.list(USER_A))
    }

    @Test
    fun remindersSurviveStoreRecreation() {
        val saved = store.save(USER_A, draft(hour = 6))

        val restored = ReminderStore(storage).list(USER_A)

        assertEquals(listOf(saved), restored)
    }

    @Test
    fun editingKeepsIdAndReplacesFields() {
        val saved = store.save(USER_A, draft(hour = 8))

        val edited = store.save(USER_A, saved.copy(hour = 9, minute = 15, repeatDays = emptySet()))

        assertEquals(saved.id, edited.id)
        assertEquals(listOf(edited), store.list(USER_A))
    }

    @Test(expected = IllegalArgumentException::class)
    fun editingUnknownReminderIsRejected() {
        store.save(USER_A, draft(hour = 8).copy(id = 999))
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidReminderIsNotStored() {
        store.save(USER_A, draft(hour = 25))
    }

    @Test
    fun deleteRemovesOnlyTargetReminder() {
        val first = store.save(USER_A, draft(hour = 7))
        val second = store.save(USER_A, draft(hour = 8))

        assertTrue(store.delete(USER_A, first.id))
        assertFalse(store.delete(USER_A, first.id))
        assertEquals(listOf(second), store.list(USER_A))
    }

    @Test
    fun setEnabledUpdatesStoredValue() {
        val saved = store.save(USER_A, draft(hour = 7))

        store.setEnabled(USER_A, saved.id, enabled = false)

        assertFalse(store.find(USER_A, saved.id)!!.enabled)
        assertNull(store.setEnabled(USER_A, 12345, enabled = true))
    }

    @Test
    fun listIsSortedByTime() {
        store.save(USER_A, draft(hour = 22))
        store.save(USER_A, draft(hour = 6, minute = 45))
        store.save(USER_A, draft(hour = 6, minute = 5))

        assertEquals(listOf(6 to 5, 6 to 45, 22 to 0), store.list(USER_A).map { it.hour to it.minute })
    }

    @Test
    fun usersDoNotSeeEachOthersRemindersAndIdsNeverCollide() {
        val forA = store.save(USER_A, draft(hour = 7))
        val forB = store.save(USER_B, draft(hour = 7))

        assertEquals(listOf(forA), store.list(USER_A))
        assertEquals(listOf(forB), store.list(USER_B))
        assertNotEquals(forA.id, forB.id)
    }

    @Test
    fun deletedIdIsNotReissued() {
        val first = store.save(USER_A, draft(hour = 7))
        store.delete(USER_A, first.id)

        val next = store.save(USER_A, draft(hour = 7))

        assertNotEquals(first.id, next.id)
    }

    @Test
    fun corruptedStorageIsTreatedAsEmpty() {
        storage.values["reminders_user_$USER_A"] = "{not json"

        assertEquals(emptyList<StudyReminder>(), store.list(USER_A))
    }

    companion object {
        private const val USER_A = 11L
        private const val USER_B = 22L
    }
}
