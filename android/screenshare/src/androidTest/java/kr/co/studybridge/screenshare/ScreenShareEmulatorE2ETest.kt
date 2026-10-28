package kr.co.studybridge.screenshare

import android.app.Activity
import android.os.Build
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/**
 * 에뮬레이터 E2E: 실제 MediaProjection 전체 디스플레이 캡처 → libwebrtc → 로컬 OpenVidu 2.30(openvidu-dev, Kurento) SCREEN 송출.
 * CI 가 세션·SCREEN 토큰을 만들어 계측 인자(ovToken/ovApi/ovSecret/ovSession)로 넘긴다. 인자가 없으면 건너뛴다.
 * 실기기 검증을 대신하지 않는다(브라우저·게임 등 실제 앱, 실제 네트워크·PC/Android 수신 화면은 기기에서 확인).
 */
@RunWith(AndroidJUnit4::class)
class ScreenShareEmulatorE2ETest {

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val device = UiDevice.getInstance(instrumentation)
    private val args = InstrumentationRegistry.getArguments()

    @After
    fun tearDown() {
        if (ScreenShareRuntime.status.state.isActive) runCatching { ScreenShareService.stop(context) }
        runCatching { device.setOrientationNatural() }
        runCatching { device.unfreezeRotation() }
    }

    @Test
    fun capturesWholeDisplayPublishesScreenAndKeepsSharingAcrossApps() {
        val encodedToken = args.getString("ovTokenB64")
        assumeTrue("OpenVidu 토큰이 없으면(로컬 실행) E2E 를 건너뛴다", !encodedToken.isNullOrBlank())
        val token = String(Base64.decode(encodedToken, Base64.DEFAULT))
        val api = requireNotNull(args.getString("ovApi"))
        val secret = requireNotNull(args.getString("ovSecret"))
        val sessionId = requireNotNull(args.getString("ovSession"))

        shell("appops set ${context.packageName} PROJECT_MEDIA allow")
        if (Build.VERSION.SDK_INT >= 33) shell("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS")

        // 1) 시스템 화면 녹화 동의(전체 화면)
        ConsentActivity.result = CompletableFuture()
        val scenario = ActivityScenario.launch(ConsentActivity::class.java)
        val (resultCode, data) = awaitConsent()
        assertEquals("화면 녹화 동의가 승인되어야 한다", Activity.RESULT_OK, resultCode)
        ScreenShareRuntime.storeConsent(resultCode, requireNotNull(data))
        val consent = requireNotNull(ScreenShareRuntime.takeConsent())

        // 2) 앱과 같은 경로로 Foreground Service 시작(동의 → startForeground(mediaProjection) → getMediaProjection)
        val config = JSONObject()
            .put("token", token)
            .put("metadata", """{"userId":"e2e","clientData":"E2E Android","kind":"SCREEN"}""")
            .put("insecureTransportForTesting", true)
            .put("maxLongSide", 1280)
            .put("frameRate", 15)
        ScreenShareService.start(context, consent, config.toString())

        val publishing = waitForStatus(60_000) { it.state == ScreenShareState.PUBLISHING }
        log("publishing connection=${publishing.connectionId} stream=${publishing.streamId} size=${publishing.width}x${publishing.height}")
        val connectionId = requireNotNull(publishing.connectionId)

        // 3) 실제로 인코딩·전송되는지(outbound-rtp)
        val first = waitForStatus(20_000) { it.framesEncoded > 0 && it.bytesSent > 0 }
        log("first stats frames=${first.framesEncoded} bytes=${first.bytesSent}")

        // 4) 서버(OpenVidu)가 이 연결의 SCREEN 영상 게시를 알고 있는지
        val publisher = waitForServer(api, secret, sessionId, connectionId)
        assertEquals("SCREEN", publisher.getJSONObject("mediaOptions").getString("typeOfVideo"))
        assertTrue(publisher.getJSONObject("mediaOptions").getBoolean("hasVideo"))

        scenario.close()

        // 5) 홈 화면으로 나가도 송출 유지
        device.pressHome()
        assertStillSending("home", first.bytesSent)

        // 6) 다른 앱(설정)으로 이동해도 송출 유지
        shell("am start -W -a android.settings.SETTINGS")
        val afterHome = ScreenShareRuntime.status.bytesSent
        assertStillSending("settings", afterHome)

        // 7) 화면 회전 → 같은 캡처 세션에서 가로 크기로 바뀌고 송출 유지
        device.setOrientationLeft()
        val rotated = waitForStatus(20_000) { it.width > it.height && it.state == ScreenShareState.PUBLISHING }
        log("rotated ${rotated.width}x${rotated.height}")
        assertStillSending("rotated", rotated.bytesSent)
        device.setOrientationNatural()

        // 8) 사용자 종료 → 리소스 정리 + 서버 연결 제거(슬롯 반환)
        ScreenShareService.stop(context)
        val stopped = waitForStatus(20_000) { it.state == ScreenShareState.IDLE }
        assertEquals(StopReason.USER_STOPPED, stopped.reason)
        waitForServerRemoval(api, secret, sessionId, connectionId)
        log("stopped and removed from server")
    }

