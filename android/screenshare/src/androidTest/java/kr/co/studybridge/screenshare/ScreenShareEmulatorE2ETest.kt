package kr.co.studybridge.screenshare

import android.app.Activity
import android.app.ActivityManager
import android.content.Intent
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
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.FixMethodOrder
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.MethodSorters
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.regex.Pattern

/**
 * 에뮬레이터 E2E: 실제 MediaProjection 전체 디스플레이 캡처 → libwebrtc → 로컬 OpenVidu 2.30(openvidu-dev, Kurento) SCREEN 송출
 * → 다른 참가자(테스트 시청자)가 구독해 실제로 디코딩. CI 가 세션과 토큰을 만들어 계측 인자로 넘긴다(없으면 건너뜀).
 * 실기기 검증을 대신하지 않는다(실제 브라우저·게임 앱, 실제 모바일 네트워크, PC 웹/Android 앱 수신 화면은 기기에서 확인).
 */
@RunWith(AndroidJUnit4::class)
@FixMethodOrder(MethodSorters.NAME_ASCENDING)
class ScreenShareEmulatorE2ETest {

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val device = UiDevice.getInstance(instrumentation)
    private val args = InstrumentationRegistry.getArguments()
    private var viewer: OpenViduTestViewer? = null

    private val api get() = requireNotNull(args.getString("ovApi"))
    private val secret get() = requireNotNull(args.getString("ovSecret"))
    /** 시나리오마다 다른 OpenVidu 세션(토큰에 들어 있다). 마지막 참가자가 나가면 서버가 세션을 지우기 때문이다. */
    private var sessionId = ""

    /** 이번 공유를 시작한 시각. 이전 시나리오의 마지막 상태(IDLE)를 이번 결과로 오인하지 않는다. */
    private var startedAt = 0L

    @After
    fun tearDown() {
        viewer?.close()
        if (ScreenShareRuntime.status.state.isActive) runCatching { ScreenShareService.stop(context) }
        shell("cmd connectivity airplane-mode disable")
        runCatching { device.setOrientationNatural() }
        runCatching { device.unfreezeRotation() }
    }

    @Test
    fun t1_capturesPublishesAndIsReceivedAcrossAppsAndRotation() {
        val token = tokenArg("ovPublishTokenB64")
        val publishing = startSharing(token)
        val connectionId = requireNotNull(publishing.connectionId)

        // 실제 인코딩·전송(outbound-rtp)과 서버(OpenVidu) 측 SCREEN 게시
        val first = waitForStatus(20_000) { it.framesEncoded > 0 && it.bytesSent > 0 }
        log("publisher stats frames=${first.framesEncoded} bytes=${first.bytesSent}")
        val publisher = waitForServerPublisher(connectionId)
        assertEquals("SCREEN", publisher.getJSONObject("mediaOptions").getString("typeOfVideo"))
        assertTrue("OS 에 MediaProjection 이 활성이어야 한다", mediaProjectionActive())

        // 상대방 수신: 다른 참가자가 SCREEN 스트림을 구독해 실제로 디코딩한다
        val receiver = OpenViduTestViewer(context, tokenArg("ovViewerTokenB64")).also { viewer = it }
        val screen = receiver.joinAndFindScreen()
        assertEquals(connectionId, screen.connectionId)
        assertEquals("SCREEN", screen.typeOfVideo)
        receiver.subscribe(screen)
        waitFor("시청자 디코딩", 30_000) { receiver.decodedFrames.get() >= 5 }
        log("viewer decoded=${receiver.decodedFrames.get()} size=${receiver.lastFrameSize.get()}")

        // 홈 화면 → 다른 앱(설정)으로 이동해도 송출·수신 유지
        device.pressHome()
        assertStillSendingAndReceived("home", receiver)
        shell("am start -W -a android.settings.SETTINGS")
        assertStillSendingAndReceived("settings", receiver)

        // 회전 → 같은 캡처 세션에서 가로로 바뀌고, 시청자도 가로 프레임을 받는다
        device.setOrientationLeft()
        val rotated = waitForStatus(20_000) { it.width > it.height }
        log("publisher rotated ${rotated.width}x${rotated.height}")
        waitFor("시청자 가로 프레임", 30_000) {
            val (width, height) = receiver.lastFrameSize.get().split('x').map(String::toInt)
            width > height
        }
        log("viewer rotated size=${receiver.lastFrameSize.get()}")
        assertStillSendingAndReceived("rotated", receiver)
        device.setOrientationNatural()

        // 사용자 종료 → 앱·OS·서버 모두 정리
        ScreenShareService.stop(context)
        val stopped = waitForStatus(20_000, allowStop = true) { it.state == ScreenShareState.IDLE }
        assertEquals(StopReason.USER_STOPPED, stopped.reason)
        assertCleanedUp("user-stop")
        waitForServerRemoval(connectionId, 20_000)
        log("t1 stopped, OS projection released, server connection removed")
    }

