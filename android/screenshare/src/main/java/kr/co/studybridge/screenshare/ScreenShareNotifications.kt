package kr.co.studybridge.screenshare

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat

/** 공유 중임을 항상 보여주는 Foreground Service 알림. '공유 중지' 버튼으로 앱을 열지 않고도 끝낼 수 있다. */
internal object ScreenShareNotifications {
    const val NOTIFICATION_ID = 0x5B5C
    private const val CHANNEL_ID = "studybridge_screen_share"

    fun sharing(context: Context, publishing: Boolean): Notification {
        ensureChannel(context)
        val stopIntent = PendingIntent.getService(
            context,
            1,
            Intent(context, ScreenShareService::class.java).setAction(ScreenShareService.ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val openApp = context.packageManager.getLaunchIntentForPackage(context.packageName)?.let {
            PendingIntent.getActivity(context, 2, it, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }

        return NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_stat_screen_share)
            .setContentTitle(context.getString(R.string.screen_share_notification_title))
            .setContentText(
                context.getString(
                    if (publishing) R.string.screen_share_notification_publishing else R.string.screen_share_notification_connecting,
                ),
            )
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
            .setContentIntent(openApp)
            .addAction(0, context.getString(R.string.screen_share_notification_stop), stopIntent)
            .build()
    }

    private fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        if (manager.getNotificationChannel(CHANNEL_ID) != null) return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                context.getString(R.string.screen_share_channel_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply { description = context.getString(R.string.screen_share_channel_description) },
        )
    }
}
