package kr.co.studybridge.screenshare

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.test.assertFailsWith

/** openvidu-browser 2.30.0 이 보내는 메시지와 같은 모양인지 고정한다(서버 계약 호환). */
class OpenViduProtocolTest {

    @Test
    fun `토큰에서 openvidu WebSocket 주소와 세션을 만든다`() {
        val endpoint = OpenViduProtocol.endpointFromToken("wss://studybridge.co.kr?sessionId=group_study_51&token=tok_AbC123")
        assertEquals("wss://studybridge.co.kr/openvidu?sessionId=group_study_51", endpoint.webSocketUrl)
        assertEquals("group_study_51", endpoint.sessionId)
    }

    @Test
    fun `포트가 있는 ws 토큰은 wss 로 올리고 포트를 유지한다`() {
        val endpoint = OpenViduProtocol.endpointFromToken("ws://10.0.0.5:4443?sessionId=group_study_7&token=tok_x")
        assertEquals("wss://10.0.0.5:4443/openvidu?sessionId=group_study_7", endpoint.webSocketUrl)
    }

    @Test
    fun `OpenVidu 토큰이 아니면 거부한다`() {
        assertFailsWith<IllegalArgumentException> { OpenViduProtocol.endpointFromToken("tok_only") }
        assertFailsWith<IllegalArgumentException> { OpenViduProtocol.endpointFromToken("wss://host?token=tok_x") }
    }

    @Test
    fun `요청은 JSON-RPC 2_0 형식이다`() {
        val message = JSONObject(OpenViduProtocol.request(3, "ping", OpenViduProtocol.pingParams(first = true)))
        assertEquals(3, message.getInt("id"))
        assertEquals("ping", message.getString("method"))
        assertEquals("2.0", message.getString("jsonrpc"))
        assertEquals(5000, message.getJSONObject("params").getInt("interval"))
        assertFalse(JSONObject(OpenViduProtocol.request(4, "ping", OpenViduProtocol.pingParams(first = false))).has("params"))
    }

    @Test
    fun `joinRoom 은 토큰·세션·메타데이터를 보낸다`() {
        val metadata = """{"userId":"7","clientData":"김민서","kind":"SCREEN"}"""
        val params = OpenViduProtocol.joinRoomParams("wss://h?sessionId=s&token=t", "s", metadata)
        assertEquals("s", params.getString("session"))
        assertEquals(metadata, params.getString("metadata"))
        assertEquals("2.30.0", params.getString("sdkVersion"))
        assertFalse(params.getBoolean("recorder"))
    }

    @Test
    fun `publishVideo 는 오디오 없는 SCREEN 영상으로 게시한다`() {
        val params = OpenViduProtocol.publishVideoParams("v=0", 720, 1600, 15)
        assertEquals("SCREEN", params.getString("typeOfVideo"))
        assertFalse(params.getBoolean("hasAudio"))
        assertTrue(params.getBoolean("hasVideo"))
        assertEquals(15, params.getInt("frameRate"))
        val dimensions = JSONObject(params.getString("videoDimensions"))
        assertEquals(720, dimensions.getInt("width"))
        assertEquals(1600, dimensions.getInt("height"))
        assertEquals("v=0", params.getString("sdpOffer"))
    }

    @Test
    fun `ICE 후보는 내 connectionId 를 endpointName 으로 보낸다`() {
        val params = OpenViduProtocol.iceCandidateParams("con_screen", "candidate:1 1 udp 1 1.2.3.4 5 typ host", "0", 0)
        assertEquals("con_screen", params.getString("endpointName"))
        assertEquals("0", params.getString("sdpMid"))
        assertEquals(0, params.getInt("sdpMLineIndex"))
    }

    @Test
    fun `회전 시 videoDimensions 변경을 알린다`() {
        val params = OpenViduProtocol.videoDimensionsChangedParams("str_1", 1600, 720)
        assertEquals("videoDimensions", params.getString("property"))
        assertEquals(1600, JSONObject(params.getString("newValue")).getInt("width"))
    }

    @Test
    fun `응답과 알림을 구분한다`() {
        val response = OpenViduProtocol.parse("""{"id":2,"result":{"id":"con_1","sdpAnswer":"x"},"jsonrpc":"2.0"}""")
        assertTrue(response is RpcMessage.Response)
        assertEquals("con_1", (response as RpcMessage.Response).result!!.getString("id"))

        val error = OpenViduProtocol.parse("""{"id":5,"error":{"code":401,"message":"no"},"jsonrpc":"2.0"}""")
        assertEquals(401, (error as RpcMessage.Response).error!!.code)

        val notification = OpenViduProtocol.parse("""{"method":"iceCandidate","params":{"endpointName":"con_1"},"jsonrpc":"2.0"}""")
        assertEquals("iceCandidate", (notification as RpcMessage.Notification).method)

        assertEquals(RpcMessage.Invalid, OpenViduProtocol.parse("not json"))
        assertEquals(RpcMessage.Invalid, OpenViduProtocol.parse("""{"id":1,"jsonrpc":"2.0"}"""))
    }

    @Test
    fun `앱이 넘긴 ICE 서버는 stun·turn 주소만 받는다`() {
        val servers = OpenViduProtocol.iceServersFromJson(
            JSONArray(
                """[{"urls":"stun:stun.l.google.com:19302"},
                    {"urls":["turn:1.2.3.4:3478?transport=udp","https://bad"],"username":"u","credential":"c"},
                    {"urls":"http://bad"},
                    {"urls":"turn:5.6.7.8:3478","username":null}]""",
            ),
        )
        assertEquals(3, servers.size)
        assertEquals(listOf("turn:1.2.3.4:3478?transport=udp"), servers[1].urls)
        assertEquals("u", servers[1].username)
        assertNull("JSON null 은 \"null\" 문자열이 아니다", servers[2].username)
    }

    @Test
    fun `joinRoom 응답의 customIceServers 를 읽는다`() {
        val servers = OpenViduProtocol.customIceServers(
            JSONObject("""{"customIceServers":[{"url":"turn:9.9.9.9:3478","username":"a","credential":"b"}]}"""),
        )
        assertEquals(listOf("turn:9.9.9.9:3478"), servers.single().urls)
        assertTrue(OpenViduProtocol.customIceServers(JSONObject("{}")).isEmpty())
    }
}