    @Test
    fun t2_networkLossStopsSafelyAndReleasesResources() {
        val publishing = startSharing(tokenArg("ovNetworkTokenB64"))
        waitForStatus(20_000) { it.bytesSent > 0 }
        val connectionId = requireNotNull(publishing.connectionId)

        shell("cmd connectivity airplane-mode enable")
        val stopped = waitForStatus(60_000, allowStop = true) { it.state == ScreenShareState.IDLE }
        log("network loss -> reason=${stopped.reason} message=${stopped.message}")
        assertEquals(StopReason.NETWORK_LOST, stopped.reason)
        assertCleanedUp("network-loss")

        shell("cmd connectivity airplane-mode disable")
        SystemClock.sleep(5_000)
        // 끊긴 쪽은 서버에 알릴 수 없다. 서버가 죽은 연결을 언제 정리하는지 관찰만 남긴다(운영은 앱 복귀 시 DELETE video/screen 으로 반환).
        val removed = runCatching { waitForServerRemoval(connectionId, 60_000) }.isSuccess
        log("network loss: server connection removed within 60s after reconnect = $removed")
    }

    @Test
    fun t3_serviceDestroyedByAppCloseReleasesResources() {
        val publishing = startSharing(tokenArg("ovAppCloseTokenB64"))
        waitForStatus(20_000) { it.bytesSent > 0 }
        val connectionId = requireNotNull(publishing.connectionId)

        // 앱 작업 종료(stopWithTask)·시스템 종료와 같은 경로: Service.onDestroy
        context.stopService(Intent(context, ScreenShareService::class.java))
        val stopped = waitForStatus(20_000, allowStop = true) { it.state == ScreenShareState.IDLE }
        assertEquals(StopReason.APP_CLOSED, stopped.reason)
        assertCleanedUp("app-close")
        waitForServerRemoval(connectionId, 20_000)
        log("t3 service destroyed, OS projection released, server connection removed")
    }

    // ── 공통 ───────────────────────────────────────────────────────────────

    private fun tokenArg(name: String): String {
        val encoded = args.getString(name)
        assumeTrue("$name 이 없으면(로컬 실행) E2E 를 건너뛴다", !encoded.isNullOrBlank())
        return String(Base64.decode(encoded, Base64.DEFAULT))
    }

    /** 시스템 동의 → 앱과 같은 경로로 Foreground Service 시작 → PUBLISHING 까지. */
    private fun startSharing(token: String): ScreenShareStatus {
        sessionId = OpenViduProtocol.endpointFromToken(token, keepInsecureWebSocket = true).sessionId
        startedAt = System.currentTimeMillis()
        shell("appops set ${context.packageName} PROJECT_MEDIA allow")
        if (Build.VERSION.SDK_INT >= 33) shell("pm grant ${context.packageName} android.permission.POST_NOTIFICATIONS")
        ConsentActivity.result = CompletableFuture()
        val scenario = ActivityScenario.launch(ConsentActivity::class.java)
        val (resultCode, data) = awaitConsent()
        assertEquals("화면 녹화 동의가 승인되어야 한다", Activity.RESULT_OK, resultCode)
        ScreenShareRuntime.storeConsent(resultCode, requireNotNull(data))
        val consent = requireNotNull(ScreenShareRuntime.takeConsent())
        val config = JSONObject()
            .put("token", token)
            .put("metadata", """{"userId":"e2e","clientData":"E2E Android","kind":"SCREEN"}""")
            .put("insecureTransportForTesting", true)
            .put("maxLongSide", 1280)
            .put("frameRate", 15)
        ScreenShareService.start(context, consent, config.toString())
        val publishing = waitForStatus(60_000) { it.state == ScreenShareState.PUBLISHING }
        log("publishing connection=${publishing.connectionId} stream=${publishing.streamId} size=${publishing.width}x${publishing.height}")
        scenario.close()
        return publishing
    }

