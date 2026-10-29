package kr.co.studybridge.screenshare

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.assertFailsWith

/** v1.6 E2E 에서 발견한 크래시(ScreenPublisher.kt:47 ClassCastException) 회귀 방지. */
class WebRtcRuntimeTest {

    @Test
    fun `Executors 팩토리 결과는 ScheduledThreadPoolExecutor 로 캐스팅할 수 없다(원래 크래시 재현)`() {
        val delegated = Executors.newSingleThreadScheduledExecutor()
        try {
            assertFailsWith<ClassCastException> { delegated as ScheduledThreadPoolExecutor }
        } finally {
            delegated.shutdownNow()
        }
    }

    @Test
    fun `송출 스케줄러는 단일 스레드에서 순서대로 실행하고 이름을 붙인다`() {
        val scheduler = WebRtcRuntime.serialScheduler("sb-test-worker")
        val order = CopyOnWriteArrayList<Int>()
        val threads = CopyOnWriteArrayList<String>()
        val done = CountDownLatch(5)
        repeat(5) { index ->
            scheduler.execute {
                order.add(index)
                threads.add(Thread.currentThread().name)
                done.countDown()
            }
        }
        assertTrue(done.await(5, TimeUnit.SECONDS))
        assertEquals(listOf(0, 1, 2, 3, 4), order.toList())
        assertEquals(setOf("sb-test-worker"), threads.toSet())
        scheduler.shutdownNow()
    }

    @Test
    fun `종료 뒤에는 남은 지연·주기 작업을 실행하지 않는다`() {
        val scheduler = WebRtcRuntime.serialScheduler("sb-test-worker")
        val ran = AtomicInteger(0)
        scheduler.schedule({ ran.incrementAndGet() }, 200, TimeUnit.MILLISECONDS)
        scheduler.scheduleWithFixedDelay({ ran.incrementAndGet() }, 200, 100, TimeUnit.MILLISECONDS)
        scheduler.shutdown()
        assertTrue(scheduler.awaitTermination(2, TimeUnit.SECONDS))
        assertEquals(0, ran.get())
    }

    @Test
    fun `취소한 작업은 큐에서 바로 지운다`() {
        val scheduler = WebRtcRuntime.serialScheduler("sb-test-worker")
        val future = scheduler.schedule({ }, 1, TimeUnit.HOURS)
        future.cancel(false)
        assertTrue(scheduler.queue.isEmpty())
        assertFalse(scheduler.isShutdown)
        scheduler.shutdownNow()
    }
}
