package kr.co.studybridge.screenshare

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.test.assertFailsWith

class ScreenShareModelTest {

    private val token = "wss://studybridge.co.kr?sessionId=group_study_51&token=tok_1"

    @Test
    fun `설정은 범위를 벗어난 값을 안전한 범위로 자른다`() {
        val config = ScreenShareConfig.parse(
            JSONObject()
                .put("token", token)
                .put("connectionId", "con_screen")
                .put("maxSendKbps", 99_999)
                .put("maxLongSide", 100)
                .put("frameRate", 120)
                .toString(),
        )
        assertEquals(4000, config.maxSendKbps)
        assertEquals(640, config.maxLongSide)
        assertEquals(30, config.frameRate)
        assertEquals("con_screen", config.expectedConnectionId)
        assertEquals("group_study_51", config.endpoint.sessionId)
    }

    @Test
    fun `값이 없으면 기본값(15fps, 긴 변 1280, 2500kbps)을 쓴다`() {
        val config = ScreenShareConfig.parse(JSONObject().put("token", token).toString())
        assertEquals(15, config.frameRate)
        assertEquals(1280, config.maxLongSide)
        assertEquals(2500, config.maxSendKbps)
        assertTrue(config.iceServers.isEmpty())
    }

    @Test
    fun `토큰이 없거나 잘못되면 시작하지 않는다`() {
        assertFailsWith<IllegalArgumentException> { ScreenShareConfig.parse("{}") }
        assertFailsWith<IllegalArgumentException> { ScreenShareConfig.parse("not json") }
        assertFailsWith<IllegalArgumentException> { ScreenShareConfig.parse(JSONObject().put("token", "tok_only").toString()) }
        assertFailsWith<IllegalArgumentException> {
            ScreenShareConfig.parse(JSONObject().put("token", token).put("metadata", "x".repeat(1001)).toString())
        }
    }

    @Test
    fun `송출 크기는 방향을 유지하고 긴 변만 줄이며 16 배수로 맞춘다`() {
        assertEquals(CaptureSize(576, 1280), CaptureSize.fit(1080, 2400, 1280))
        assertEquals(CaptureSize(1280, 576), CaptureSize.fit(2400, 1080, 1280))
        assertEquals(CaptureSize(720, 1280), CaptureSize.fit(720, 1280, 1280))
        assertEquals(CaptureSize(1280, 800), CaptureSize.fit(2560, 1600, 1280))
        assertFailsWith<IllegalArgumentException> { CaptureSize.fit(0, 100, 1280) }
    }

    @Test
    fun `회전 값으로 방향을 정하고 늦게 갱신된 크기를 바로잡는다`() {
        // 세로가 자연 방향인 폰(320x640): 90° 회전인데 metrics 가 아직 세로면 가로로 바꾼다.
        assertEquals(640 to 320, orientDisplaySize(320, 640, 320, 640, 1))
        assertEquals(640 to 320, orientDisplaySize(640, 320, 320, 640, 3))
        assertEquals(320 to 640, orientDisplaySize(640, 320, 320, 640, 0))
        assertEquals(320 to 640, orientDisplaySize(320, 640, 320, 640, 2))
        // 가로가 자연 방향인 태블릿(2560x1600): 90° 회전이면 세로
        assertEquals(1600 to 2560, orientDisplaySize(2560, 1600, 2560, 1600, 1))
        assertEquals(2560 to 1600, orientDisplaySize(2560, 1600, 2560, 1600, 0))
        // 해상도 배율로 physical 과 logical 이 달라도 방향만 본다
        assertEquals(720 to 1600, orientDisplaySize(720, 1600, 1080, 2400, 0))
        assertEquals(1600 to 720, orientDisplaySize(720, 1600, 1080, 2400, 1))
        // 정보가 없으면 그대로
        assertEquals(500 to 900, orientDisplaySize(500, 900, 0, 0, 1))
    }

    @Test
    fun `정상 흐름 IDLE → STARTING → CONNECTING → PUBLISHING → STOPPING → IDLE`() {
        val machine = ScreenShareStateMachine()
        assertTrue(machine.begin())
        assertFalse("중복 시작 거부", machine.begin())
        assertTrue(machine.connecting(576, 1280))
        assertTrue(machine.publishing("con_screen", "str_1"))
        assertEquals(ScreenShareState.PUBLISHING, machine.current.state)
        assertEquals("con_screen", machine.current.connectionId)
        assertTrue(machine.resized(1280, 576))
        assertEquals(1280, machine.current.width)

        assertTrue(machine.stopping())
        val stopped = machine.stopped(StopReason.USER_STOPPED)
        assertEquals(ScreenShareState.IDLE, stopped.state)
        assertEquals(StopReason.USER_STOPPED, stopped.reason)
        assertTrue("종료 뒤 다시 시작할 수 있다", machine.begin())
    }

    @Test
    fun `종료는 한 번만 처리한다(사용자 중지와 시스템 onStop 이 겹쳐도)`() {
        val machine = ScreenShareStateMachine()
        machine.begin()
        machine.connecting(720, 1280)
        assertTrue(machine.stopping())
        assertFalse(machine.stopping())
        assertFalse("종료 중에는 송출 상태로 가지 않는다", machine.publishing("c", "s"))
        assertFalse("IDLE 에서는 종료할 것이 없다", ScreenShareStateMachine().stopping())
    }

    @Test
    fun `송출 통계는 송출 중에만 반영한다`() {
        val machine = ScreenShareStateMachine()
        machine.begin()
        machine.connecting(576, 1280)
        assertFalse("연결 중에는 통계를 반영하지 않는다", machine.measured(1, 1, 1.0))
        machine.publishing("con", "str")
        assertTrue(machine.measured(150, 400_000, 15.0))
        assertEquals(150L, machine.current.framesEncoded)
        assertEquals(400_000L, machine.current.toJson().getLong("bytesSent"))
    }

    @Test
    fun `건너뛴 전이는 거부한다`() {
        val machine = ScreenShareStateMachine()
        assertFalse(machine.connecting(1, 1))
        machine.begin()
        assertFalse("CONNECTING 전에 PUBLISHING 불가", machine.publishing("c", "s"))
        assertFalse(machine.resized(10, 10))
    }

    @Test
    fun `상태 JSON 은 브리지 계약 필드를 담는다`() {
        val json = ScreenShareStatus(ScreenShareState.IDLE, reason = StopReason.NETWORK_LOST).toJson()
        assertEquals("idle", json.getString("state"))
        assertFalse(json.getBoolean("active"))
        assertEquals("network-lost", json.getString("reason"))
        assertTrue(json.getString("message").contains("네트워크"))
        assertTrue(json.isNull("connectionId"))
    }
}
