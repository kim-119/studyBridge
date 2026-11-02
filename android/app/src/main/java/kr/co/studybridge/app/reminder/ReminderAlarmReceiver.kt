package kr.co.studybridge.app.reminder

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kr.co.studybridge.app.notification.StudyIntentTarget
import kr.co.studybridge.app.notification.StudyNotificationFactory
import kr.co.studybridge.app.notification.StudyNotificationIds
import kr.co.studybridge.app.notification.StudyNotificationPoster
import kr.co.studybridge.app.notification.StudyPendingIntentIds
import kr.co.studybridge.app.study.StudyAccount

class ReminderAlarmReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val reminderId = StudyPendingIntentIds.ownerIdOf(intent.data) ?: return
        val isSnooze = when (intent.action) {
            StudyIntentTarget.REMINDER_ALARM.action -> false
            StudyIntentTarget.REMINDER_SNOOZE_ALARM.action -> true
            else -> return
        }

        val scheduler = ReminderScheduler.from(context)
        val userId = StudyAccount(context).currentUserId()
        val store = ReminderStore.from(context)
        val reminder = userId?.let { store.find(it, reminderId) }

        if (userId == null || reminder == null || !reminder.enabled) {
            scheduler.cancel(reminderId)
            return
        }

        StudyNotificationPoster.post(
            context,
            StudyNotificationIds.reminder(reminder.id),
            StudyNotificationFactory.reminder(context, reminder),
        )

        if (isSnooze) return
        if (reminder.isRepeating) {
            scheduler.scheduleAfterFiring(reminder, System.currentTimeMillis())
        } else {
            store.setEnabled(userId, reminder.id, enabled = false)
        }
    }
}
