package kr.co.studybridge.app.study

import android.content.Intent
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import kr.co.studybridge.app.notification.StudyActionSource
import kr.co.studybridge.app.notification.StudyNotificationChannels
import kr.co.studybridge.app.reminder.ReminderAccountSync
import kr.co.studybridge.app.ui.ReminderSettingsActivity

@CapacitorPlugin(name = "StudyBridgeStudyNative")
class StudyNativePlugin : Plugin() {

    override fun load() {
        StudyNotificationChannels.registerAll(context)
    }

    @PluginMethod
    fun shareSession(call: PluginCall) {
        val accessToken = call.getString("accessToken")
        if (accessToken.isNullOrBlank()) {
            call.reject("accessToken is required")
            return
        }

        val account = StudyRuntime.account(context)
        val previousUserId = account.currentUserId()
        if (account.signIn(accessToken) == SignInOutcome.REJECTED) {
            call.reject("accessToken could not be read")
            return
        }
        val currentUserId = account.currentUserId() ?: run {
            call.reject("accessToken has no user")
            return
        }

        if (previousUserId != currentUserId) {
            forgetPreviousAccountState(previousUserId)
        }
        ReminderAccountSync.scheduleForSignedInUser(context, previousUserId, currentUserId)
        call.resolve()
        syncAfterSignIn()
    }

    @PluginMethod
    fun signOut(call: PluginCall) {
        val account = StudyRuntime.account(context)
        account.currentUserId()?.let { ReminderAccountSync.cancelForUser(context, it) }
        account.signOut()
        StudyRuntime.clearForSignOut(context)
        call.resolve()
    }

    @PluginMethod
    fun openReminderSettings(call: PluginCall) {
        val intent = Intent(context, ReminderSettingsActivity::class.java)
        activity?.startActivity(intent) ?: run {
            call.reject("Activity is not available")
            return
        }
        call.resolve()
    }

    override fun handleOnResume() {
        super.handleOnResume()
        if (StudyRuntime.hasPendingAction(context)) {
            requestFreshAccessTokenForPendingAction()
        } else if (StudyRuntime.hasUsableSession(context)) {
            StudyRuntime.perform(context, StudyAction.REFRESH, StudyActionSource.NOTIFICATION)
        }
    }

    private fun forgetPreviousAccountState(previousUserId: Long?) {
        val statusStore = StudyRuntime.statusStore(context)
        if (previousUserId == null) {
            statusStore.clearSnapshot()
        } else {
            statusStore.clearAll()
        }
    }

    private fun syncAfterSignIn() {
        if (!StudyRuntime.hasUsableSession(context)) {
            requestFreshAccessTokenForPendingAction()
            return
        }
        if (StudyRuntime.hasPendingAction(context)) {
            StudyRuntime.runPendingActionIfFresh(context)
        } else {
            StudyRuntime.perform(context, StudyAction.REFRESH, StudyActionSource.NOTIFICATION)
        }
    }

    private fun requestFreshAccessTokenForPendingAction() {
        if (!StudyRuntime.hasPendingAction(context)) return
        val now = System.currentTimeMillis()
        if (now - lastTokenRequestAtMillis < TOKEN_REQUEST_INTERVAL_MS) return
        lastTokenRequestAtMillis = now
        notifyListeners(EVENT_ACCESS_TOKEN_REQUESTED, JSObject(), true)
    }

    private var lastTokenRequestAtMillis = 0L

    companion object {
        const val EVENT_ACCESS_TOKEN_REQUESTED = "accessTokenRequested"
        private const val TOKEN_REQUEST_INTERVAL_MS = 30_000L
    }
}
