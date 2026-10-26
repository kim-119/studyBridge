package kr.co.studybridge.app.session

import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin

@CapacitorPlugin(name = "StudyBridgeSecureSession")
class SecureSessionPlugin : Plugin() {

    private val vault by lazy { SecureSessionVault(context) }

    @PluginMethod
    fun readRefreshToken(call: PluginCall) {
        val result = JSObject()
        result.put("refreshToken", vault.readRefreshToken())
        call.resolve(result)
    }

    @PluginMethod
    fun writeRefreshToken(call: PluginCall) {
        val refreshToken = call.getString("refreshToken")

        if (refreshToken.isNullOrBlank()) {
            call.reject("refreshToken is required")
            return
        }

        try {
            vault.writeRefreshToken(refreshToken)
            call.resolve()
        } catch (error: Exception) {
            call.reject("Failed to store the refresh token", error)
        }
    }

    @PluginMethod
    fun clear(call: PluginCall) {
        vault.clear()
        call.resolve()
    }
}
