package kr.co.studybridge.screenshare

import org.json.JSONObject

/**
 * 화면공유 상태 머신:
 *  IDLE → STARTING(서비스·캡처 준비) → CONNECTING(OpenVidu SCREEN 접속·협상) → PUBLISHING(송출 중) → STOPPING → IDLE(종료 사유 포함)
 * 어느 단계에서 실패해도 STOPPING 을 거쳐 IDLE 로 돌아오고, 종료는 한 번만 처리한다(중복 종료 요청은 무시).
 */
internal enum class ScreenShareState(val wire: String) {
    IDLE("idle"),
    STARTING("starting"),
    CONNECTING("connecting"),
    PUBLISHING("publishing"),
    STOPPING("stopping");

    val isActive: Boolean get() = this != IDLE
}

internal enum class StopReason(val wire: String, val message: String) {
    USER_STOPPED("user-stopped", "화면공유를 종료했습니다."),
    PERMISSION_REVOKED("permission-revoked", "시스템에서 화면공유가 중지되었습니다."),
    PERMISSION_DENIED("permission-denied", "화면 녹화 권한을 받지 못해 화면공유를 시작하지 않았습니다."),
    NETWORK_LOST("network-lost", "네트워크 연결이 끊겨 화면공유를 종료했습니다. 연결을 확인한 뒤 다시 시작해 주세요."),
    SERVER_CLOSED("server-closed", "서버에서 화면공유 연결을 종료했습니다."),
    CONNECTION_FAILED("connection-failed", "화면공유 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요."),
    APP_CLOSED("app-closed", "앱이 종료되어 화면공유를 끝냈습니다."),
    INVALID_REQUEST("invalid-request", "화면공유 요청 정보가 올바르지 않습니다."),
    ERROR("error", "화면공유 중 오류가 발생했습니다."),
}

internal data class ScreenShareStatus(
    val state: ScreenShareState,
    val reason: StopReason? = null,
    val message: String? = null,
    val connectionId: String? = null,
    val streamId: String? = null,
    val width: Int = 0,
    val height: Int = 0,
    /** 송출 통계(outbound-rtp): 실제로 인코딩·전송된 프레임/바이트. 0 이면 아직 화면이 나가지 않은 것이다. */
    val framesEncoded: Long = 0,
    val bytesSent: Long = 0,
    val framesPerSecond: Double = 0.0,
    val updatedAt: Long = System.currentTimeMillis(),
) {
    fun toJson(): JSONObject =
        JSONObject()
            .put("state", state.wire)
            .put("active", state.isActive)
            .put("reason", reason?.wire ?: JSONObject.NULL)
            .put("message", (message ?: reason?.message) ?: JSONObject.NULL)
            .put("connectionId", connectionId ?: JSONObject.NULL)
            .put("streamId", streamId ?: JSONObject.NULL)
            .put("width", width)
            .put("height", height)
            .put("framesEncoded", framesEncoded)
            .put("bytesSent", bytesSent)
            .put("framesPerSecond", framesPerSecond)
            .put("updatedAt", updatedAt)

    companion object {
        val IDLE = ScreenShareStatus(ScreenShareState.IDLE, updatedAt = 0)
    }
}

/** 허용 전이만 통과시키는 순수 상태 머신(단위 테스트 대상). */
internal class ScreenShareStateMachine(initial: ScreenShareStatus = ScreenShareStatus.IDLE) {
    var current: ScreenShareStatus = initial
        private set

    private var stopRequested = false

    fun begin(): Boolean {
        if (current.state != ScreenShareState.IDLE) return false
        stopRequested = false
        current = ScreenShareStatus(ScreenShareState.STARTING)
        return true
    }

    fun connecting(width: Int, height: Int): Boolean = move(ScreenShareState.STARTING, ScreenShareState.CONNECTING) {
        it.copy(width = width, height = height)
    }

    fun publishing(connectionId: String?, streamId: String?): Boolean =
        move(ScreenShareState.CONNECTING, ScreenShareState.PUBLISHING) { it.copy(connectionId = connectionId, streamId = streamId) }

    fun measured(framesEncoded: Long, bytesSent: Long, framesPerSecond: Double): Boolean {
        if (current.state != ScreenShareState.PUBLISHING) return false
        current = current.copy(framesEncoded = framesEncoded, bytesSent = bytesSent, framesPerSecond = framesPerSecond)
        return true
    }

    fun resized(width: Int, height: Int): Boolean {
        if (current.state != ScreenShareState.CONNECTING && current.state != ScreenShareState.PUBLISHING) return false
        current = current.copy(width = width, height = height, updatedAt = System.currentTimeMillis())
        return true
    }

    /** 첫 종료 요청만 true. 이후 요청(사용자 중지 + 시스템 onStop 동시 발생 등)은 무시한다. */
    fun stopping(): Boolean {
        if (stopRequested || current.state == ScreenShareState.IDLE) return false
        stopRequested = true
        current = current.copy(state = ScreenShareState.STOPPING, updatedAt = System.currentTimeMillis())
        return true
    }

    fun stopped(reason: StopReason, message: String? = null): ScreenShareStatus {
        current = ScreenShareStatus(ScreenShareState.IDLE, reason = reason, message = message)
        return current
    }

    private fun move(from: ScreenShareState, to: ScreenShareState, change: (ScreenShareStatus) -> ScreenShareStatus): Boolean {
        if (stopRequested || current.state != from) return false
        current = change(current).copy(state = to, updatedAt = System.currentTimeMillis())
        return true
    }
}
