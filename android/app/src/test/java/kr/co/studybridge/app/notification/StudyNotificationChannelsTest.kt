package kr.co.studybridge.app.notification

import kr.co.studybridge.app.reminder.ReminderAlertStyle
import kr.co.studybridge.app.study.StudyActionResult
import kr.co.studybridge.app.study.StudyFeedback
import kr.co.studybridge.app.study.TimerSession
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StudyNotificationChannelsTest {

    @Test
    fun channelIdsAreUniqueAndDoNotReuseScreenShareChannel() {
        val ids = StudyNotificationChannels.specs.map { it.id }

        assertEquals(ids.size, ids.toSet().size)
        assertFalse(SCREEN_SHARE_CHANNEL_ID in ids)
        assertTrue(ids.all { it.startsWith("studybridge_study_") })
    }

    @Test
    fun everyAlertStyleHasItsOwnChannelMatchingSoundAndVibration() {
        val expected = mapOf(
            ReminderAlertStyle.SOUND_AND_VIBRATION to (true to true),
            ReminderAlertStyle.SOUND_ONLY to (true to false),
            ReminderAlertStyle.VIBRATION_ONLY to (false to true),
            ReminderAlertStyle.SILENT to (false to false),
        )

        expected.forEach { (style, soundAndVibration) ->
            val spec = StudyNotificationChannels.specOf(StudyNotificationChannels.reminderChannelId(style))
            assertEquals(style.name, soundAndVibration, spec.playsSound to spec.vibrates)
        }
        assertEquals(4, ReminderAlertStyle.entries.map(StudyNotificationChannels::reminderChannelId).toSet().size)
    }

    @Test
    fun sessionChannelIsQuiet() {
        val session = StudyNotificationChannels.specOf(StudyNotificationChannels.STUDY_SESSION)

        assertFalse(session.playsSound)
        assertFalse(session.vibrates)
    }

    @Test
    fun notificationIdsDoNotCollide() {
        val reminderIds = (1..500).map(StudyNotificationIds::reminder)

        assertEquals(500, reminderIds.toSet().size)
        assertFalse(StudyNotificationIds.STUDY_SESSION in reminderIds)
        assertFalse(StudyNotificationIds.FEEDBACK in reminderIds)
        assertFalse(SCREEN_SHARE_NOTIFICATION_ID in reminderIds + StudyNotificationIds.STUDY_SESSION + StudyNotificationIds.FEEDBACK)
    }

    @Test
    fun feedbackIsShownForFailuresButNotForSuccessfulStart() {
        val session = TimerSession(1L, null, 0L, null, null)

        assertNull(StudyFeedback.of(StudyActionResult.Started(session)))
        assertNull(StudyFeedback.of(StudyActionResult.AlreadyStudying(session)))
        assertTrue(StudyFeedback.of(StudyActionResult.LoginRequired)!!.opensApp)
        assertTrue(StudyFeedback.of(StudyActionResult.GroupSessionActive(session.copy(groupStudyId = 5L)))!!.opensApp)
        assertNotNull(StudyFeedback.of(StudyActionResult.NetworkUnavailable))
        assertNotNull(StudyFeedback.of(StudyActionResult.Stopped(session)))
    }

    companion object {
        private const val SCREEN_SHARE_CHANNEL_ID = "studybridge_screen_share"
        private const val SCREEN_SHARE_NOTIFICATION_ID = 0x5B5C
    }
}
