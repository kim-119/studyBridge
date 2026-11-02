package kr.co.studybridge.app.study

import android.content.Context
import android.util.Base64
import kr.co.studybridge.app.session.SecureSessionVault

data class AuthorizedUser(val userId: Long, val accessToken: String)

interface StudyCredentials {
    fun authorizedUser(nowMillis: Long): AuthorizedUser?
}

enum class SignInOutcome {
    SAME_USER,
    NEW_USER,
    REJECTED,
}

class StudyAccount(context: Context) : StudyCredentials {

    private val vault = SecureSessionVault(context)
    private val preferences = context.applicationContext
        .getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    @Synchronized
    fun signIn(accessToken: String): SignInOutcome {
        val claims = parseClaims(accessToken) ?: return SignInOutcome.REJECTED
        val previousUserId = currentUserId()

        vault.writeAccessToken(accessToken)
        preferences.edit().putLong(USER_ID_KEY, claims.userId).commit()

        return if (previousUserId == claims.userId) SignInOutcome.SAME_USER else SignInOutcome.NEW_USER
    }

    @Synchronized
    fun signOut() {
        vault.clearAccessToken()
        preferences.edit().remove(USER_ID_KEY).commit()
    }

    @Synchronized
    fun currentUserId(): Long? {
        val userId = preferences.getLong(USER_ID_KEY, NO_USER)
        return if (userId == NO_USER) null else userId
    }

    @Synchronized
    override fun authorizedUser(nowMillis: Long): AuthorizedUser? {
        val userId = currentUserId() ?: return null
        val accessToken = vault.readAccessToken() ?: return null
        val claims = parseClaims(accessToken) ?: return null
        if (claims.userId != userId || !claims.isUsableAt(nowMillis)) return null
        return AuthorizedUser(userId, accessToken)
    }

    private fun parseClaims(accessToken: String): AccessTokenClaims? =
        AccessTokenClaims.parse(accessToken) { segment ->
            Base64.decode(segment, Base64.URL_SAFE or Base64.NO_PADDING or Base64.NO_WRAP)
        }

    companion object {
        private const val PREFERENCES_NAME = "studybridge_study_account"
        private const val USER_ID_KEY = "user_id"
        private const val NO_USER = -1L
    }
}
