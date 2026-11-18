package kr.co.studybridge.screenshare

import android.content.Context
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.projection.MediaProjection
import android.os.SystemClock
import android.view.Surface
import org.webrtc.CapturerObserver
import org.webrtc.SurfaceTextureHelper
import org.webrtc.VideoCapturer
import org.webrtc.VideoFrame
import org.webrtc.VideoSink

/**
 * MediaProjection 전체 디스플레이(또는 사용자가 시스템 선택창에서 고른 범위)를 WebRTC 프레임으로 넘긴다.
 *
 *  · VirtualDisplay 는 한 번만 만든다. Android 14+ 는 같은 MediaProjection 으로 createVirtualDisplay 를 다시 부르면 거부하므로
 *    회전·해상도 변경은 [changeCaptureFormat] 에서 resize 로 처리한다.
 *  · 화면이 멈춰 있으면 VirtualDisplay 가 새 프레임을 내지 않는다 → 새로 들어온 시청자도 첫 화면을 받도록 마지막 프레임을 다시 보낸다.
 *  · FLAG_SECURE 등 캡처가 금지된 화면은 시스템이 검게 내보내며, 여기서 우회하지 않는다.
 */
internal class DisplayCapturer(
    private val projection: MediaProjection,
    private val densityDpi: Int,
) : VideoCapturer, VideoSink {

    private var helper: SurfaceTextureHelper? = null
    private var observer: CapturerObserver? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var surface: Surface? = null
    private var width = 0
    private var height = 0

    @Volatile
    private var lastFrameAt = 0L

    @Volatile
    private var disposed = false

    override fun initialize(surfaceTextureHelper: SurfaceTextureHelper, context: Context, capturerObserver: CapturerObserver) {
        helper = surfaceTextureHelper
        observer = capturerObserver
    }

    override fun startCapture(width: Int, height: Int, framerate: Int) {
        check(!disposed) { "capturer disposed" }
        val textureHelper = checkNotNull(helper) { "capturer not initialized" }
        this.width = width
        this.height = height
        textureHelper.setTextureSize(width, height)
        val captureSurface = Surface(textureHelper.surfaceTexture)
        surface = captureSurface
        virtualDisplay = projection.createVirtualDisplay(
            "StudyBridgeScreenShare",
            width,
            height,
            densityDpi,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            captureSurface,
            null,
            null,
        )
        observer?.onCapturerStarted(virtualDisplay != null)
        textureHelper.startListening(this)
    }

    override fun stopCapture() {
        val textureHelper = helper ?: return
        textureHelper.stopListening()
        virtualDisplay?.release()
        virtualDisplay = null
        surface?.release()
        surface = null
        observer?.onCapturerStopped()
    }

    override fun changeCaptureFormat(width: Int, height: Int, framerate: Int) {
        val textureHelper = helper ?: return
        if (disposed || (width == this.width && height == this.height)) return
        this.width = width
        this.height = height
        textureHelper.handler.post {
            if (disposed) return@post
            textureHelper.setTextureSize(width, height)
            virtualDisplay?.resize(width, height, densityDpi)
        }
    }

    override fun dispose() {
        disposed = true
    }

    override fun isScreencast(): Boolean = true

    override fun onFrame(frame: VideoFrame) {
        lastFrameAt = SystemClock.elapsedRealtime()
        observer?.onFrameCaptured(frame)
    }

    /** 일정 시간 새 프레임이 없으면 마지막 프레임을 다시 보낸다(정지 화면·새 시청자 대비). */
    fun refreshIfIdle(idleMs: Long) {
        val textureHelper = helper ?: return
        if (disposed || virtualDisplay == null) return
        if (SystemClock.elapsedRealtime() - lastFrameAt >= idleMs) textureHelper.forceFrame()
    }
}
