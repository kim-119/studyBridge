package kr.co.studybridge.app.media

import android.Manifest
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback

private const val MEDIA_PERMISSION_CALLBACK = "onMediaPermissionResult"

@CapacitorPlugin(
    name = "StudyBridgeMedia",
    permissions = [
        Permission(alias = CAMERA_ALIAS, strings = [Manifest.permission.CAMERA]),
        Permission(alias = MICROPHONE_ALIAS, strings = [Manifest.permission.RECORD_AUDIO])
    ]
)
class StudyBridgeMediaPlugin : Plugin() {

    private val voiceSession by lazy { VoiceSessionController(context) }

    @PluginMethod
    fun checkMediaPermissions(call: PluginCall) {
        call.resolve(currentPermissionState())
    }

    @PluginMethod
    fun requestMediaPermissions(call: PluginCall) {
        val aliases = mediaPermissionAliasesToRequest(
            wantsCamera = call.getBoolean(CAMERA_ALIAS, true) ?: true,
            wantsMicrophone = call.getBoolean(MICROPHONE_ALIAS, true) ?: true,
            cameraGranted = isGranted(CAMERA_ALIAS),
            microphoneGranted = isGranted(MICROPHONE_ALIAS)
        )

        if (aliases.isEmpty()) {
            call.resolve(currentPermissionState())
            return
        }

        requestPermissionForAliases(aliases, call, MEDIA_PERMISSION_CALLBACK)
    }

    @PermissionCallback
    private fun onMediaPermissionResult(call: PluginCall) {
        call.resolve(currentPermissionState())
    }

    @PluginMethod
    fun startVoiceSession(call: PluginCall) {
        val useSpeakerphone = call.getBoolean("speakerphone", true) ?: true

        voiceSession.start(activity, useSpeakerphone)
        call.resolve(sessionState())
    }

    @PluginMethod
    fun stopVoiceSession(call: PluginCall) {
        voiceSession.stop(activity)
        call.resolve(sessionState())
    }

    @PluginMethod
    fun setSpeakerphone(call: PluginCall) {
        val enabled = call.getBoolean("enabled", true) ?: true

        voiceSession.applySpeakerphone(enabled)
        call.resolve(sessionState())
    }

    override fun handleOnDestroy() {
        voiceSession.stop(activity)
        super.handleOnDestroy()
    }

    private fun isGranted(alias: String) = getPermissionState(alias) == PermissionState.GRANTED

    private fun currentPermissionState(): JSObject {
        val state = JSObject()
        state.put(CAMERA_ALIAS, getPermissionState(CAMERA_ALIAS).toString())
        state.put(MICROPHONE_ALIAS, getPermissionState(MICROPHONE_ALIAS).toString())
        state.put("granted", isGranted(CAMERA_ALIAS) && isGranted(MICROPHONE_ALIAS))
        return state
    }

    private fun sessionState(): JSObject {
        val state = JSObject()
        state.put("active", voiceSession.isSessionActive())
        state.put("speakerphone", voiceSession.isSpeakerphoneOn())
        return state
    }
}
