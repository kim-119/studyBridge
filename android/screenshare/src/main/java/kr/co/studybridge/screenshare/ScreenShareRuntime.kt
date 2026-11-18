package kr.co.studybridge.screenshare

import android.content.Intent
import android.os.SystemClock
import java.util.concurrent.CopyOnWriteArraySet

/**
 * 프로세스 안에서 플러그인(WebView 브리지)과 Foreground Service 가 공유하는 상태.
 * Activity 가 일시정지·재생성돼도 서비스의 송출 상태를 다시 읽을 수 있다.
 */
internal object ScreenShareRuntime {
    /** MediaProjection 동의 결과는 1회용이며 오래 들고 있지 않는다(Android 14+ 재사용 금지). */
    private const val CONSENT_TTL_MS = 2 * 60 * 1000L

    class Consent(val resultCode: Int, val data: Intent, val grantedAt: Long = SystemClock.elapsedRealtime())

    @Volatile
    var status: ScreenShareStatus = ScreenShareStatus.IDLE
        private set

    private val listeners = CopyOnWriteArraySet<(ScreenShareStatus) -> Unit>()

    @Volatile
    private var consent: Consent? = null

    fun publish(next: ScreenShareStatus) {
        status = next
        listeners.forEach { listener -> runCatching { listener(next) } }
    }

    fun addListener(listener: (ScreenShareStatus) -> Unit) {
        listeners.add(listener)
    }

    fun removeListener(listener: (ScreenShareStatus) -> Unit) {
        listeners.remove(listener)
    }

    fun storeConsent(resultCode: Int, data: Intent) {
        consent = Consent(resultCode, data)
    }

    /** 동의를 꺼내면서 지운다. 시간이 지난 동의는 쓰지 않는다. */
    fun takeConsent(): Consent? {
        val current = consent
        consent = null
        if (current == null) return null
        return if (SystemClock.elapsedRealtime() - current.grantedAt <= CONSENT_TTL_MS) current else null
    }

    fun discardConsent() {
        consent = null
    }

    fun hasConsent(): Boolean {
        val current = consent ?: return false
        return SystemClock.elapsedRealtime() - current.grantedAt <= CONSENT_TTL_MS
    }
}
