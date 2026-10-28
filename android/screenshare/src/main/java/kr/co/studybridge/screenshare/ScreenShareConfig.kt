package kr.co.studybridge.screenshare

import org.json.JSONObject

/**
 * WebView(JS) 가 넘기는 송출 설정. 토큰·연결 정보는 서버(POST /api/groups/{g}/video/screen-token) 응답을 그대로 쓴다.
 * 범위를 벗어난 값은 안전한 범위로 자르고, 토큰이 OpenVidu 형식이 아니면 시작하지 않는다.
 */
internal data class ScreenShareConfig(
    val token: String,
    val endpoint: OpenViduEndpoint,
    val expectedConnectionId: String?,
    val metadata: String,
    val iceServers: List<IceServerSpec>,
    val maxSendKbps: Int,
    val maxLongSide: Int,
    val frameRate: Int,
) {
    companion object {
        const val DEFAULT_FRAME_RATE = 15
        const val DEFAULT_MAX_LONG_SIDE = 1280
        const val DEFAULT_MAX_SEND_KBPS = 2500
        private const val MAX_METADATA_CHARS = 1000

        fun parse(json: String?): ScreenShareConfig {
            val source = try {
                JSONObject(json ?: "")
            } catch (_: Exception) {
                throw IllegalArgumentException("화면공유 설정을 읽지 못했습니다.")
            }
            val token = source.optStringOrNull("token") ?: throw IllegalArgumentException("화면공유 토큰이 없습니다.")
            val metadata = source.optStringOrNull("metadata").orEmpty()
            require(metadata.length <= MAX_METADATA_CHARS) { "화면공유 참가자 정보가 너무 깁니다." }

            return ScreenShareConfig(
                token = token,
                endpoint = OpenViduProtocol.endpointFromToken(token),
                expectedConnectionId = source.optStringOrNull("connectionId"),
                metadata = metadata,
                iceServers = OpenViduProtocol.iceServersFromJson(source.optJSONArray("iceServers")),
                maxSendKbps = source.optInt("maxSendKbps", DEFAULT_MAX_SEND_KBPS).clampOr(DEFAULT_MAX_SEND_KBPS, 300, 4000),
                maxLongSide = source.optInt("maxLongSide", DEFAULT_MAX_LONG_SIDE).clampOr(DEFAULT_MAX_LONG_SIDE, 640, 1920),
                frameRate = source.optInt("frameRate", DEFAULT_FRAME_RATE).clampOr(DEFAULT_FRAME_RATE, 5, 30),
            )
        }

        private fun Int.clampOr(fallback: Int, min: Int, max: Int): Int = if (this <= 0) fallback else coerceIn(min, max)
    }
}

/** 실제 디스플레이 크기 → 송출 크기. 방향(가로/세로)은 유지하고 긴 변만 줄이며, 하드웨어 인코더를 위해 16 배수로 맞춘다. */
internal data class CaptureSize(val width: Int, val height: Int) {
    companion object {
        private const val ALIGNMENT = 16

        fun fit(displayWidth: Int, displayHeight: Int, maxLongSide: Int): CaptureSize {
            require(displayWidth > 0 && displayHeight > 0) { "디스플레이 크기를 알 수 없습니다." }
            val longSide = maxOf(displayWidth, displayHeight)
            val scale = if (longSide > maxLongSide) maxLongSide.toDouble() / longSide else 1.0
            return CaptureSize(align(displayWidth * scale), align(displayHeight * scale))
        }

        private fun align(value: Double): Int = maxOf(ALIGNMENT, (value / ALIGNMENT).toInt() * ALIGNMENT)
    }
}
