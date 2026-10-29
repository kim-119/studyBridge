package kr.co.studybridge.screenshare

import android.content.Context
import android.util.Log
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SoftwareVideoDecoderFactory
import org.webrtc.SoftwareVideoEncoderFactory
import org.webrtc.VideoTrack
import java.util.concurrent.CompletableFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

/**
 * 테스트용 시청자: 같은 OpenVidu 세션에 다른 참가자로 들어가 SCREEN 스트림을 구독(receiveVideoFrom, recvonly)하고
 * 실제로 디코딩된 프레임 수·크기를 센다. openvidu-browser 2.30 의 Kurento 구독 흐름(클라이언트 offer)과 같다.
 */
internal class OpenViduTestViewer(context: Context, token: String) {

    data class RemoteScreen(val connectionId: String, val streamId: String, val typeOfVideo: String, val metadata: String)

    private val endpoint = OpenViduProtocol.endpointFromToken(token, keepInsecureWebSocket = true)
    private val token = token
    private val worker = WebRtcRuntime.serialScheduler("sb-test-viewer")
    private val factory: PeerConnectionFactory
    private var signaling: OpenViduSignaling? = null
    private var peer: PeerConnection? = null
    private var publisherConnectionId: String? = null
    private val joined = CompletableFuture<JSONObject>()
    private val subscribed = CompletableFuture<Unit>()
    private val pendingCandidates = mutableListOf<IceCandidate>()
    private var remoteSet = false

    val decodedFrames = AtomicInteger(0)
    val lastFrameSize = AtomicReference("0x0")

    init {
        WebRtcRuntime.ensureInitialized(context)
        factory = PeerConnectionFactory.builder()
            .setVideoDecoderFactory(SoftwareVideoDecoderFactory())
            .setVideoEncoderFactory(SoftwareVideoEncoderFactory())
            .createPeerConnectionFactory()
    }

    /** 세션에 들어가 이미 게시 중인 SCREEN 스트림 정보를 돌려준다(시청자가 보는 서버 정보 그대로). */
    fun joinAndFindScreen(timeoutSec: Long = 20): RemoteScreen {
        signaling = OpenViduSignaling(endpoint.webSocketUrl, worker, object : OpenViduSignaling.Listener {
            override fun onOpen() {
                val params = OpenViduProtocol.joinRoomParams(token, endpoint.sessionId, """{"clientData":"E2E Viewer"}""")
                signaling?.request("joinRoom", params) { result, error ->
                    if (result != null) joined.complete(result) else joined.completeExceptionally(AssertionError("viewer joinRoom: ${error?.message}"))
                }
            }

            override fun onNotification(method: String, params: JSONObject) {
                if (method != "iceCandidate") return
                val owner = publisherConnectionId ?: return
                if (!OpenViduProtocol.isIceCandidateFor(params, owner)) return
                val candidate = IceCandidate(params.optStringOrNull("sdpMid"), params.optInt("sdpMLineIndex", 0), params.optString("candidate"))
                if (remoteSet) peer?.addIceCandidate(candidate) else pendingCandidates.add(candidate)
            }

            override fun onClosed(byServer: Boolean, detail: String) {
                joined.completeExceptionally(AssertionError("viewer signaling closed: $detail"))
            }
        }).also { it.connect() }

        val result = joined.get(timeoutSec, TimeUnit.SECONDS)
        val participants = result.optJSONArray("value") ?: throw AssertionError("joinRoom 응답에 참가자 목록이 없음")
        for (index in 0 until participants.length()) {
            val participant = participants.getJSONObject(index)
            val stream = participant.optJSONArray("streams")?.optJSONObject(0) ?: continue
            if (stream.optString("typeOfVideo") != "SCREEN") continue
            return RemoteScreen(
                connectionId = participant.getString("id"),
                streamId = stream.getString("id"),
                typeOfVideo = stream.getString("typeOfVideo"),
                metadata = participant.optString("metadata"),
            )
        }
        throw AssertionError("시청자가 받은 참가자 목록에 SCREEN 스트림이 없음: $participants")
    }

    /** SCREEN 스트림을 구독하고, 디코딩된 프레임을 센다. */
    fun subscribe(screen: RemoteScreen, timeoutSec: Long = 30) {
        worker.execute {
            publisherConnectionId = screen.connectionId
            val connection = factory.createPeerConnection(
                PeerConnection.RTCConfiguration(emptyList()).apply { sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN },
                observer,
            ) ?: run {
                subscribed.completeExceptionally(AssertionError("viewer PeerConnection 생성 실패"))
                return@execute
            }
            peer = connection
            val transceiver = connection.addTransceiver(
                org.webrtc.MediaStreamTrack.MediaType.MEDIA_TYPE_VIDEO,
                RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.RECV_ONLY),
            )
            (transceiver.receiver.track() as? VideoTrack)?.addSink { frame ->
                decodedFrames.incrementAndGet()
                lastFrameSize.set("${frame.rotatedWidth}x${frame.rotatedHeight}")
            }
            connection.createOffer(sdp("createOffer") { created ->
                val offer = requireNotNull(created)
                connection.setLocalDescription(sdp("setLocal") {
                    val params = JSONObject().put("sender", screen.streamId).put("sdpOffer", offer.description)
                    signaling?.request("receiveVideoFrom", params) { result, error ->
                        val answer = result?.optStringOrNull("sdpAnswer")
                        if (answer == null) {
                            subscribed.completeExceptionally(AssertionError("receiveVideoFrom: ${error?.message}"))
                            return@request
                        }
                        connection.setRemoteDescription(sdp("setRemote") {
                            worker.execute {
                                remoteSet = true
                                pendingCandidates.forEach { connection.addIceCandidate(it) }
                                pendingCandidates.clear()
                                subscribed.complete(Unit)
                            }
                        }, SessionDescription(SessionDescription.Type.ANSWER, answer))
                    }
                }, offer)
            }, MediaConstraints())
        }
        subscribed.get(timeoutSec, TimeUnit.SECONDS)
    }

    fun close() {
        worker.execute {
            signaling?.close(finalMethod = "leaveRoom")
            runCatching { peer?.dispose() }
            runCatching { factory.dispose() }
            worker.shutdown()
        }
    }

    private val observer = object : PeerConnection.Observer {
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) {
            Log.i(TAG, "viewer ice=$state")
        }
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onDataChannel(channel: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receiver: RtpReceiver, streams: Array<out MediaStream>) = Unit
        override fun onIceCandidate(candidate: IceCandidate) {
            worker.execute {
                val target = publisherConnectionId ?: return@execute
                signaling?.request("onIceCandidate", OpenViduProtocol.iceCandidateParams(target, candidate.sdp, candidate.sdpMid, candidate.sdpMLineIndex)) { _, _ -> }
            }
        }
    }

    private fun sdp(step: String, onSuccess: (SessionDescription?) -> Unit) = object : SdpObserver {
        override fun onCreateSuccess(description: SessionDescription) = onSuccess(description)
        override fun onSetSuccess() = onSuccess(null)
        override fun onCreateFailure(error: String?) { subscribed.completeExceptionally(AssertionError("$step: $error")) }
        override fun onSetFailure(error: String?) { subscribed.completeExceptionally(AssertionError("$step: $error")) }
    }

    private companion object {
        const val TAG = "SBScreenShareE2E"
    }
}
