package kr.co.studybridge.app.session

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val KEYSTORE_PROVIDER = "AndroidKeyStore"
private const val KEY_ALIAS = "studybridge_session_key"
private const val PREFERENCES_NAME = "studybridge_secure_session"
private const val REFRESH_TOKEN_KEY = "refresh_token"
private const val ACCESS_TOKEN_KEY = "access_token"
private const val CIPHER_TRANSFORMATION = "AES/GCM/NoPadding"
private const val GCM_TAG_LENGTH_BITS = 128
private const val PAYLOAD_SEPARATOR = ":"
private const val LOG_TAG = "SecureSessionVault"

class SecureSessionVault(context: Context) {

    private val preferences =
        context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun writeRefreshToken(refreshToken: String) {
        preferences.edit().putString(REFRESH_TOKEN_KEY, encrypt(refreshToken)).apply()
    }

    fun readRefreshToken(): String? = readEncrypted(REFRESH_TOKEN_KEY)

    fun writeAccessToken(accessToken: String) {
        preferences.edit().putString(ACCESS_TOKEN_KEY, encrypt(accessToken)).commit()
    }

    fun readAccessToken(): String? = readEncrypted(ACCESS_TOKEN_KEY)

    fun clearAccessToken() {
        preferences.edit().remove(ACCESS_TOKEN_KEY).commit()
    }

    fun clear() {
        preferences.edit().remove(REFRESH_TOKEN_KEY).remove(ACCESS_TOKEN_KEY).apply()
    }

    private fun encrypt(plainText: String): String {
        val cipher = Cipher.getInstance(CIPHER_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, loadOrCreateKey())

        val encrypted = cipher.doFinal(plainText.toByteArray(Charsets.UTF_8))
        return encode(cipher.iv) + PAYLOAD_SEPARATOR + encode(encrypted)
    }

    private fun readEncrypted(preferenceKey: String): String? {
        val payload = preferences.getString(preferenceKey, null) ?: return null
        val parts = payload.split(PAYLOAD_SEPARATOR)

        if (parts.size != 2) {
            preferences.edit().remove(preferenceKey).apply()
            return null
        }

        return try {
            val cipher = Cipher.getInstance(CIPHER_TRANSFORMATION)
            cipher.init(
                Cipher.DECRYPT_MODE,
                loadOrCreateKey(),
                GCMParameterSpec(GCM_TAG_LENGTH_BITS, decode(parts[0]))
            )
            String(cipher.doFinal(decode(parts[1])), Charsets.UTF_8)
        } catch (error: Exception) {
            Log.w(LOG_TAG, "Stored token could not be decrypted and was discarded", error)
            preferences.edit().remove(preferenceKey).apply()
            null
        }
    }

    private fun loadOrCreateKey(): SecretKey {
        val keyStore = KeyStore.getInstance(KEYSTORE_PROVIDER).apply { load(null) }
        val existingKey = keyStore.getKey(KEY_ALIAS, null) as? SecretKey

        if (existingKey != null) return existingKey

        val keyGenerator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE_PROVIDER)
        keyGenerator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return keyGenerator.generateKey()
    }

    private fun encode(bytes: ByteArray): String = Base64.encodeToString(bytes, Base64.NO_WRAP)

    private fun decode(text: String): ByteArray = Base64.decode(text, Base64.NO_WRAP)
}
