package kr.co.studybridge.app.notification

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import kr.co.studybridge.app.R
import kr.co.studybridge.app.reminder.StudyReminder
import kr.co.studybridge.app.study.StudyTimeText
import java.util.TimeZone

data class StudyNotificationContent(
    val channelId: String,
    val title: String,
    val text: String,
    val priority: Int,
    val smallIconRes: Int = R.drawable.ic_stat_study,
)

object StudyNotificationFactory {

    private const val FEEDBACK_TIMEOUT_MS = 20_000L

    fun basic(context: Context, content: StudyNotificationContent): NotificationCompat.Builder {
        val spec = StudyNotificationChannels.specOf(content.channelId)
        return NotificationCompat.Builder(context, content.channelId)
            .setSmallIcon(content.smallIconRes)
            .setContentTitle(content.title)
            .setContentText(content.text)
            .setPriority(content.priority)
            .setDefaults(legacyDefaultsOf(spec))
            .setOnlyAlertOnce(true)
    }

    fun studying(context: Context, startedAtMillis: Long): Notification {
        val startLabel = StudyTimeText.clockLabel(startedAtMillis, TimeZone.getDefault())
        val content = StudyNotificationContent(
            channelId = StudyNotificationChannels.STUDY_SESSION,
            title = context.getString(R.string.app_name),
            text = context.getString(R.string.study_notification_studying_text, startLabel),
            priority = NotificationCompat.PRIORITY_LOW,
        )
        return basic(context, content)
            .setSubText(context.getString(R.string.study_notification_studying_subtext))
            .setWhen(startedAtMillis)
            .setShowWhen(true)
            .setUsesChronometer(true)
            .setOngoing(true)
            .setCategory(NotificationCompat.CATEGORY_PROGRESS)
            .setContentIntent(StudyPendingIntents.openApp(context, StudyActionSource.NOTIFICATION))
            .addAction(
                R.drawable.ic_stat_study,
                context.getString(R.string.study_action_stop),
                StudyPendingIntents.stopStudy(context, StudyActionSource.NOTIFICATION),
            )
            .addAction(
                R.drawable.ic_stat_study,
                context.getString(R.string.study_action_open_app),
                StudyPendingIntents.openApp(context, StudyActionSource.NOTIFICATION),
            )
            .build()
    }

    fun feedback(context: Context, text: String, opensApp: Boolean): Notification {
        val content = StudyNotificationContent(
            channelId = StudyNotificationChannels.STUDY_SESSION,
            title = context.getString(R.string.app_name),
            text = text,
            priority = NotificationCompat.PRIORITY_LOW,
        )
        val builder = basic(context, content)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .setTimeoutAfter(FEEDBACK_TIMEOUT_MS)
        if (opensApp) {
            builder.setContentIntent(StudyPendingIntents.openApp(context, StudyActionSource.NOTIFICATION))
        }
        return builder.build()
    }

    fun reminder(context: Context, reminder: StudyReminder): Notification {
        val content = StudyNotificationContent(
            channelId = StudyNotificationChannels.reminderChannelId(reminder.alertStyle),
            title = reminder.displayTitle,
            text = context.getString(R.string.study_notification_reminder_text),
            priority = NotificationCompat.PRIORITY_HIGH,
        )
        return basic(context, content)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(StudyPendingIntents.openApp(context, StudyActionSource.REMINDER, reminder.id))
            .addAction(
                R.drawable.ic_stat_study,
                context.getString(R.string.study_action_start),
                StudyPendingIntents.startStudy(context, StudyActionSource.REMINDER, reminder.id),
            )
            .addAction(
                R.drawable.ic_stat_study,
                context.getString(R.string.study_action_snooze),
                StudyPendingIntents.snoozeReminder(context, reminder.id),
            )
            .addAction(
                R.drawable.ic_stat_study,
                context.getString(R.string.study_action_open_app),
                StudyPendingIntents.openApp(context, StudyActionSource.REMINDER, reminder.id),
            )
            .build()
    }

    private fun legacyDefaultsOf(spec: StudyChannelSpec): Int {
        var defaults = 0
        if (spec.playsSound) defaults = defaults or NotificationCompat.DEFAULT_SOUND
        if (spec.vibrates) defaults = defaults or NotificationCompat.DEFAULT_VIBRATE
        return defaults
    }
}

object StudyNotificationPoster {

    fun canPost(context: Context): Boolean {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) return false
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) return true
        return ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED
    }

    fun post(context: Context, notificationId: Int, notification: Notification): Boolean {
        if (!canPost(context)) return false
        StudyNotificationChannels.registerAll(context)
        val manager = context.getSystemService(NotificationManager::class.java) ?: return false
        return try {
            manager.notify(notificationId, notification)
            true
        } catch (error: SecurityException) {
            false
        }
    }

    fun cancel(context: Context, notificationId: Int) {
        context.getSystemService(NotificationManager::class.java)?.cancel(notificationId)
    }
}
