package kr.co.studybridge.app.study

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import kr.co.studybridge.app.notification.StudyActionSource

class StudyRestartReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action !in RESTART_ACTIONS) return
        if (!StudyRuntime.hasUsableSession(context)) return

        val pendingResult = goAsync()
        StudyRuntime.perform(context, StudyAction.REFRESH, StudyActionSource.NOTIFICATION) {
            pendingResult.finish()
        }
    }

    companion object {
        val RESTART_ACTIONS = setOf(
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
        )
    }
}
