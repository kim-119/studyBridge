package kr.co.studybridge.screenshare

import android.content.Context
import android.media.projection.MediaProjection
import android.util.Log
import org.json.JSONObject
import org.webrtc.DataChannel
import org.webrtc.DefaultVideoDecoderFactory
import org.webrtc.DefaultVideoEncoderFactory
import org.webrtc.EglBase
import org.webrtc.IceCandidate
import org.webrtc.MediaConstraints
import org.webrtc.MediaStream
import org.webrtc.PeerConnection
import org.webrtc.PeerConnectionFactory
import org.webrtc.RTCStatsReport
import org.webrtc.RtpParameters
import org.webrtc.RtpReceiver
import org.webrtc.RtpTransceiver
import org.webrtc.SdpObserver
import org.webrtc.SessionDescription
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoSource
import org.webrtc.VideoTrack
import org.webrtc.audio.AudioDeviceModule
import org.webrtc.audio.JavaAudioDeviceModule
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.ScheduledThreadPoolExecutor
import java.util.concurrent.TimeUnit

/**
 * 화면 캡처 → libwebrtc VideoTrack → OpenVidu SCREEN Connection(별도 WebSocket·PeerConnection) 송출.
 * WebView 의 PRIMARY(카메라·마이크) 연결과 독립이며, 모든 작업은 단일 작업 스레드에서 순서대로 처리한다.
 */
