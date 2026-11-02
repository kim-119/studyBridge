package kr.co.studybridge.app.notification

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kr.co.studybridge.app.reminder.ReminderScheduler
import kr.co.studybridge.app.study.StudyAction
import kr.co.studybridge.app.study.StudyRuntime

class StudyActionReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val ownerId = StudyPendingIntentIds.ownerIdOf(intent.data) ?: StudyPendingIntents.NO_OWNER
        val source = StudyPendingIntentIds.sourceOf(intent.data)

        when (intent.action) {
            StudyIntentTarget.START_STUDY.action -> runStudyAction(context, StudyAction.START, source, ownerId)
            StudyIntentTarget.STOP_STUDY.action -> runStudyAction(context, StudyAction.STOP, source, ownerId)
            StudyIntentTarget.SNOOZE_REMINDER.action -> snoozeReminder(context, ownerId)
        }
    }

    private fun runStudyAction(context: Context, action: StudyAction, source: StudyActionSource, ownerId: Int) {
        if (source == StudyActionSource.REMINDER && ownerId != StudyPendingIntents.NO_OWNER) {
            StudyNotificationPoster.cancel(context, StudyNotificationIds.reminder(ownerId))
        }
        val pendingResult = goAsync()
        StudyRuntime.perform(context, action, source) { pendingResult.finish() }
    }

    private fun snoozeReminder(context: Context, reminderId: Int) {
        if (reminderId == StudyPendingIntents.NO_OWNER) return
        StudyNotificationPoster.cancel(context, StudyNotificationIds.reminder(reminderId))
        ReminderScheduler.from(context).scheduleSnooze(reminderId)
    }
}
