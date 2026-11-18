package kr.co.studybridge.app.study

import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

enum class StudyApiFailure {
    UNAUTHORIZED,
    NETWORK,
    SERVER,
}

class StudyApiException(val failure: StudyApiFailure, message: String, cause: Throwable? = null) :
    Exception(message, cause)

interface StudyTimerApi {
    fun currentSession(accessToken: String): TimerSession?
    fun startPersonalSession(accessToken: String): TimerSession
    fun endSession(accessToken: String): TimerSession?
    fun todayCompletedSeconds(accessToken: String): Long
}

class HttpStudyTimerApi(private val baseUrl: String) : StudyTimerApi {

    override fun currentSession(accessToken: String): TimerSession? =
        TimerResponseParser.parseSession(request("GET", "/api/timers/current", accessToken, body = null))

    override fun startPersonalSession(accessToken: String): TimerSession {
        val body = request("POST", "/api/timers/start", accessToken, START_PERSONAL_BODY)
        return TimerResponseParser.parseSession(body)
            ?: throw StudyApiException(StudyApiFailure.SERVER, "Start response did not contain a session")
    }

    override fun endSession(accessToken: String): TimerSession? =
        TimerResponseParser.parseSession(request("POST", "/api/timers/end", accessToken, END_BY_USER_BODY))

    override fun todayCompletedSeconds(accessToken: String): Long =
        TimerResponseParser.parseTodaySeconds(request("GET", "/api/study-time/today", accessToken, body = null))

    private fun request(method: String, path: String, accessToken: String, body: String?): String? {
        val connection = try {
            URL(baseUrl.trimEnd('/') + path).openConnection() as HttpURLConnection
        } catch (error: IOException) {
            throw StudyApiException(StudyApiFailure.NETWORK, "Could not open $path", error)
        }

        try {
            connection.requestMethod = method
            connection.connectTimeout = CONNECT_TIMEOUT_MS
            connection.readTimeout = READ_TIMEOUT_MS
            connection.useCaches = false
            connection.setRequestProperty("Authorization", "Bearer $accessToken")
            connection.setRequestProperty("Accept", "application/json")
            if (body != null) {
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
            return readResponse(connection, path)
        } catch (error: IOException) {
            throw StudyApiException(StudyApiFailure.NETWORK, "Network failure on $method $path", error)
        } finally {
            connection.disconnect()
        }
    }

    private fun readResponse(connection: HttpURLConnection, path: String): String? {
        val status = connection.responseCode
        return when {
            status == HttpURLConnection.HTTP_NO_CONTENT -> null
            status in 200..299 -> connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
            status == HttpURLConnection.HTTP_UNAUTHORIZED || status == HttpURLConnection.HTTP_FORBIDDEN ->
                throw StudyApiException(StudyApiFailure.UNAUTHORIZED, "$path rejected the access token ($status)")
            else -> throw StudyApiException(StudyApiFailure.SERVER, "$path failed with HTTP $status")
        }
    }

    companion object {
        private const val CONNECT_TIMEOUT_MS = 6_000
        private const val READ_TIMEOUT_MS = 10_000
        private const val START_PERSONAL_BODY = """{"supportsHeartbeat":false}"""
        private const val END_BY_USER_BODY = """{"reason":"NATIVE_USER_STOP"}"""
    }
}
