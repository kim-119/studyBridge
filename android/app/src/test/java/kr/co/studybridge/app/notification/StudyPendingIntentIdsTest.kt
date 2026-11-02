package kr.co.studybridge.app.notification

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class StudyPendingIntentIdsTest {

    @Test
    fun everyTargetAndOwnerProducesDistinctIdentity() {
        val identities = StudyIntentTarget.entries.flatMap { target ->
            listOf(0, 1, 2, 10, 11, 99_999).map { owner ->
                StudyPendingIntentIds.identity(target, owner, StudyActionSource.REMINDER)
            }
        }

        assertEquals(identities.size, identities.map { it.dataUri }.toSet().size)
        assertEquals(identities.size, identities.map { it.requestCode }.toSet().size)
    }

    @Test
    fun sourceIsPartOfIdentitySoWidgetAndNotificationIntentsDoNotOverwriteEachOther() {
        val widget = StudyPendingIntentIds.identity(StudyIntentTarget.START_STUDY, 0, StudyActionSource.WIDGET)
        val notification = StudyPendingIntentIds.identity(StudyIntentTarget.START_STUDY, 0, StudyActionSource.NOTIFICATION)

        assertEquals(widget.action, notification.action)
        assertNotEquals(widget.dataUri, notification.dataUri)
    }

    @Test
    fun identityEndsWithOwnerIdAndKeepsSourceBeforeIt() {
        val identity = StudyPendingIntentIds.identity(StudyIntentTarget.SNOOZE_REMINDER, 42, StudyActionSource.NOTIFICATION)

        assertTrue(identity.dataUri.endsWith("/notification/42"))
        assertEquals(StudyIntentTarget.SNOOZE_REMINDER.action, identity.action)
    }

    @Test(expected = IllegalArgumentException::class)
    fun ownerIdOutsideRangeIsRejected() {
        StudyPendingIntentIds.identity(StudyIntentTarget.REMINDER_ALARM, 100_000, StudyActionSource.REMINDER)
    }

    @Test
    fun cancellationTargetsOnlyAlarmsOfTheGivenReminder() {
        val reminderThree = StudyPendingIntentIds.reminderAlarmIdentities(3)
        val otherReminders = listOf(13, 30, 33).flatMap { StudyPendingIntentIds.reminderAlarmIdentities(it) }

        assertEquals(
            setOf(StudyIntentTarget.REMINDER_ALARM.action, StudyIntentTarget.REMINDER_SNOOZE_ALARM.action),
            reminderThree.map { it.action }.toSet(),
        )
        assertTrue(reminderThree.none { candidate -> otherReminders.any { it.dataUri == candidate.dataUri } })
        assertTrue(reminderThree.none { candidate -> otherReminders.any { it.requestCode == candidate.requestCode } })
    }

    @Test
    fun actionSourceKeysRoundTrip() {
        StudyActionSource.entries.forEach { assertEquals(it, StudyActionSource.fromKey(it.key)) }
        assertEquals(StudyActionSource.NOTIFICATION, StudyActionSource.fromKey("unknown"))
    }
}
