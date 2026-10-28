package kr.co.studybridge.screenshare

import android.Manifest
import android.app.Activity
import android.content.Context
import android.media.projection.MediaProjectionManager
import android.os.Build
import androidx.activity.result.ActivityResult
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback

private const val NOTIFICATIONS_ALIAS = "notifications"

/**
 * WebView ↔ 네이티브 화면공유 브리지. 토큰 발급·슬롯 확인은 JS 가 기존 서버 API 로 하고, 여기서는
 * 시스템 동의 → Foreground Service 시작 → 상태 이벤트(stateChange)만 맡는다.
 */
@CapacitorPlugin(
    name = "StudyBridgeScreenShare",
    permissions = [Permission(alias = NOTIFICATIONS_ALIAS, strings = [Manifest.permission.POST_NOTIFICATIONS])],
)
class ScreenSharePlugin : Plugin() {

    private val statusListener: (ScreenShareStatus) -> Unit = { status ->
        notifyListeners(STATE_EVENT, JSObject.fromJSONObject(status.toJson()), true)
    }

    override fun load() {
        ScreenShareRuntime.addListener(statusListener)
    }

    override fun handleOnDestroy() {
        ScreenShareRuntime.removeListener(statusListener)
        super.handleOnDestroy()
    }

    @PluginMethod
    fun getStatus(call: PluginCall) {
        call.resolve(statusObject())
    }

    /** Android 13+ 알림 권한(공유 중 상태 알림 표시용). 거부해도 화면공유는 시작할 수 있다. */
    @PluginMethod
    fun requestNotificationPermission(call: PluginCall) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU || getPermissionState(NOTIFICATIONS_ALIAS) == PermissionState.GRANTED) {
            call.resolve(JSObject().put("granted", true))
            return
        }
        requestPermissionForAlias(NOTIFICATIONS_ALIAS, call, "onNotificationPermission")
    }

    @PermissionCallback
    private fun onNotificationPermission(call: PluginCall) {
        call.resolve(JSObject().put("granted", getPermissionState(NOTIFICATIONS_ALIAS) == PermissionState.GRANTED))
    }

    /** 시스템 화면 녹화 동의창. 사용자가 전체 화면/단일 앱을 고르며 앱은 그 선택을 바꾸지 않는다. */
    @PluginMethod
    fun requestConsent(call: PluginCall) {
        if (ScreenShareRuntime.status.state.isActive) {
            call.reject("이미 화면을 공유하고 있습니다.", "ALREADY_SHARING")
            return
        }
        val manager = context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as? MediaProjectionManager
        if (manager == null) {
            call.reject("이 기기는 화면공유를 지원하지 않습니다.", "UNSUPPORTED")
            return
        }
        ScreenShareRuntime.discardConsent()
        startActivityForResult(call, manager.createScreenCaptureIntent(), "onConsentResult")
    }

    @ActivityCallback
    private fun onConsentResult(call: PluginCall?, result: ActivityResult) {
        val data = result.data
        val granted = result.resultCode == Activity.RESULT_OK && data != null
        if (granted && data != null) ScreenShareRuntime.storeConsent(result.resultCode, data)
        call?.resolve(JSObject().put("granted", granted))
    }

    /** 동의 직후 서버에서 받은 SCREEN 토큰으로 송출을 시작한다. 동의는 여기서 소모된다(재사용 불가). */
    @PluginMethod
    fun start(call: PluginCall) {
        if (ScreenShareRuntime.status.state.isActive) {
            call.reject("이미 화면을 공유하고 있습니다.", "ALREADY_SHARING")
            return
        }
        val config = call.data
        try {
            ScreenShareConfig.parse(config.toString())
        } catch (error: IllegalArgumentException) {
            call.reject(error.message ?: "화면공유 설정이 올바르지 않습니다.", "INVALID_REQUEST")
            return
        }
        val consent = ScreenShareRuntime.takeConsent()
        if (consent == null) {
            call.reject("화면 녹화 동의가 없거나 만료되었습니다. 다시 시작해 주세요.", "CONSENT_REQUIRED")
            return
        }
        try {
            ScreenShareService.start(context, consent, config.toString())
            call.resolve(JSObject().put("started", true))
        } catch (error: Exception) {
            call.reject("화면공유 서비스를 시작하지 못했습니다.", "SERVICE_START_FAILED", error)
        }
    }

    @PluginMethod
    fun discardConsent(call: PluginCall) {
        ScreenShareRuntime.discardConsent()
        call.resolve()
    }

    @PluginMethod
    fun stop(call: PluginCall) {
        if (ScreenShareRuntime.status.state.isActive) {
            try {
                ScreenShareService.stop(context)
            } catch (error: IllegalStateException) {
                call.reject("화면공유를 종료하지 못했습니다.", "STOP_FAILED", error)
                return
            }
        }
        call.resolve(statusObject())
    }

    private fun statusObject(): JSObject = JSObject.fromJSONObject(ScreenShareRuntime.status.toJson())

    private companion object {
        const val STATE_EVENT = "stateChange"
    }
}
