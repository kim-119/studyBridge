package kr.co.studybridge.app.notification

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.annotation.RequiresApi
import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.ReminderAlertStyle

data class StudyChannelSpec(
    val id: String,
    val nameRes: Int,
    val descriptionRes: Int,
    val importance: Int,
    val playsSound: Boolean,
    val vibrates: Boolean,
)

object StudyNotificationChannels {

    const val STUDY_SESSION = "studybridge_study_session"
    const val REMINDER_SOUND_AND_VIBRATION = "studybridge_study_reminder_sound_vibration"
    const val REMINDER_SOUND_ONLY = "studybridge_study_reminder_sound"
    const val REMINDER_VIBRATION_ONLY = "studybridge_study_reminder_vibration"
    const val REMINDER_SILENT = "studybridge_study_reminder_silent"

    private const val IMPORTANCE_LOW = 2
    private const val IMPORTANCE_HIGH = 4

    val specs: List<StudyChannelSpec> = listOf(
        StudyChannelSpec(STUDY_SESSION, R.string.study_channel_session_name, R.string.study_channel_session_description, IMPORTANCE_LOW, playsSound = false, vibrates = false),
        StudyChannelSpec(REMINDER_SOUND_AND_VIBRATION, R.string.study_channel_reminder_sound_vibration_name, R.string.study_channel_reminder_description, IMPORTANCE_HIGH, playsSound = true, vibrates = true),
        StudyChannelSpec(REMINDER_SOUND_ONLY, R.string.study_channel_reminder_sound_name, R.string.study_channel_reminder_description, IMPORTANCE_HIGH, playsSound = true, vibrates = false),
        StudyChannelSpec(REMINDER_VIBRATION_ONLY, R.string.study_channel_reminder_vibration_name, R.string.study_channel_reminder_description, IMPORTANCE_HIGH, playsSound = false, vibrates = true),
        StudyChannelSpec(REMINDER_SILENT, R.string.study_channel_reminder_silent_name, R.string.study_channel_reminder_description, IMPORTANCE_LOW, playsSound = false, vibrates = false),
    )

    fun reminderChannelId(style: ReminderAlertStyle): String = when (style) {
        ReminderAlertStyle.SOUND_AND_VIBRATION -> REMINDER_SOUND_AND_VIBRATION
        ReminderAlertStyle.SOUND_ONLY -> REMINDER_SOUND_ONLY
        ReminderAlertStyle.VIBRATION_ONLY -> REMINDER_VIBRATION_ONLY
        ReminderAlertStyle.SILENT -> REMINDER_SILENT
    }

    fun specOf(channelId: String): StudyChannelSpec = specs.first { it.id == channelId }

    fun registerAll(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        specs.forEach { spec -> manager.createNotificationChannel(channelOf(context, spec)) }
    }

    @RequiresApi(Build.VERSION_CODES.O)
    private fun channelOf(context: Context, spec: StudyChannelSpec): NotificationChannel {
        val importance = if (spec.importance == IMPORTANCE_HIGH) {
            NotificationManager.IMPORTANCE_HIGH
        } else {
            NotificationManager.IMPORTANCE_LOW
        }
        return NotificationChannel(spec.id, context.getString(spec.nameRes), importance).apply {
            description = context.getString(spec.descriptionRes)
            enableVibration(spec.vibrates)
            if (!spec.playsSound) setSound(null, null)
            setShowBadge(spec.id != STUDY_SESSION)
        }
    }
}

object StudyNotificationIds {
    const val STUDY_SESSION = 0x5D01
    const val FEEDBACK = 0x5D02
    private const val REMINDER_BASE = 0x5E0000

    fun reminder(reminderId: Int): Int = REMINDER_BASE + reminderId
}
