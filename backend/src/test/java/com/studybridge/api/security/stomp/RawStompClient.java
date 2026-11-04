package com.studybridge.api.security.stomp;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * 테스트용 원시 STOMP 1.2 클라이언트(JDK WebSocket → SockJS raw 엔드포인트 /ws-group/websocket).
 * 공격자가 보낼 수 있는 임의 프레임(헤더 누락·위조 토큰·와일드카드 구독·/topic 직접 SEND)을 그대로 보낸다.
 */
final class RawStompClient implements WebSocket.Listener, AutoCloseable {

    record Frame(String command, Map<String, String> headers, String body) {
        String header(String name) {
            return headers.get(name);
        }
    }

    private final BlockingQueue<Frame> frames = new LinkedBlockingQueue<>();
    private final CompletableFuture<Integer> closed = new CompletableFuture<>();
    private final StringBuilder buffer = new StringBuilder();
    private WebSocket webSocket;

    static RawStompClient open(int port) {
        RawStompClient client = new RawStompClient();
        client.webSocket = HttpClient.newHttpClient().newWebSocketBuilder()
                .connectTimeout(Duration.ofSeconds(5))
                .buildAsync(URI.create("ws://localhost:" + port + "/ws-group/websocket"), client)
                .join();
        return client;
    }

    RawStompClient connect(String authorizationHeader) {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("accept-version", "1.2");
        headers.put("host", "localhost");
        headers.put("heart-beat", "0,0");
        if (authorizationHeader != null) {
            headers.put("Authorization", authorizationHeader);
        }
        send("CONNECT", headers, "");
        return this;
    }

    void subscribe(String id, String destination) {
        send("SUBSCRIBE", Map.of("id", id, "destination", destination), "");
    }

    void sendJson(String destination, String json) {
        send("SEND", Map.of("destination", destination, "content-type", "application/json"), json);
    }

    void send(String command, Map<String, String> headers, String body) {
        StringBuilder frame = new StringBuilder(command).append('\n');
        headers.forEach((k, v) -> frame.append(k).append(':').append(v).append('\n'));
        frame.append('\n').append(body).append('\0');
        webSocket.sendText(frame.toString(), true).join();
    }

    /** 다음 STOMP 프레임(heartbeat 제외). 시간 안에 없으면 null. */
    Frame next(Duration timeout) throws InterruptedException {
        return frames.poll(timeout.toMillis(), TimeUnit.MILLISECONDS);
    }

    /** 지정 명령 프레임이 올 때까지 다른 프레임은 건너뛴다. */
    Frame nextOf(String command, Duration timeout) throws InterruptedException {
        long deadline = System.nanoTime() + timeout.toNanos();
        while (System.nanoTime() < deadline) {
            Frame frame = frames.poll(Math.max(1, (deadline - System.nanoTime()) / 1_000_000), TimeUnit.MILLISECONDS);
            if (frame != null && frame.command().equals(command)) {
                return frame;
            }
        }
        return null;
    }

    boolean awaitClosed(Duration timeout) {
        try {
            closed.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    boolean isOpen() {
        return !closed.isDone() && !webSocket.isInputClosed();
    }

    @Override
    public void onOpen(WebSocket webSocket) {
        webSocket.request(1);
    }

    @Override
    public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
        synchronized (buffer) {
            buffer.append(data);
            int end;
            while ((end = buffer.indexOf("\0")) >= 0) {
                String raw = buffer.substring(0, end);
                buffer.delete(0, end + 1);
                Frame frame = parse(raw);
                if (frame != null) {
                    frames.add(frame);
                }
            }
        }
        webSocket.request(1);
        return null;
    }

    @Override
    public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
        closed.complete(statusCode);
        return null;
    }

    @Override
    public void onError(WebSocket webSocket, Throwable error) {
        closed.complete(-1);
    }

    private static Frame parse(String raw) {
        String trimmed = raw.replaceFirst("^[\\r\\n]+", ""); // heartbeat 개행 제거
        if (trimmed.isEmpty()) {
            return null;
        }
        int headerEnd = trimmed.indexOf("\n\n");
        String head = headerEnd >= 0 ? trimmed.substring(0, headerEnd) : trimmed;
        String body = headerEnd >= 0 ? trimmed.substring(headerEnd + 2) : "";
        String[] lines = head.split("\n");
        Map<String, String> headers = new LinkedHashMap<>();
        for (int i = 1; i < lines.length; i++) {
            int colon = lines[i].indexOf(':');
            if (colon > 0) {
                headers.putIfAbsent(lines[i].substring(0, colon), lines[i].substring(colon + 1));
            }
        }
        return new Frame(lines[0].trim(), headers, body);
    }

    @Override
    public void close() {
        try {
            if (!closed.isDone()) {
                webSocket.sendClose(WebSocket.NORMAL_CLOSURE, "bye").get(2, TimeUnit.SECONDS);
            }
        } catch (Exception ignored) {
            webSocket.abort();
        }
    }
}
