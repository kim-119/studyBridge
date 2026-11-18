package kr.co.studybridge.screenshare

import android.content.Context
import org.webrtc.PeerConnectionFactory
import java.util.concurrent.ScheduledThreadPoolExecutor

internal object WebRtcRuntime {

    @Volatile
    private var initialized = false

    /** PeerConnectionFactory.initialize 는 프로세스당 한 번만 한다(송출·테스트 수신기가 함께 쓴다). */
    @Synchronized
    fun ensureInitialized(context: Context) {
        if (initialized) return
        PeerConnectionFactory.initialize(
            PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions(),
        )
        initialized = true
    }

    /**
     * 송출 작업을 순서대로 처리하는 단일 스레드 스케줄러.
     * Executors.newSingleThreadScheduledExecutor() 는 DelegatedScheduledExecutorService 래퍼를 돌려주므로
     * ScheduledThreadPoolExecutor 로 캐스팅하면 ClassCastException 이 난다 → 생성자로 직접 만든다.
     * 종료(shutdown) 뒤에는 남은 지연·주기 작업을 실행하지 않고, 취소된 작업은 큐에서 바로 지운다.
     */
    fun serialScheduler(threadName: String): ScheduledThreadPoolExecutor =
        ScheduledThreadPoolExecutor(1) { runnable -> Thread(runnable, threadName) }.apply {
            executeExistingDelayedTasksAfterShutdownPolicy = false
            continueExistingPeriodicTasksAfterShutdownPolicy = false
            removeOnCancelPolicy = true
        }
}
