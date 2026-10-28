package kr.co.studybridge.screenshare

import org.json.JSONArray
import org.json.JSONObject
import java.net.URLDecoder
import java.net.URLEncoder

/**
 * OpenVidu 2.x JSON-RPC 계약 — openvidu-browser 2.30.0(웹·WebView 가 쓰는 버전)과 같은 메시지를 만든다.
 *
 *  · 토큰: `wss://<host>?sessionId=<id>&token=<tok>` → WebSocket `wss://<host>/openvidu?sessionId=<id>` (Session.getTokenParams / OpenVidu.startWs)
 *    ws:// 토큰은 wss:// 로 올린다(웹 forceSecureWebSocketTransport 와 동일).
 *  · joinRoom → publishVideo(sdpOffer) → onIceCandidate(endpointName = 내 connectionId) / 서버 알림 iceCandidate
 *  · ping: 5초마다, 첫 ping 만 {interval:5000} (kurento-jsonrpc heartbeat)
 */
internal data class OpenViduEndpoint(val webSocketUrl: String, val sessionId: String)

internal sealed class RpcMessage {
    data class Response(val id: Int, val result: JSONObject?, val error: RpcError?) : RpcMessage()
    data class Notification(val method: String, val params: JSONObject) : RpcMessage()
    object Invalid : RpcMessage()
}

internal data class RpcError(val code: Int, val message: String)

internal object OpenViduProtocol {
    const val SDK_VERSION = "2.30.0"
    const val PING_INTERVAL_MS = 5_000L
    const val PLATFORM = "StudyBridge Android ScreenShare"

    private val TOKEN_URL = Regex("^(wss?|https?)://([^/?#]+)[^?#]*\\?([^#]*)", RegexOption.IGNORE_CASE)
    private val SAFE_SESSION_ID = Regex("^[A-Za-z0-9_-]+$")

    fun endpointFromToken(token: String): OpenViduEndpoint {
        val match = TOKEN_URL.find(token.trim()) ?: throw IllegalArgumentException("OpenVidu 토큰 형식이 아닙니다.")
        val host = match.groupValues[2]
        val query = queryParams(match.groupValues[3])
        val sessionId = query["sessionId"]?.takeIf { it.isNotBlank() }
            ?: throw IllegalArgumentException("토큰에 sessionId 가 없습니다.")
        val encodedSession = if (SAFE_SESSION_ID.matches(sessionId)) sessionId else URLEncoder.encode(sessionId, "UTF-8")
        return OpenViduEndpoint("wss://$host/openvidu?sessionId=$encodedSession", sessionId)
    }

    private fun queryParams(query: String): Map<String, String> =
        query.split('&')
            .filter { it.isNotEmpty() }
            .associate { pair ->
                val index = pair.indexOf('=')
                if (index < 0) decode(pair) to "" else decode(pair.substring(0, index)) to decode(pair.substring(index + 1))
            }

    private fun decode(value: String): String = URLDecoder.decode(value, "UTF-8")

    fun request(id: Int, method: String, params: JSONObject?): String {
        val message = JSONObject()
        message.put("id", id)
        message.put("method", method)
        if (params != null) message.put("params", params)
        message.put("jsonrpc", "2.0")
        return message.toString()
    }

    fun joinRoomParams(token: String, sessionId: String, metadata: String): JSONObject =
        JSONObject()
            .put("token", token)
            .put("session", sessionId)
            .put("platform", PLATFORM)
            .put("sdkVersion", SDK_VERSION)
            .put("metadata", metadata)
            .put("secret", "")
            .put("recorder", false)
            .put("stt", false)

    /** 화면공유 전용 송출: 오디오 없음, typeOfVideo=SCREEN(서버의 PRIMARY 우회 게시 정리 규칙과도 맞는다). */
    fun publishVideoParams(sdpOffer: String, width: Int, height: Int, frameRate: Int): JSONObject =
        JSONObject()
            .put("doLoopback", false)
            .put("hasAudio", false)
            .put("hasVideo", true)
            .put("audioActive", false)
            .put("videoActive", true)
            .put("typeOfVideo", "SCREEN")
            .put("frameRate", frameRate)
            .put("videoDimensions", dimensionsJson(width, height))
            .put("sdpOffer", sdpOffer)

