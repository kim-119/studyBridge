package kr.co.studybridge.app.study

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class StudySessionCoordinatorTest {

    private class FakeTimerServer : StudyTimerApi {
        var active: TimerSession? = null
        var todaySeconds = 600L
        var failure: StudyApiFailure? = null
        var todayFailure: StudyApiFailure? = null
        var startCalls = 0
        var endCalls = 0
        val receivedTokens = mutableListOf<String>()
        private var nextId = 1L

        override fun currentSession(accessToken: String): TimerSession? {
            receivedTokens += accessToken
            failIfRequested()
            return active
        }

        @Synchronized
        override fun startPersonalSession(accessToken: String): TimerSession {
            failIfRequested()
            startCalls += 1
            Thread.sleep(5)
            return active ?: TimerSession(nextId++, null, NOW - 1_000, null, null).also { active = it }
        }

        override fun endSession(accessToken: String): TimerSession? {
            failIfRequested()
            endCalls += 1
            val ended = active?.copy(endedAtMillis = NOW, durationSeconds = 1L)
            active = null
            todaySeconds += 1
            return ended
        }

        override fun todayCompletedSeconds(accessToken: String): Long {
            todayFailure?.let { throw StudyApiException(it, "today failed") }
            return todaySeconds
        }

        private fun failIfRequested() {
            failure?.let { throw StudyApiException(it, "requested failure") }
        }
    }

    private class FakeCredentials(var user: AuthorizedUser?) : StudyCredentials {
        override fun authorizedUser(nowMillis: Long): AuthorizedUser? = user
    }

    private class InMemoryStatus : StudyStatusRepository {
        var snapshot = StudySnapshot.EMPTY
        override fun read(): StudySnapshot = snapshot
        override fun write(snapshot: StudySnapshot) {
            this.snapshot = snapshot
        }
    }

    private val server = FakeTimerServer()
    private val credentials = FakeCredentials(AuthorizedUser(7L, "token-7"))
    private val status = InMemoryStatus()
    private val coordinator = StudySessionCoordinator(server, credentials, status) { NOW }

    @Test
    fun startCreatesPersonalSessionAndRecordsServerStartTime() {
        val result = coordinator.start()

        assertTrue(result is StudyActionResult.Started)
        assertEquals(1, server.startCalls)
        assertEquals(StudyPhase.STUDYING, status.snapshot.phase)
        assertEquals(NOW - 1_000, status.snapshot.startedAtMillis)
        assertEquals(600L, status.snapshot.todayCompletedSeconds)
        assertEquals(StudySessionCoordinator.serverDateKey(NOW), status.snapshot.todayDateKey)
        assertEquals(StudyIssue.NONE, status.snapshot.issue)
    }

    @Test
    fun startWhileAlreadyStudyingDoesNotCreateSecondSession() {
        server.active = TimerSession(3L, null, NOW - 60_000, null, null)

        val result = coordinator.start()

        assertTrue(result is StudyActionResult.AlreadyStudying)
        assertEquals(0, server.startCalls)
        assertEquals(NOW - 60_000, status.snapshot.startedAtMillis)
    }

    @Test
    fun startDoesNotReplaceRunningGroupSession() {
        server.active = TimerSession(4L, 51L, NOW - 60_000, null, null)

        val result = coordinator.start()

        assertTrue(result is StudyActionResult.GroupSessionActive)
        assertEquals(0, server.startCalls)
        assertEquals(StudyPhase.GROUP_STUDYING, status.snapshot.phase)
    }

    @Test
    fun stopEndsPersonalSessionAndClearsStudyingState() {
        coordinator.start()

        val result = coordinator.stop()

        assertTrue(result is StudyActionResult.Stopped)
        assertEquals(1, server.endCalls)
        assertEquals(StudyPhase.IDLE, status.snapshot.phase)
        assertNull(status.snapshot.startedAtMillis)
        assertEquals(601L, status.snapshot.todayCompletedSeconds)
    }

    @Test
    fun stopNeverEndsGroupSession() {
        server.active = TimerSession(4L, 51L, NOW - 60_000, null, null)

        val result = coordinator.stop()

        assertTrue(result is StudyActionResult.GroupSessionActive)
        assertEquals(0, server.endCalls)
    }

    @Test
    fun stopWithoutSessionReportsNotStudying() {
        val result = coordinator.stop()

        assertEquals(StudyActionResult.NotStudying, result)
        assertEquals(0, server.endCalls)
        assertEquals(StudyPhase.IDLE, status.snapshot.phase)
    }

    @Test
    fun missingCredentialsNeverCallServer() {
        credentials.user = null

        val result = coordinator.start()

        assertEquals(StudyActionResult.LoginRequired, result)
        assertTrue(server.receivedTokens.isEmpty())
        assertEquals(StudyIssue.LOGIN_REQUIRED, status.snapshot.issue)
    }

    @Test
    fun rejectedTokenIsReportedAsLoginRequired() {
        server.failure = StudyApiFailure.UNAUTHORIZED

        assertEquals(StudyActionResult.LoginRequired, coordinator.start())
        assertEquals(0, server.startCalls)
        assertEquals(StudyIssue.LOGIN_REQUIRED, status.snapshot.issue)
    }

    @Test
    fun networkFailureKeepsLastConfirmedPhase() {
        coordinator.start()
        server.failure = StudyApiFailure.NETWORK

        val result = coordinator.stop()

        assertEquals(StudyActionResult.NetworkUnavailable, result)
        assertEquals(StudyPhase.STUDYING, status.snapshot.phase)
        assertEquals(StudyIssue.NETWORK, status.snapshot.issue)
    }

    @Test
    fun serverFailureIsReported() {
        server.failure = StudyApiFailure.SERVER

        assertEquals(StudyActionResult.ServerFailed, coordinator.refresh())
        assertEquals(StudyIssue.SERVER, status.snapshot.issue)
    }

    @Test
    fun refreshRestoresStateAfterAppRestart() {
        server.active = TimerSession(9L, null, NOW - 120_000, null, null)

        val result = coordinator.refresh()

        assertTrue(result is StudyActionResult.Refreshed)
        assertEquals(StudyPhase.STUDYING, status.snapshot.phase)
        assertEquals(NOW - 120_000, status.snapshot.startedAtMillis)
    }

    @Test
    fun sessionEndedElsewhereIsReflectedOnRefresh() {
        coordinator.start()
        server.active = null

        coordinator.refresh()

        assertEquals(StudyPhase.IDLE, status.snapshot.phase)
    }

    @Test
    fun todayTotalFailureDoesNotHideConfirmedSession() {
        server.todayFailure = StudyApiFailure.NETWORK

        coordinator.start()

        assertEquals(StudyPhase.STUDYING, status.snapshot.phase)
        assertNull(status.snapshot.todayCompletedSeconds)
    }

    @Test
    fun staleTodayTotalFromAnotherDayIsDropped() {
        status.snapshot = StudySnapshot.EMPTY.copy(todayCompletedSeconds = 9_999L, todayDateKey = "2000-01-01")
        server.todayFailure = StudyApiFailure.NETWORK

        coordinator.refresh()

        assertNull(status.snapshot.todayCompletedSeconds)
        assertNull(status.snapshot.todayDateKey)
    }

    @Test
    fun concurrentStartRequestsCreateOnlyOneSession() {
        val workers = Executors.newFixedThreadPool(4)
        val done = CountDownLatch(8)
        repeat(8) {
            workers.execute {
                coordinator.start()
                done.countDown()
            }
        }

        assertTrue(done.await(5, TimeUnit.SECONDS))
        workers.shutdown()
        assertEquals(1, server.startCalls)
    }

    @Test
    fun serverDateKeyUsesSeoulCalendarDay() {
        assertEquals("2026-10-28", StudySessionCoordinator.serverDateKey(SEOUL_2026_10_28_23_30))
    }

    companion object {
        private const val NOW = 1_793_156_400_000L
        private const val SEOUL_2026_10_28_23_30 = 1_793_197_800_000L
    }
}
