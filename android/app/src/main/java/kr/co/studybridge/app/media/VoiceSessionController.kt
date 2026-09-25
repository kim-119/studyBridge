package kr.co.studybridge.app.media

import android.app.Activity
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.os.Build
import android.view.WindowManager

class VoiceSessionController(private val context: Context) {

    private val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager

    private var focusRequest: AudioFocusRequest? = null
    private var previousAudioMode: Int = AudioManager.MODE_NORMAL
    private var previousSpeakerphoneOn: Boolean = false
    private var isActive: Boolean = false

    fun start(activity: Activity?, useSpeakerphone: Boolean) {
        if (isActive) {
            applySpeakerphone(useSpeakerphone)
            return
        }

        previousAudioMode = audioManager.mode
        @Suppress("DEPRECATION")
        previousSpeakerphoneOn = audioManager.isSpeakerphoneOn

        requestAudioFocus()
        audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
        applySpeakerphone(useSpeakerphone)
        keepScreenOn(activity, true)

        isActive = true
    }

    fun stop(activity: Activity?) {
        if (!isActive) return

        keepScreenOn(activity, false)
        abandonAudioFocus()
        audioManager.mode = previousAudioMode
        applySpeakerphone(previousSpeakerphoneOn)

        isActive = false
    }

    fun applySpeakerphone(enabled: Boolean) {
        @Suppress("DEPRECATION")
        audioManager.isSpeakerphoneOn = enabled
    }

    fun isSpeakerphoneOn(): Boolean {
        @Suppress("DEPRECATION")
        return audioManager.isSpeakerphoneOn
    }

    fun isSessionActive(): Boolean = isActive

    private fun requestAudioFocus() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val attributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                .build()

            val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN)
                .setAudioAttributes(attributes)
                .build()

            focusRequest = request
            audioManager.requestAudioFocus(request)
        } else {
            @Suppress("DEPRECATION")
            audioManager.requestAudioFocus(
                null,
                AudioManager.STREAM_VOICE_CALL,
                AudioManager.AUDIOFOCUS_GAIN
            )
        }
    }

    private fun abandonAudioFocus() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            focusRequest?.let { audioManager.abandonAudioFocusRequest(it) }
            focusRequest = null
        } else {
            @Suppress("DEPRECATION")
            audioManager.abandonAudioFocus(null)
        }
    }

    private fun keepScreenOn(activity: Activity?, enabled: Boolean) {
        val target = activity ?: return

        target.runOnUiThread {
            if (enabled) {
                target.window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            } else {
                target.window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            }
        }
    }
}
