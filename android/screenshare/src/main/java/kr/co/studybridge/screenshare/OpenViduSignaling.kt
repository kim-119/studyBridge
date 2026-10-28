package kr.co.studybridge.screenshare

import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.ScheduledFuture
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * OpenVidu WebSocket JSON-RPC 클라이언트(SCREEN Connection 전용). 모든 콜백은 [worker] 에서 실행된다.
 * ping 이 연속 [MAX_MISSED_PINGS] 번 응답하지 않으면 연결이 끊긴 것으로 본다.
 */
internal class OpenViduSignaling(
    private val url: String,
    private val worker: ScheduledExecutorService,
    private val listener: Listener,
) {
    interface Listener {
        fun onOpen()
        fun onNotification(method: String, params: JSONObject)
        fun onClosed(byServer: Boolean, detail: String)
    }

    private class Pending(val callback: (JSONObject?, RpcError?) -> Unit, val timeout: ScheduledFuture<*>)

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    private val ids = AtomicInteger(0)
    private val pending = ConcurrentHashMap<Int, Pending>()
    private val closed = AtomicBoolean(false)
    private val missedPings = AtomicInteger(0)
    private var socket: WebSocket? = null
    private var pingTask: ScheduledFuture<*>? = null
    private var firstPing = true

    fun connect() {
        socket = client.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                post {
                    startPing()
                    listener.onOpen()
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                post { handle(OpenViduProtocol.parse(text)) }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                webSocket.close(1000, null)
                post { lost(byServer = true, detail = "closing $code") }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                post { lost(byServer = true, detail = "closed $code") }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                post { lost(byServer = false, detail = t.javaClass.simpleName) }
            }
        })
    }

    fun request(method: String, params: JSONObject?, timeoutMs: Long = 10_000, callback: (JSONObject?, RpcError?) -> Unit) {
        if (closed.get()) {
            callback(null, RpcError(-1, "연결이 닫혔습니다."))
            return
        }
        val id = ids.incrementAndGet()
        val timeout = worker.schedule({
            pending.remove(id)?.callback?.invoke(null, RpcError(-2, "$method 응답 시간이 초과되었습니다."))
        }, timeoutMs, TimeUnit.MILLISECONDS)
        pending[id] = Pending(callback, timeout)
        val sent = socket?.send(OpenViduProtocol.request(id, method, params)) ?: false
        if (!sent) {
            pending.remove(id)?.let {
                it.timeout.cancel(false)
                it.callback(null, RpcError(-1, "$method 를 보내지 못했습니다."))
            }
        }
    }

    /** 응답을 기다리지 않는 마지막 요청(leaveRoom 등) 후 정상 종료. 여러 번 불러도 한 번만 닫는다. */
    fun close(finalMethod: String? = null) {
        if (!closed.compareAndSet(false, true)) return
        pingTask?.cancel(false)
        if (finalMethod != null) socket?.send(OpenViduProtocol.request(ids.incrementAndGet(), finalMethod, null))
        socket?.close(1000, "screen share finished")
        failPending("연결을 닫았습니다.")
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    private fun handle(message: RpcMessage) {
        when (message) {
            is RpcMessage.Response -> pending.remove(message.id)?.let {
                it.timeout.cancel(false)
                it.callback(message.result, message.error)
            }
            is RpcMessage.Notification -> listener.onNotification(message.method, message.params)
            RpcMessage.Invalid -> Log.w(TAG, "ignored malformed OpenVidu message")
        }
    }

    private fun startPing() {
        pingTask = worker.scheduleWithFixedDelay({ sendPing() }, 0, OpenViduProtocol.PING_INTERVAL_MS, TimeUnit.MILLISECONDS)
    }

    private fun sendPing() {
        if (closed.get()) return
        val params = OpenViduProtocol.pingParams(firstPing)
        firstPing = false
        request("ping", params, OpenViduProtocol.PING_INTERVAL_MS) { _, error ->
            if (error == null) {
                missedPings.set(0)
            } else if (missedPings.incrementAndGet() >= MAX_MISSED_PINGS) {
                lost(byServer = false, detail = "ping timeout")
            }
        }
    }

    private fun lost(byServer: Boolean, detail: String) {
        if (!closed.compareAndSet(false, true)) return
        pingTask?.cancel(false)
        failPending("연결이 끊겼습니다.")
        socket?.cancel()
        client.dispatcher.executorService.shutdown()
        listener.onClosed(byServer, detail)
    }

    private fun failPending(message: String) {
        val entries = pending.values.toList()
        pending.clear()
        entries.forEach {
            it.timeout.cancel(false)
            it.callback(null, RpcError(-1, message))
        }
    }

    private fun post(block: () -> Unit) {
        try {
            worker.execute(block)
        } catch (_: RejectedExecutionException) {
            // 송출이 이미 정리돼 작업 스레드가 닫혔다.
        }
    }

    private companion object {
        const val TAG = "SBScreenSignaling"
        const val MAX_MISSED_PINGS = 3
    }
}
