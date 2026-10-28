package kr.co.studybridge.screenshare

import android.app.Activity
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.display.DisplayManager
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.util.DisplayMetrics
import android.util.Log
import android.view.Display
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import androidx.core.content.IntentCompat

/**
 * 화면공유 Foreground Service(type=mediaProjection). Activity 가 일시정지·종료돼도 송출을 이어간다.
 *
 * Android 14+ 순서: 사용자 동의(createScreenCaptureIntent) → 이 서비스 startForeground(type=mediaProjection)
 * → getMediaProjection → registerCallback → createVirtualDisplay(1회). 동의 결과는 한 번만 쓴다.
 */
class ScreenShareService : Service() {

    private val mainHandler = Handler(Looper.getMainLooper())
    private var publisher: ScreenPublisher? = null
    private var displayListener: DisplayManager.DisplayListener? = null
    private var lastPublishing = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> handleStart(intent)
            ACTION_STOP -> {
                val active = publisher
                if (active != null) active.stop(StopReason.USER_STOPPED) else shutDown()
            }
            else -> shutDown()
        }
        return START_NOT_STICKY
    }

    private fun handleStart(intent: Intent) {
        if (publisher != null) {
            Log.w(TAG, "screen share already running; duplicate start ignored")
            return
        }
        // startForegroundService 후 5초 안에 startForeground 를 불러야 한다 → 다른 작업보다 먼저.
        try {
            ServiceCompat.startForeground(
                this,
                ScreenShareNotifications.NOTIFICATION_ID,
                ScreenShareNotifications.sharing(this, publishing = false),
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION else 0,
            )
        } catch (error: Exception) {
            Log.e(TAG, "startForeground failed", error)
            report(StopReason.ERROR, "화면공유 알림 서비스를 시작하지 못했습니다.")
            shutDown()
            return
        }

        val config = try {
            ScreenShareConfig.parse(intent.getStringExtra(EXTRA_CONFIG))
        } catch (error: IllegalArgumentException) {
            report(StopReason.INVALID_REQUEST, error.message)
            shutDown()
            return
        }

        val projection = obtainProjection(intent) ?: run {
            report(StopReason.PERMISSION_DENIED, null)
            shutDown()
            return
        }

        val next = ScreenPublisher(
            context = applicationContext,
            projection = projection,
            config = config,
            displaySize = ::currentDisplay,
            onStatus = ::onPublisherStatus,
            onFinished = { mainHandler.post { shutDown() } },
        )
        publisher = next
        // 시스템 '공유 중지'(상태 표시줄 칩·잠금 등)·권한 회수 → 정상 종료.
        projection.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                publisher?.stop(StopReason.PERMISSION_REVOKED)
            }
        }, mainHandler)
        watchDisplay(next)
        next.start()
    }

    private fun obtainProjection(intent: Intent): MediaProjection? {
        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val data = IntentCompat.getParcelableExtra(intent, EXTRA_RESULT_DATA, Intent::class.java) ?: return null
        if (resultCode != Activity.RESULT_OK) return null
        val manager = getSystemService(MediaProjectionManager::class.java) ?: return null
        return try {
            manager.getMediaProjection(resultCode, data)
        } catch (error: SecurityException) {
            Log.w(TAG, "media projection consent rejected", error)
            null
        } catch (error: IllegalStateException) {
            Log.w(TAG, "media projection consent already used", error)
            null
        }
    }

    private fun onPublisherStatus(status: ScreenShareStatus) {
        ScreenShareRuntime.publish(status)
        val publishing = status.state == ScreenShareState.PUBLISHING
        if (publishing != lastPublishing && status.state.isActive) {
            lastPublishing = publishing
            mainHandler.post { refreshNotification(publishing) }
        }
    }

    private fun refreshNotification(publishing: Boolean) {
        if (publisher == null) return
        val manager = getSystemService(NotificationManager::class.java) ?: return
        runCatching {
            manager.notify(ScreenShareNotifications.NOTIFICATION_ID, ScreenShareNotifications.sharing(this, publishing))
        }
    }

    /** 회전·해상도 변경(폴더블 펼침 등) 감지 → 같은 캡처 세션에서 크기만 바꾼다. */
    private fun watchDisplay(target: ScreenPublisher) {
        val manager = getSystemService(DisplayManager::class.java) ?: return
        val listener = object : DisplayManager.DisplayListener {
            override fun onDisplayAdded(displayId: Int) = Unit
            override fun onDisplayRemoved(displayId: Int) = Unit
            override fun onDisplayChanged(displayId: Int) {
                if (displayId == Display.DEFAULT_DISPLAY) target.onDisplayChanged()
            }
        }
        manager.registerDisplayListener(listener, mainHandler)
        displayListener = listener
    }

    private fun currentDisplay(): ScreenPublisher.DisplayInfo {
        val display = getSystemService(DisplayManager::class.java)?.getDisplay(Display.DEFAULT_DISPLAY)
        val metrics = DisplayMetrics()
        if (display != null) {
            @Suppress("DEPRECATION")
            display.getRealMetrics(metrics)
        } else {
            metrics.setTo(resources.displayMetrics)
        }
        return ScreenPublisher.DisplayInfo(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi)
    }

    private fun report(reason: StopReason, message: String?) {
        ScreenShareRuntime.publish(ScreenShareStatus(ScreenShareState.IDLE, reason = reason, message = message))
    }

    private fun shutDown() {
        displayListener?.let { getSystemService(DisplayManager::class.java)?.unregisterDisplayListener(it) }
        displayListener = null
        publisher = null
        lastPublishing = false
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        publisher?.stop(StopReason.APP_CLOSED)
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        // 시스템이 서비스를 끝낸 경우에도 캡처·연결을 남기지 않는다(이미 종료됐으면 무시된다).
        publisher?.stop(StopReason.APP_CLOSED)
        displayListener?.let { getSystemService(DisplayManager::class.java)?.unregisterDisplayListener(it) }
        displayListener = null
        super.onDestroy()
    }

    companion object {
        private const val TAG = "SBScreenShareService"
        const val ACTION_START = "kr.co.studybridge.screenshare.START"
        const val ACTION_STOP = "kr.co.studybridge.screenshare.STOP"
        private const val EXTRA_RESULT_CODE = "resultCode"
        private const val EXTRA_RESULT_DATA = "resultData"
        private const val EXTRA_CONFIG = "config"

        internal fun start(context: Context, consent: ScreenShareRuntime.Consent, configJson: String) {
            val intent = Intent(context, ScreenShareService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_RESULT_CODE, consent.resultCode)
                .putExtra(EXTRA_RESULT_DATA, consent.data)
                .putExtra(EXTRA_CONFIG, configJson)
            ContextCompat.startForegroundService(context, intent)
        }

        internal fun stop(context: Context) {
            context.startService(Intent(context, ScreenShareService::class.java).setAction(ACTION_STOP))
        }
    }
}