    fun iceCandidateParams(endpointName: String, candidate: String, sdpMid: String?, sdpMLineIndex: Int): JSONObject =
        JSONObject()
            .put("endpointName", endpointName)
            .put("candidate", candidate)
            .put("sdpMid", sdpMid ?: JSONObject.NULL)
            .put("sdpMLineIndex", sdpMLineIndex)

    /** 회전·해상도 변경을 시청자에게 알린다(openvidu-browser 의 streamPropertyChanged videoDimensions 와 같은 형식). */
    fun videoDimensionsChangedParams(streamId: String, width: Int, height: Int): JSONObject =
        JSONObject()
            .put("streamId", streamId)
            .put("property", "videoDimensions")
            .put("newValue", dimensionsJson(width, height))
            .put("reason", "screenResized")

    fun pingParams(first: Boolean): JSONObject? = if (first) JSONObject().put("interval", PING_INTERVAL_MS) else null

    private fun dimensionsJson(width: Int, height: Int): String =
        JSONObject().put("width", width).put("height", height).toString()

    fun parse(text: String): RpcMessage {
        val message = try {
            JSONObject(text)
        } catch (_: Exception) {
            return RpcMessage.Invalid
        }
        if (message.has("method")) {
            return RpcMessage.Notification(message.optString("method"), message.optJSONObject("params") ?: JSONObject())
        }
        if (!message.has("id")) return RpcMessage.Invalid
        val id = message.optInt("id", -1)
        if (id < 0) return RpcMessage.Invalid
        val error = message.optJSONObject("error")?.let {
            RpcError(it.optInt("code", 0), it.optString("message", "OpenVidu 오류"))
        }
        val result = message.optJSONObject("result")
        if (error == null && result == null) return RpcMessage.Invalid
        return RpcMessage.Response(id, result, error)
    }

    /** joinRoom 응답의 customIceServers([{url, username, credential}]) — 앱이 ICE 서버를 넘기지 않았을 때만 쓴다. */
    fun customIceServers(joinResult: JSONObject): List<IceServerSpec> {
        val list = joinResult.optJSONArray("customIceServers") ?: return emptyList()
        return (0 until list.length()).mapNotNull { index ->
            val item = list.optJSONObject(index) ?: return@mapNotNull null
            val url = item.optString("url").takeIf { it.isNotBlank() } ?: return@mapNotNull null
            IceServerSpec(listOf(url), item.optStringOrNull("username"), item.optStringOrNull("credential"))
        }
    }

    fun iceServersFromJson(array: JSONArray?): List<IceServerSpec> {
        if (array == null) return emptyList()
        return (0 until array.length()).mapNotNull { index ->
            val item = array.optJSONObject(index) ?: return@mapNotNull null
            val urls = when (val raw = item.opt("urls")) {
                is JSONArray -> (0 until raw.length()).mapNotNull { raw.optString(it).takeIf(String::isNotBlank) }
                is String -> listOf(raw).filter(String::isNotBlank)
                else -> emptyList()
            }.filter { it.startsWith("stun:") || it.startsWith("turn:") || it.startsWith("turns:") }
            if (urls.isEmpty()) return@mapNotNull null
            IceServerSpec(urls, item.optStringOrNull("username"), item.optStringOrNull("credential"))
        }
    }
}

internal data class IceServerSpec(val urls: List<String>, val username: String?, val credential: String?)

/** org.json 의 optString 은 JSON null 을 "null" 문자열로 돌려준다 → 없음으로 본다. */
internal fun JSONObject.optStringOrNull(name: String): String? =
    if (isNull(name)) null else optString(name).takeIf { it.isNotBlank() }
