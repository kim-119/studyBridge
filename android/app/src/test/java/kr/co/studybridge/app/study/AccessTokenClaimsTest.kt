package kr.co.studybridge.app.study

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class AccessTokenClaimsTest {

    private val decoder: (String) -> ByteArray = { Base64.getUrlDecoder().decode(it) }

    private fun token(payloadJson: String): String {
        val encoder = Base64.getUrlEncoder().withoutPadding()
        val header = encoder.encodeToString("""{"alg":"HS256"}""".toByteArray())
        val payload = encoder.encodeToString(payloadJson.toByteArray())
        return "$header.$payload.signature"
    }

    @Test
    fun readsUserIdAndExpiry() {
        val claims = AccessTokenClaims.parse(token("""{"sub":"a@b.c","userId":95,"exp":1793156400}"""), decoder)!!

        assertEquals(95L, claims.userId)
        assertEquals(1_793_156_400_000L, claims.expiresAtMillis)
    }

    @Test
    fun tokenIsNotUsedWithinOneMinuteOfExpiry() {
        val claims = AccessTokenClaims(userId = 1, expiresAtMillis = 1_000_000L)

        assertTrue(claims.isUsableAt(1_000_000L - 120_000L))
        assertFalse(claims.isUsableAt(1_000_000L - 30_000L))
        assertFalse(claims.isUsableAt(1_000_001L))
    }

    @Test
    fun malformedTokensAreRejected() {
        assertNull(AccessTokenClaims.parse("abc", decoder))
        assertNull(AccessTokenClaims.parse("a.b.c", decoder))
        assertNull(AccessTokenClaims.parse(token("""{"sub":"a@b.c","exp":1793156400}"""), decoder))
        assertNull(AccessTokenClaims.parse(token("""{"userId":3}"""), decoder))
        assertNull(AccessTokenClaims.parse(token("not json"), decoder))
    }
}
