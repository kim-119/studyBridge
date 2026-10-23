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
private const val CIPHER_TRANSFORMATION = "AES/GCM/NoPadding"
private const val GCM_TAG_LENGTH_BITS = 128
private const val PAYLOAD_SEPARATOR = ":"
private const val LOG_TAG = "SecureSessionVault"

class SecureSessionVault(context: Context) {

    private val preferences =
        context.applicationContext.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    fun writeRefreshToken(refreshToken: String) {
        val cipher = Cipher.getInstance(CIPHER_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, loadOrCreateKey())

        val encrypted = cipher.doFinal(refreshToken.toByteArray(Charsets.UTF_8))
        val payload = encode(cipher.iv) + PAYLOAD_SEPARATOR + encode(encrypted)

        preferences.edit().putString(REFRESH_TOKEN_KEY, payload).apply()
    }

    fun readRefreshToken(): String? {
        val payload = preferences.getString(REFRESH_TOKEN_KEY, null) ?: return null
        val parts = payload.split(PAYLOAD_SEPARATOR)

        if (parts.size != 2) {
            clear()
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
            Log.w(LOG_TAG, "Stored refresh token could not be decrypted and was discarded", error)
            clear()
            null
        }
    }

    fun clear() {
        preferences.edit().remove(REFRESH_TOKEN_KEY).apply()
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
