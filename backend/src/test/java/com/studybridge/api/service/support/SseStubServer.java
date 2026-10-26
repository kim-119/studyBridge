package com.studybridge.api.service.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * AI07 /api/ai/multi-chat/stream 을 흉내 내는 스크립트형 SSE 스텁(JDK HttpServer).
 *  · frames: 순서대로 내보낼 raw SSE 프레임("event: x\ndata: {...}\n\n"). 프레임 사이 delayMs 로 천천히 흘릴 수 있다.
 *  · 요청 헤더/본문을 캡처한다(X-Request-ID / body.requestId 상관 검증).
 *  · 클라이언트가 끊으면 write 가 IOException 으로 실패한다 → clientDisconnected 로 관측(취소 체인 검증).
 */
public final class SseStubServer implements AutoCloseable {

    private final HttpServer server;
    public final List<String> frames = Collections.synchronizedList(new ArrayList<>());
    public volatile long delayMs = 0L;
    public volatile int status = 200;
    public volatile int nonStreamStatus = 200;
    public volatile String errorBody = "{\"detail\":{\"code\":\"STUB\",\"message\":\"stub rejected\"}}";
    public final AtomicInteger hits = new AtomicInteger();
    public final AtomicReference<com.sun.net.httpserver.Headers> lastHeaders = new AtomicReference<>();
    public final AtomicReference<String> lastBody = new AtomicReference<>();
    public final AtomicBoolean clientDisconnected = new AtomicBoolean(false);
    public final AtomicInteger framesWritten = new AtomicInteger();
    public final CountDownLatch disconnectLatch = new CountDownLatch(1);

    public SseStubServer() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/openapi.json", ex -> write(ex, 200, "application/json",
                "{\"paths\":{\"/api/ai/multi-chat/stream\":{},\"/api/ai/multi-chat\":{}}}"));
        server.createContext("/api/ai/multi-chat/stream", this::handleStream);
        server.createContext("/api/ai/multi-chat", ex -> {
            hits.incrementAndGet();
            lastHeaders.set(ex.getRequestHeaders());
            lastBody.set(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            write(ex, nonStreamStatus, "application/json", nonStreamStatus == 200
                    ? "{\"success\":true,\"mode\":\"basic\",\"answers\":[{\"agentId\":7001,\"agentName\":\"교수\",\"answer\":\"non-stream\"}]}"
                    : errorBody);
        });
        server.setExecutor(java.util.concurrent.Executors.newCachedThreadPool());
        server.start();
    }

    private void handleStream(HttpExchange ex) throws IOException {
        hits.incrementAndGet();
        lastHeaders.set(ex.getRequestHeaders());
        lastBody.set(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        if (status != 200) {
            write(ex, status, "application/json", errorBody);
            return;
        }
        ex.getResponseHeaders().add("Content-Type", "text/event-stream");
        ex.sendResponseHeaders(200, 0);
        try (OutputStream os = ex.getResponseBody()) {
            List<String> snapshot;
            synchronized (frames) {
                snapshot = new ArrayList<>(frames);
            }
            for (String f : snapshot) {
                if (delayMs > 0) {
                    try {
                        Thread.sleep(delayMs);
                    } catch (InterruptedException ie) {
                        Thread.currentThread().interrupt();
                        return;
                    }
                }
                os.write(f.getBytes(StandardCharsets.UTF_8));
                os.flush();
                framesWritten.incrementAndGet();
            }
        } catch (IOException e) {
            clientDisconnected.set(true);
            disconnectLatch.countDown();
        }
    }

    public String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    public static String frame(String event, String json) {
        return "event: " + event + "\ndata: " + json + "\n\n";
    }

    private static void write(HttpExchange ex, int status, String ct, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", ct);
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(bytes);
        }
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
