package kr.co.studybridge.app.study

import android.content.ComponentName
import android.content.Context
import android.service.quicksettings.TileService
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyActionSource
import kr.co.studybridge.app.notification.StudyNotificationFactory
import kr.co.studybridge.app.notification.StudyNotificationIds
import kr.co.studybridge.app.notification.StudyNotificationPoster
import kr.co.studybridge.app.tile.StudyQuickSettingsTileService
import kr.co.studybridge.app.widget.StudyTimeWidgetProvider

object StudySurfaces {

    fun render(context: Context, snapshot: StudySnapshot, result: StudyActionResult, source: StudyActionSource) {
        renderSessionNotification(context, snapshot)
        renderFeedback(context, result, source)
        refreshTile(context)
        StudyTimeWidgetProvider.updateAll(context)
    }

    fun renderSnapshot(context: Context, snapshot: StudySnapshot) {
        renderSessionNotification(context, snapshot)
        refreshTile(context)
        StudyTimeWidgetProvider.updateAll(context)
    }

    fun clearAll(context: Context) {
        StudyNotificationPoster.cancel(context, StudyNotificationIds.STUDY_SESSION)
        StudyNotificationPoster.cancel(context, StudyNotificationIds.FEEDBACK)
        refreshTile(context)
        StudyTimeWidgetProvider.updateAll(context)
    }

    private fun renderSessionNotification(context: Context, snapshot: StudySnapshot) {
        val startedAt = snapshot.startedAtMillis
        if (snapshot.isStudying && startedAt != null) {
            StudyNotificationPoster.post(
                context,
                StudyNotificationIds.STUDY_SESSION,
                StudyNotificationFactory.studying(context, startedAt),
            )
        } else if (snapshot.phase != StudyPhase.UNKNOWN) {
            StudyNotificationPoster.cancel(context, StudyNotificationIds.STUDY_SESSION)
        }
    }

    private fun renderFeedback(context: Context, result: StudyActionResult, source: StudyActionSource) {
        if (source == StudyActionSource.TILE) return
        val feedback = StudyFeedback.of(result) ?: return
        StudyNotificationPoster.post(
            context,
            StudyNotificationIds.FEEDBACK,
            StudyNotificationFactory.feedback(context, context.getString(feedback.messageRes), feedback.opensApp),
        )
    }

    private fun refreshTile(context: Context) {
        TileService.requestListeningState(context, ComponentName(context, StudyQuickSettingsTileService::class.java))
    }
}

data class StudyFeedback(val messageRes: Int, val opensApp: Boolean) {
    companion object {
        fun of(result: StudyActionResult): StudyFeedback? = when (result) {
            is StudyActionResult.Stopped -> StudyFeedback(R.string.study_feedback_stopped, opensApp = false)
            StudyActionResult.NotStudying -> StudyFeedback(R.string.study_feedback_not_studying, opensApp = false)
            is StudyActionResult.GroupSessionActive -> StudyFeedback(R.string.study_feedback_group_active, opensApp = true)
            StudyActionResult.LoginRequired -> StudyFeedback(R.string.study_feedback_login_required, opensApp = true)
            StudyActionResult.NetworkUnavailable -> StudyFeedback(R.string.study_feedback_network, opensApp = false)
            StudyActionResult.ServerFailed -> StudyFeedback(R.string.study_feedback_server, opensApp = false)
            StudyActionResult.Busy -> StudyFeedback(R.string.study_feedback_busy, opensApp = false)
            is StudyActionResult.Started,
            is StudyActionResult.AlreadyStudying,
            is StudyActionResult.Refreshed -> null
        }
    }
}
