package kr.co.studybridge.app.reminder

import android.app.AlarmManager
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.Uri
import kr.co.studybridge.app.notification.PendingIntentIdentity
import kr.co.studybridge.app.notification.StudyIntentTarget
import kr.co.studybridge.app.notification.StudyNotificationIds
import kr.co.studybridge.app.notification.StudyPendingIntentIds

class ReminderCanceller(private val context: Context) {

    private val alarmManager: AlarmManager? = context.getSystemService(AlarmManager::class.java)
    private val notificationManager: NotificationManager? = context.getSystemService(NotificationManager::class.java)

    fun cancelScheduledAlarms(reminderId: Int): Int =
        StudyPendingIntentIds.reminderAlarmIdentities(reminderId).count(::cancelIfRegistered)

    fun cancelSnooze(reminderId: Int): Boolean =
        cancelIfRegistered(
            StudyPendingIntentIds.reminderAlarmIdentities(reminderId)
                .first { it.action == StudyIntentTarget.REMINDER_SNOOZE_ALARM.action },
        )

    fun cancelEverything(reminderId: Int) {
        cancelScheduledAlarms(reminderId)
        notificationManager?.cancel(StudyNotificationIds.reminder(reminderId))
    }

    private fun cancelIfRegistered(identity: PendingIntentIdentity): Boolean {
        val intent = Intent(context, ReminderAlarmReceiver::class.java)
            .setAction(identity.action)
            .setData(Uri.parse(identity.dataUri))
            .setPackage(context.packageName)
        val registered = PendingIntent.getBroadcast(
            context,
            identity.requestCode,
            intent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_NO_CREATE,
        ) ?: return false

        alarmManager?.cancel(registered)
        registered.cancel()
        return true
    }
}
