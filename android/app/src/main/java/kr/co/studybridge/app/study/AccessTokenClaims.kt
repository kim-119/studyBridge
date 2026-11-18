package kr.co.studybridge.app.study

import org.json.JSONException
import org.json.JSONObject

data class AccessTokenClaims(
    val userId: Long,
    val expiresAtMillis: Long,
) {
    fun isUsableAt(nowMillis: Long): Boolean = nowMillis + EXPIRY_SAFETY_MARGIN_MS < expiresAtMillis

    companion object {
        private const val EXPIRY_SAFETY_MARGIN_MS = 60_000L
        private const val MILLIS_PER_SECOND = 1000L

        fun parse(accessToken: String, decodeBase64Url: (String) -> ByteArray): AccessTokenClaims? {
            val segments = accessToken.split('.')
            if (segments.size != 3) return null

            return try {
                val payload = JSONObject(String(decodeBase64Url(segments[1]), Charsets.UTF_8))
                val userId = payload.optLong("userId", 0L)
                val expiresAtSeconds = payload.optLong("exp", 0L)
                if (userId <= 0L || expiresAtSeconds <= 0L) {
                    null
                } else {
                    AccessTokenClaims(userId, expiresAtSeconds * MILLIS_PER_SECOND)
                }
            } catch (error: JSONException) {
                null
            } catch (error: IllegalArgumentException) {
                null
            }
        }
    }
}