    private fun awaitConsent(): Pair<Int, android.content.Intent?> {
        val future = ConsentActivity.result
        // PROJECT_MEDIA appop 이 허용되면 동의창 없이 승인된다. 동의창이 뜨는 OS 버전이면 '전체 화면' → '시작'을 누른다.
        if (runCatching { future.get(5, TimeUnit.SECONDS) }.isSuccess) return future.get()
        device.wait(Until.findObject(By.text(Pattern.compile("(?i)(a single app|single app|앱 하나)"))), 3_000)?.let { spinner ->
            spinner.click()
            device.wait(Until.findObject(By.text(Pattern.compile("(?i)(entire screen|share entire screen|전체 화면)"))), 3_000)?.click()
        }
        device.wait(Until.findObject(By.text(Pattern.compile("(?i)(start now|start|share screen|지금 시작|시작)"))), 10_000)?.click()
        return future.get(20, TimeUnit.SECONDS)
    }

    private fun assertStillSending(step: String, previousBytes: Long) {
        val next = waitForStatus(20_000) { it.bytesSent > previousBytes }
        assertEquals("$step: 송출이 유지되어야 한다", ScreenShareState.PUBLISHING, next.state)
        log("$step bytes ${previousBytes} -> ${next.bytesSent} frames=${next.framesEncoded} fps=${next.framesPerSecond}")
    }

    private fun waitForStatus(timeoutMs: Long, condition: (ScreenShareStatus) -> Boolean): ScreenShareStatus {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val status = ScreenShareRuntime.status
            if (condition(status)) return status
            if (status.state == ScreenShareState.IDLE && status.reason != null && status.reason != StopReason.USER_STOPPED) {
                throw AssertionError("화면공유가 예기치 않게 종료됨: ${status.reason} ${status.message}")
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("시간 안에 조건을 만족하지 못함. 마지막 상태=${ScreenShareRuntime.status}")
    }

    private fun waitForServer(api: String, secret: String, sessionId: String, connectionId: String): JSONObject {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (SystemClock.elapsedRealtime() < deadline) {
            val connection = serverConnections(api, secret, sessionId).firstOrNull { it.optString("connectionId") == connectionId }
            val publisher = connection?.optJSONArray("publishers")?.optJSONObject(0)
            if (publisher != null) {
                log("server publisher ${publisher.optString("streamId")} ${publisher.optJSONObject("mediaOptions")}")
                return publisher
            }
            SystemClock.sleep(500)
        }
        throw AssertionError("OpenVidu 가 SCREEN 게시를 보고하지 않음")
    }

    private fun waitForServerRemoval(api: String, secret: String, sessionId: String, connectionId: String) {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (SystemClock.elapsedRealtime() < deadline) {
            val active = serverConnections(api, secret, sessionId).any {
                it.optString("connectionId") == connectionId && it.optString("status") == "active"
            }
            if (!active) return
            SystemClock.sleep(500)
        }
        throw AssertionError("종료 후에도 서버에 SCREEN 연결이 남아 있음")
    }

    private fun serverConnections(api: String, secret: String, sessionId: String): List<JSONObject> {
        val connection = URL("$api/openvidu/api/sessions/$sessionId").openConnection() as HttpURLConnection
        val credentials = Base64.encodeToString("OPENVIDUAPP:$secret".toByteArray(), Base64.NO_WRAP)
        connection.setRequestProperty("Authorization", "Basic $credentials")
        connection.connectTimeout = 5_000
        connection.readTimeout = 5_000
        return try {
            if (connection.responseCode != 200) return emptyList()
            val body = JSONObject(connection.inputStream.bufferedReader().readText())
            val content = body.getJSONObject("connections").getJSONArray("content")
            (0 until content.length()).map { content.getJSONObject(it) }
        } finally {
            connection.disconnect()
        }
    }

    private fun shell(command: String) {
        val descriptor = instrumentation.uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { it.readBytes() }
    }

    private fun log(message: String) {
        Log.i(TAG, message)
    }

    private companion object {
        const val TAG = "SBScreenShareE2E"
    }
}