    private fun awaitConsent(): Pair<Int, Intent?> {
        val future = ConsentActivity.result
        // PROJECT_MEDIA appop 이 허용되면 동의창 없이 승인된다. 동의창이 뜨면 '전체 화면' → '시작'을 누른다.
        if (runCatching { future.get(5, TimeUnit.SECONDS) }.isSuccess) return future.get()
        device.wait(Until.findObject(By.text(Pattern.compile("(?i)(a single app|single app|앱 하나)"))), 3_000)?.let { spinner ->
            spinner.click()
            device.wait(Until.findObject(By.text(Pattern.compile("(?i)(entire screen|share entire screen|전체 화면)"))), 3_000)?.click()
        }
        device.wait(Until.findObject(By.text(Pattern.compile("(?i)(start now|start|share screen|지금 시작|시작)"))), 10_000)?.click()
        return future.get(20, TimeUnit.SECONDS)
    }

    private fun assertStillSendingAndReceived(step: String, receiver: OpenViduTestViewer) {
        val bytes = ScreenShareRuntime.status.bytesSent
        val frames = receiver.decodedFrames.get()
        val next = waitForStatus(20_000) { it.bytesSent > bytes }
        waitFor("$step 시청자 프레임 증가", 20_000) { receiver.decodedFrames.get() > frames }
        assertEquals("$step: 송출이 유지되어야 한다", ScreenShareState.PUBLISHING, next.state)
        log("$step publisher bytes $bytes -> ${next.bytesSent}, viewer frames $frames -> ${receiver.decodedFrames.get()}")
    }

    /** 앱 상태뿐 아니라 OS 에서도 정리됐는지: 서비스 종료, MediaProjection 해제. */
    private fun assertCleanedUp(step: String) {
        waitFor("$step 서비스 종료", 10_000) { !serviceRunning() }
        waitFor("$step MediaProjection 해제", 10_000) { !mediaProjectionActive() }
        assertFalse(ScreenShareRuntime.status.state.isActive)
        log("$step cleaned: service stopped, media projection released")
    }

    @Suppress("DEPRECATION")
    private fun serviceRunning(): Boolean =
        context.getSystemService(ActivityManager::class.java).getRunningServices(Int.MAX_VALUE)
            .any { it.service.className == ScreenShareService::class.java.name }

    private fun mediaProjectionActive(): Boolean = shell("dumpsys media_projection").contains(context.packageName)

    private fun waitForStatus(timeoutMs: Long, allowStop: Boolean = false, condition: (ScreenShareStatus) -> Boolean): ScreenShareStatus {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            val status = ScreenShareRuntime.status
            if (status.updatedAt < startedAt) {
                SystemClock.sleep(250)
                continue
            }
            if (condition(status)) return status
            if (!allowStop && status.state == ScreenShareState.IDLE && status.reason != null) {
                throw AssertionError("화면공유가 예기치 않게 종료됨: ${status.reason} ${status.message}")
            }
            SystemClock.sleep(250)
        }
        throw AssertionError("시간 안에 조건을 만족하지 못함. 마지막 상태=${ScreenShareRuntime.status}")
    }

    private fun waitFor(what: String, timeoutMs: Long, condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (condition()) return
            SystemClock.sleep(250)
        }
        throw AssertionError("시간 안에 확인하지 못함: $what")
    }

    private fun waitForServerPublisher(connectionId: String): JSONObject {
        val deadline = SystemClock.elapsedRealtime() + 20_000
        while (SystemClock.elapsedRealtime() < deadline) {
            val connection = serverConnections().firstOrNull { it.optString("connectionId") == connectionId }
            val publisher = connection?.optJSONArray("publishers")?.optJSONObject(0)
            if (publisher != null) {
                log("server publisher ${publisher.optString("streamId")} ${publisher.optJSONObject("mediaOptions")}")
                return publisher
            }
            SystemClock.sleep(500)
        }
        throw AssertionError("OpenVidu 가 SCREEN 게시를 보고하지 않음")
    }

    private fun waitForServerRemoval(connectionId: String, timeoutMs: Long) {
        waitFor("서버 연결 제거 $connectionId", timeoutMs) {
            serverConnections().none { it.optString("connectionId") == connectionId && it.optString("status") == "active" }
        }
    }

    private fun serverConnections(): List<JSONObject> {
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
        } catch (_: java.io.IOException) {
            emptyList()
        } finally {
            connection.disconnect()
        }
    }

    private fun shell(command: String): String {
        val descriptor = instrumentation.uiAutomation.executeShellCommand(command)
        return ParcelFileDescriptor.AutoCloseInputStream(descriptor).use { String(it.readBytes()) }
    }

    private fun log(message: String) {
        Log.i(TAG, message)
    }

    private companion object {
        const val TAG = "SBScreenShareE2E"
    }
}
