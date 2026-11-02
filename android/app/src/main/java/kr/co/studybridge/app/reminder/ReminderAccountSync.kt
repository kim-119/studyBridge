package kr.co.studybridge.app.reminder

import android.content.Context
import kr.co.studybridge.app.study.StudyAccount

object ReminderAccountSync {

    fun rescheduleForCurrentUser(context: Context): List<ScheduledReminder> {
        val userId = StudyAccount(context).currentUserId() ?: return emptyList()
        return ReminderScheduler.from(context).applyAll(ReminderStore.from(context).list(userId))
    }

    fun scheduleForSignedInUser(context: Context, previousUserId: Long?, currentUserId: Long) {
        val store = ReminderStore.from(context)
        val scheduler = ReminderScheduler.from(context)
        if (previousUserId != null && previousUserId != currentUserId) {
            scheduler.cancelAll(store.list(previousUserId))
        }
        scheduler.applyAll(store.list(currentUserId))
    }

    fun cancelForUser(context: Context, userId: Long) {
        ReminderScheduler.from(context).cancelAll(ReminderStore.from(context).list(userId))
    }
}