internal class ScreenPublisher(
    private val context: Context,
    private val projection: MediaProjection,
    private val config: ScreenShareConfig,
    private val displaySize: () -> DisplayInfo,
    private val onStatus: (ScreenShareStatus) -> Unit,
    private val onFinished: (ScreenShareStatus) -> Unit,
) {
    data class DisplayInfo(val width: Int, val height: Int, val densityDpi: Int)

    private val worker = (Executors.newSingleThreadScheduledExecutor { runnable ->
        Thread(runnable, "sb-screen-publisher")
    } as ScheduledThreadPoolExecutor).apply {
        executeExistingDelayedTasksAfterShutdownPolicy = false
        continueExistingPeriodicTasksAfterShutdownPolicy = false
    }
    private val machine = ScreenShareStateMachine()

    private var eglBase: EglBase? = null
    private var audioModule: AudioDeviceModule? = null
    private var factory: PeerConnectionFactory? = null
    private var textureHelper: SurfaceTextureHelper? = null
    private var capturer: DisplayCapturer? = null
    private var videoSource: VideoSource? = null
    private var videoTrack: VideoTrack? = null
    private var peer: PeerConnection? = null
    private var signaling: OpenViduSignaling? = null

    private var connectionId: String? = null
    private var streamId: String? = null
    private var size = CaptureSize(0, 0)
    private var remoteDescriptionSet = false
    private val pendingRemoteCandidates = mutableListOf<IceCandidate>()

    private var connectTimeout: ScheduledFuture<*>? = null
    private var disconnectTimeout: ScheduledFuture<*>? = null
    private var frameRefresh: ScheduledFuture<*>? = null
    private var statsPoll: ScheduledFuture<*>? = null

    fun start() = post {
        if (!machine.begin()) return@post
        emit()
        try {
            startCapture()
            connectSignaling()
        } catch (error: Exception) {
            Log.e(TAG, "screen share start failed", error)
            finish(StopReason.ERROR, error.message)
        }
    }

    fun stop(reason: StopReason) = post { finish(reason, null) }

    /** 회전·해상도 변경: 같은 VirtualDisplay 를 새 크기로 바꾸고 시청자에게 새 영상 크기를 알린다. */
    fun onDisplayChanged() = post {
        val current = capturer ?: return@post
        val info = displaySize()
        val next = CaptureSize.fit(info.width, info.height, config.maxLongSide)
        if (next == size) return@post
        size = next
        current.changeCaptureFormat(next.width, next.height, config.frameRate)
        videoSource?.adaptOutputFormat(next.width, next.height, config.frameRate)
        if (machine.resized(next.width, next.height)) emit()
        val published = streamId ?: return@post
        signaling?.request(
            "streamPropertyChanged",
            OpenViduProtocol.videoDimensionsChangedParams(published, next.width, next.height),
        ) { _, error -> if (error != null) Log.w(TAG, "videoDimensions update rejected: ${error.message}") }
    }

    private fun startCapture() {
        ensureWebRtcInitialized(context)
        val egl = EglBase.create().also { eglBase = it }
        val adm = JavaAudioDeviceModule.builder(context).createAudioDeviceModule().also { audioModule = it }
        val peerFactory = PeerConnectionFactory.builder()
            .setAudioDeviceModule(adm)
            .setVideoEncoderFactory(DefaultVideoEncoderFactory(egl.eglBaseContext, true, true))
            .setVideoDecoderFactory(DefaultVideoDecoderFactory(egl.eglBaseContext))
            .createPeerConnectionFactory()
            .also { factory = it }

        val info = displaySize()
        size = CaptureSize.fit(info.width, info.height, config.maxLongSide)
        val helper = SurfaceTextureHelper.create("sb-screen-capture", egl.eglBaseContext)
            ?: throw IllegalStateException("화면 캡처 버퍼를 만들지 못했습니다.")
        textureHelper = helper

        val source = peerFactory.createVideoSource(true).also { videoSource = it }
        source.adaptOutputFormat(size.width, size.height, config.frameRate)
        val displayCapturer = DisplayCapturer(projection, info.densityDpi).also { capturer = it }
        displayCapturer.initialize(helper, context, source.capturerObserver)
        displayCapturer.startCapture(size.width, size.height, config.frameRate)
        videoTrack = peerFactory.createVideoTrack(TRACK_ID, source)

        frameRefresh = worker.scheduleWithFixedDelay(
            { capturer?.refreshIfIdle(FRAME_REFRESH_IDLE_MS) },
            FRAME_REFRESH_IDLE_MS,
            FRAME_REFRESH_IDLE_MS,
            TimeUnit.MILLISECONDS,
        )
        machine.connecting(size.width, size.height)
        emit()
    }

    private fun connectSignaling() {
        connectTimeout = worker.schedule({ finish(StopReason.CONNECTION_FAILED, null) }, CONNECT_TIMEOUT_SEC, TimeUnit.SECONDS)
        signaling = OpenViduSignaling(config.endpoint.webSocketUrl, worker, object : OpenViduSignaling.Listener {
            override fun onOpen() = joinRoom()

            override fun onNotification(method: String, params: JSONObject) = handleNotification(method, params)

            override fun onClosed(byServer: Boolean, detail: String) {
                Log.w(TAG, "signaling closed byServer=$byServer detail=$detail")
                finish(if (byServer) StopReason.SERVER_CLOSED else StopReason.NETWORK_LOST, null)
            }
        }).also { it.connect() }
    }

    private fun joinRoom() {
        val params = OpenViduProtocol.joinRoomParams(config.token, config.endpoint.sessionId, config.metadata)
        signaling?.request("joinRoom", params) { result, error ->
            if (error != null || result == null) {
                Log.w(TAG, "joinRoom failed: ${error?.message}")
                finish(StopReason.CONNECTION_FAILED, null)
                return@request
            }
            connectionId = result.optStringOrNull("id")
            if (config.expectedConnectionId != null && connectionId != config.expectedConnectionId) {
                Log.w(TAG, "joined connection differs from issued token connection")
            }
            val iceServers = config.iceServers.ifEmpty { OpenViduProtocol.customIceServers(result) }
            publish(iceServers)
        }
    }

    private fun publish(iceServers: List<IceServerSpec>) {
        val peerFactory = factory ?: return
        val track = videoTrack ?: return
        val rtcConfig = PeerConnection.RTCConfiguration(iceServers.map(::toIceServer)).apply {
            sdpSemantics = PeerConnection.SdpSemantics.UNIFIED_PLAN
            bundlePolicy = PeerConnection.BundlePolicy.MAXBUNDLE
            rtcpMuxPolicy = PeerConnection.RtcpMuxPolicy.REQUIRE
            continualGatheringPolicy = PeerConnection.ContinualGatheringPolicy.GATHER_CONTINUALLY
        }
        val connection = peerFactory.createPeerConnection(rtcConfig, peerObserver)
            ?: return finish(StopReason.CONNECTION_FAILED, null)
        peer = connection

        val transceiver = connection.addTransceiver(
            track,
            RtpTransceiver.RtpTransceiverInit(RtpTransceiver.RtpTransceiverDirection.SEND_ONLY, listOf(STREAM_ID)),
        )
        limitBitrate(transceiver)

        connection.createOffer(object : SimpleSdpObserver("createOffer") {
            override fun onCreateSuccess(description: SessionDescription) = post {
                peer?.setLocalDescription(object : SimpleSdpObserver("setLocalDescription") {
                    override fun onSetSuccess() = post { sendOffer(description.description) }
                }, description)
            }
        }, MediaConstraints())
    }

    /** 서버 Kurento 상한(maxSendKbps)과 같게 맞추고, 글자 선명도를 위해 해상도를 유지(프레임 수를 먼저 줄임)한다. */
    private fun limitBitrate(transceiver: RtpTransceiver) {
        runCatching {
            val sender = transceiver.sender
            val parameters = sender.parameters
            parameters.encodings.forEach { it.maxBitrateBps = config.maxSendKbps * 1000 }
            parameters.degradationPreference = RtpParameters.DegradationPreference.MAINTAIN_RESOLUTION
            if (!sender.setParameters(parameters)) Log.w(TAG, "bitrate limit rejected")
        }.onFailure { Log.w(TAG, "bitrate limit not applied", it) }
    }

    private fun sendOffer(sdp: String) {
        val params = OpenViduProtocol.publishVideoParams(sdp, size.width, size.height, config.frameRate)
        signaling?.request("publishVideo", params, PUBLISH_TIMEOUT_MS) { result, error ->
            val answer = result?.optStringOrNull("sdpAnswer")
            if (error != null || answer == null) {
                Log.w(TAG, "publishVideo failed: ${error?.message}")
                finish(StopReason.CONNECTION_FAILED, null)
                return@request
            }
            streamId = result.optStringOrNull("id")
            peer?.setRemoteDescription(object : SimpleSdpObserver("setRemoteDescription") {
                override fun onSetSuccess() = post {
                    remoteDescriptionSet = true
                    pendingRemoteCandidates.forEach { peer?.addIceCandidate(it) }
                    pendingRemoteCandidates.clear()
                }
            }, SessionDescription(SessionDescription.Type.ANSWER, answer))
        }
    }

    private fun handleNotification(method: String, params: JSONObject) {
        val mine = connectionId ?: return
        when (method) {
            "iceCandidate" -> {
                val target = params.optStringOrNull("endpointName") ?: params.optStringOrNull("senderConnectionId")
                if (target != mine) return
                val sdp = params.optStringOrNull("candidate") ?: return
                val candidate = IceCandidate(params.optStringOrNull("sdpMid"), params.optInt("sdpMLineIndex", 0), sdp)
                if (remoteDescriptionSet) peer?.addIceCandidate(candidate) else pendingRemoteCandidates.add(candidate)
            }
            // 서버가 내 SCREEN 연결을 끊거나(forceDisconnect·정책 정리) 송출을 내렸다(forceUnpublish).
            "participantEvicted", "participantUnpublished", "participantLeft" ->
                if (params.optStringOrNull("connectionId") == mine) finish(StopReason.SERVER_CLOSED, null)
            else -> Unit // sendMessage(시청자 수신 확인 신호) 등은 송출에 영향이 없다.
        }
    }

    private fun onPeerState(state: PeerConnection.PeerConnectionState) {
        when (state) {
            PeerConnection.PeerConnectionState.CONNECTED -> {
                disconnectTimeout?.cancel(false)
                disconnectTimeout = null
                connectTimeout?.cancel(false)
                connectTimeout = null
                if (machine.publishing(connectionId, streamId)) {
                    emit()
                    startStatsPolling()
                }
            }
            // 잠깐의 네트워크 전환은 ICE 가 스스로 회복할 수 있다 → 유예 후에도 끊겨 있으면 안전하게 종료.
            PeerConnection.PeerConnectionState.DISCONNECTED -> if (disconnectTimeout == null) {
                disconnectTimeout = worker.schedule(
                    { finish(StopReason.NETWORK_LOST, null) },
                    DISCONNECT_GRACE_SEC,
                    TimeUnit.SECONDS,
                )
            }
            PeerConnection.PeerConnectionState.FAILED -> finish(StopReason.NETWORK_LOST, null)
            else -> Unit
        }
    }

    /** 송출 중 [STATS_INTERVAL_SEC] 마다 outbound-rtp 통계를 상태에 반영한다(화면이 실제로 나가는지 확인용). */
    private fun startStatsPolling() {
        if (statsPoll != null) return
        statsPoll = worker.scheduleWithFixedDelay({
            peer?.getStats { report -> post { applyStats(report) } }
        }, STATS_INTERVAL_SEC, STATS_INTERVAL_SEC, TimeUnit.SECONDS)
    }

    private fun applyStats(report: RTCStatsReport) {
        val outbound = report.statsMap.values.firstOrNull { it.type == "outbound-rtp" && it.members["kind"] == "video" }
            ?: return
        val frames = (outbound.members["framesEncoded"] as? Number)?.toLong() ?: 0L
        val bytes = (outbound.members["bytesSent"] as? Number)?.toLong() ?: 0L
        val fps = (outbound.members["framesPerSecond"] as? Number)?.toDouble() ?: 0.0
        if (machine.measured(frames, bytes, fps)) emit()
    }

    /** 한 번만 실행된다. 정리 순서: 신호 → PeerConnection → 트랙 → 캡처 → 소스 → 버퍼 → 팩토리 → EGL → MediaProjection. */
    private fun finish(reason: StopReason, message: String?) {
        if (!machine.stopping()) return
        emit()
        listOf(connectTimeout, disconnectTimeout, frameRefresh, statsPoll).forEach { it?.cancel(false) }
        signaling?.close(finalMethod = if (connectionId != null) "leaveRoom" else null)
        signaling = null
        safely("peer") { peer?.dispose() }
        peer = null
        safely("track") { videoTrack?.dispose() }
        videoTrack = null
        safely("capturer") {
            capturer?.stopCapture()
            capturer?.dispose()
        }
        capturer = null
        safely("source") { videoSource?.dispose() }
        videoSource = null
        safely("helper") { textureHelper?.dispose() }
        textureHelper = null
        safely("factory") { factory?.dispose() }
        factory = null
        safely("audio") { audioModule?.release() }
        audioModule = null
        safely("egl") { eglBase?.release() }
        eglBase = null
        safely("projection") { projection.stop() }

        val finalStatus = machine.stopped(reason, message).copy(connectionId = connectionId, streamId = streamId)
        onStatus(finalStatus)
        onFinished(finalStatus)
        worker.shutdown()
    }

    private fun emit() = onStatus(machine.current)

    private fun post(block: () -> Unit) {
        try {
            worker.execute(block)
        } catch (_: RejectedExecutionException) {
            // 이미 종료된 송출에 대한 늦은 콜백은 버린다.
        }
    }

    private inline fun safely(step: String, block: () -> Unit) {
        try {
            block()
        } catch (error: Exception) {
            Log.w(TAG, "cleanup step failed: $step", error)
        }
    }

    private fun toIceServer(spec: IceServerSpec): PeerConnection.IceServer {
        val builder = PeerConnection.IceServer.builder(spec.urls)
        spec.username?.let(builder::setUsername)
        spec.credential?.let(builder::setPassword)
        return builder.createIceServer()
    }

    private val peerObserver = object : PeerConnection.Observer {
        override fun onSignalingChange(state: PeerConnection.SignalingState) = Unit
        override fun onIceConnectionChange(state: PeerConnection.IceConnectionState) = Unit
        override fun onIceConnectionReceivingChange(receiving: Boolean) = Unit
        override fun onIceGatheringChange(state: PeerConnection.IceGatheringState) = Unit
        override fun onIceCandidatesRemoved(candidates: Array<out IceCandidate>) = Unit
        override fun onAddStream(stream: MediaStream) = Unit
        override fun onRemoveStream(stream: MediaStream) = Unit
        override fun onDataChannel(channel: DataChannel) = Unit
        override fun onRenegotiationNeeded() = Unit
        override fun onAddTrack(receiver: RtpReceiver, streams: Array<out MediaStream>) = Unit

        override fun onConnectionChange(newState: PeerConnection.PeerConnectionState) = post { onPeerState(newState) }

        override fun onIceCandidate(candidate: IceCandidate) = post {
            val mine = connectionId ?: return@post
            signaling?.request(
                "onIceCandidate",
                OpenViduProtocol.iceCandidateParams(mine, candidate.sdp, candidate.sdpMid, candidate.sdpMLineIndex),
            ) { _, error -> if (error != null) Log.w(TAG, "onIceCandidate rejected: ${error.message}") }
        }
    }

    private open inner class SimpleSdpObserver(private val step: String) : SdpObserver {
        override fun onCreateSuccess(description: SessionDescription) = Unit
        override fun onSetSuccess() = Unit
        override fun onCreateFailure(error: String?) = post { failSdp(error) }
        override fun onSetFailure(error: String?) = post { failSdp(error) }

        private fun failSdp(error: String?) {
            Log.w(TAG, "$step failed: $error")
            finish(StopReason.CONNECTION_FAILED, null)
        }
    }

    companion object {
        private const val TAG = "SBScreenPublisher"
        private const val TRACK_ID = "sb-screen-video"
        private const val STREAM_ID = "sb-screen"
        private const val CONNECT_TIMEOUT_SEC = 25L
        private const val DISCONNECT_GRACE_SEC = 15L
        private const val PUBLISH_TIMEOUT_MS = 15_000L
        private const val FRAME_REFRESH_IDLE_MS = 1_000L
        private const val STATS_INTERVAL_SEC = 3L

        @Volatile
        private var webRtcInitialized = false

        @Synchronized
        private fun ensureWebRtcInitialized(context: Context) {
            if (webRtcInitialized) return
            PeerConnectionFactory.initialize(
                PeerConnectionFactory.InitializationOptions.builder(context.applicationContext).createInitializationOptions(),
            )
            webRtcInitialized = true
        }
    }
}
