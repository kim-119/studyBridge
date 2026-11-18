package kr.co.studybridge.app.notification

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import kr.co.studybridge.app.MainActivity
import kr.co.studybridge.app.reminder.ReminderAlarmReceiver

enum class StudyIntentTarget(val action: String, val path: String, val requestCodeBase: Int) {
    REMINDER_ALARM("kr.co.studybridge.app.action.REMINDER_ALARM", "reminder-alarm", 100_000),
    REMINDER_SNOOZE_ALARM("kr.co.studybridge.app.action.REMINDER_SNOOZE_ALARM", "reminder-snooze-alarm", 200_000),
    START_STUDY("kr.co.studybridge.app.action.START_STUDY", "start-study", 300_000),
    STOP_STUDY("kr.co.studybridge.app.action.STOP_STUDY", "stop-study", 400_000),
    SNOOZE_REMINDER("kr.co.studybridge.app.action.SNOOZE_REMINDER", "snooze-reminder", 500_000),
    OPEN_APP("kr.co.studybridge.app.action.OPEN_APP", "open-app", 600_000),
}

enum class StudyActionSource(val key: String) {
    NOTIFICATION("notification"),
    REMINDER("reminder"),
    WIDGET("widget"),
    TILE("tile");

    companion object {
        fun fromKey(key: String?): StudyActionSource =
            entries.firstOrNull { it.key == key } ?: NOTIFICATION
    }
}

data class PendingIntentIdentity(
    val action: String,
    val dataUri: String,
    val requestCode: Int,
)

object StudyPendingIntentIds {

    private const val URI_SCHEME = "studybridge"
    private const val URI_HOST = "native"
    private const val MAX_OWNER_ID = 99_999

    fun identity(target: StudyIntentTarget, ownerId: Int, source: StudyActionSource): PendingIntentIdentity {
        require(ownerId in 0..MAX_OWNER_ID) { "ownerId out of range: $ownerId" }
        return PendingIntentIdentity(
            action = target.action,
            dataUri = "$URI_SCHEME://$URI_HOST/${target.path}/${source.key}/$ownerId",
            requestCode = target.requestCodeBase + ownerId,
        )
    }

    fun reminderAlarmIdentities(reminderId: Int): List<PendingIntentIdentity> = listOf(
        identity(StudyIntentTarget.REMINDER_ALARM, reminderId, StudyActionSource.REMINDER),
        identity(StudyIntentTarget.REMINDER_SNOOZE_ALARM, reminderId, StudyActionSource.REMINDER),
    )

    fun ownerIdOf(dataUri: Uri?): Int? = dataUri?.lastPathSegment?.toIntOrNull()

    fun sourceOf(dataUri: Uri?): StudyActionSource {
        val segments = dataUri?.pathSegments.orEmpty()
        return StudyActionSource.fromKey(segments.getOrNull(segments.size - 2))
    }
}

object StudyPendingIntents {

    const val NO_OWNER = 0
    private const val IMMUTABLE_UPDATE = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT

    fun reminderAlarm(context: Context, reminderId: Int): PendingIntent =
        broadcast(context, ReminderAlarmReceiver::class.java, StudyIntentTarget.REMINDER_ALARM, reminderId, StudyActionSource.REMINDER)

    fun reminderSnoozeAlarm(context: Context, reminderId: Int): PendingIntent =
        broadcast(context, ReminderAlarmReceiver::class.java, StudyIntentTarget.REMINDER_SNOOZE_ALARM, reminderId, StudyActionSource.REMINDER)

    fun startStudy(context: Context, source: StudyActionSource, ownerId: Int = NO_OWNER): PendingIntent =
        broadcast(context, StudyActionReceiver::class.java, StudyIntentTarget.START_STUDY, ownerId, source)

    fun stopStudy(context: Context, source: StudyActionSource, ownerId: Int = NO_OWNER): PendingIntent =
        broadcast(context, StudyActionReceiver::class.java, StudyIntentTarget.STOP_STUDY, ownerId, source)

    fun snoozeReminder(context: Context, reminderId: Int): PendingIntent =
        broadcast(context, StudyActionReceiver::class.java, StudyIntentTarget.SNOOZE_REMINDER, reminderId, StudyActionSource.NOTIFICATION)

    fun openApp(context: Context, source: StudyActionSource, ownerId: Int = NO_OWNER): PendingIntent {
        val identity = StudyPendingIntentIds.identity(StudyIntentTarget.OPEN_APP, ownerId, source)
        val intent = Intent(context, MainActivity::class.java)
            .setAction(identity.action)
            .setData(Uri.parse(identity.dataUri))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        return PendingIntent.getActivity(context, identity.requestCode, intent, IMMUTABLE_UPDATE)
    }

    private fun broadcast(
        context: Context,
        receiver: Class<*>,
        target: StudyIntentTarget,
        ownerId: Int,
        source: StudyActionSource,
    ): PendingIntent {
        val identity = StudyPendingIntentIds.identity(target, ownerId, source)
        return PendingIntent.getBroadcast(context, identity.requestCode, explicitIntent(context, receiver, identity), IMMUTABLE_UPDATE)
    }

    private fun explicitIntent(context: Context, receiver: Class<*>, identity: PendingIntentIdentity): Intent =
        Intent(context, receiver)
            .setAction(identity.action)
            .setData(Uri.parse(identity.dataUri))
            .setPackage(context.packageName)
}
