package kr.co.studybridge.app.widget

import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.ComponentName
import android.content.Context
import android.os.SystemClock
import android.view.View
import android.widget.RemoteViews
import kr.co.studybridge.app.R
import kr.co.studybridge.app.notification.StudyActionSource
import kr.co.studybridge.app.notification.StudyPendingIntents
import kr.co.studybridge.app.study.StudyAction
import kr.co.studybridge.app.study.StudyRuntime
import java.util.TimeZone

class StudyTimeWidgetProvider : AppWidgetProvider() {

    override fun onUpdate(context: Context, appWidgetManager: AppWidgetManager, appWidgetIds: IntArray) {
        render(context, appWidgetManager, appWidgetIds)
        if (!StudyRuntime.hasUsableSession(context)) return

        val pendingResult = goAsync()
        StudyRuntime.perform(context, StudyAction.REFRESH, StudyActionSource.WIDGET) {
            pendingResult.finish()
        }
    }

    companion object {

        fun updateAll(context: Context) {
            val manager = AppWidgetManager.getInstance(context) ?: return
            val ids = manager.getAppWidgetIds(ComponentName(context, StudyTimeWidgetProvider::class.java))
            if (ids.isNotEmpty()) render(context, manager, ids)
        }

        private fun render(context: Context, manager: AppWidgetManager, appWidgetIds: IntArray) {
            val now = System.currentTimeMillis()
            val display = StudyWidgetDisplays.of(
                snapshot = StudyRuntime.currentSnapshot(context),
                hasUsableSession = StudyRuntime.hasUsableSession(context),
                nowMillis = now,
                timeZone = TimeZone.getDefault(),
            )
            val views = viewsOf(context, display, now)
            appWidgetIds.forEach { manager.updateAppWidget(it, views) }
        }

        private fun viewsOf(context: Context, display: StudyWidgetDisplay, nowMillis: Long): RemoteViews {
            val views = RemoteViews(context.packageName, R.layout.widget_study_time)
            views.setTextViewText(R.id.widget_study_status, display.statusText)
            views.setTextViewText(R.id.widget_study_today, display.todayText)
            bindChronometer(views, display, nowMillis)
            bindPrimaryButton(context, views, display.primaryButton)
            views.setOnClickPendingIntent(
                R.id.widget_study_open_app,
                StudyPendingIntents.openApp(context, StudyActionSource.WIDGET),
            )
            views.setOnClickPendingIntent(
                R.id.widget_study_logo,
                StudyPendingIntents.openApp(context, StudyActionSource.WIDGET),
            )
            return views
        }

        private fun bindChronometer(views: RemoteViews, display: StudyWidgetDisplay, nowMillis: Long) {
            val startedAt = display.chronometerStartMillis
            if (!display.showsChronometer || startedAt == null) {
                views.setViewVisibility(R.id.widget_study_chronometer, View.GONE)
                views.setChronometer(R.id.widget_study_chronometer, SystemClock.elapsedRealtime(), null, false)
                return
            }
            val elapsedMillis = (nowMillis - startedAt).coerceAtLeast(0L)
            views.setViewVisibility(R.id.widget_study_chronometer, View.VISIBLE)
            views.setChronometer(R.id.widget_study_chronometer, SystemClock.elapsedRealtime() - elapsedMillis, null, true)
        }

        private fun bindPrimaryButton(context: Context, views: RemoteViews, button: WidgetPrimaryButton) {
            when (button) {
                WidgetPrimaryButton.START -> {
                    views.setViewVisibility(R.id.widget_study_primary, View.VISIBLE)
                    views.setTextViewText(R.id.widget_study_primary, context.getString(R.string.study_action_start))
                    views.setOnClickPendingIntent(
                        R.id.widget_study_primary,
                        StudyPendingIntents.startStudy(context, StudyActionSource.WIDGET),
                    )
                }
                WidgetPrimaryButton.STOP -> {
                    views.setViewVisibility(R.id.widget_study_primary, View.VISIBLE)
                    views.setTextViewText(R.id.widget_study_primary, context.getString(R.string.study_action_stop))
                    views.setOnClickPendingIntent(
                        R.id.widget_study_primary,
                        StudyPendingIntents.stopStudy(context, StudyActionSource.WIDGET),
                    )
                }
                WidgetPrimaryButton.OPEN_APP -> views.setViewVisibility(R.id.widget_study_primary, View.GONE)
            }
        }
    }
}
