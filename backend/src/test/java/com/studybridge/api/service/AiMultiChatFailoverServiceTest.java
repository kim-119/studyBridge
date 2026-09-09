package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverSettings;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 실제 HTTP(JDK HttpServer 스텁)로 PRIMARY→SECONDARY→non-stream failover 정책을 검증한다.
 * 어떤 시나리오에서도 반환 Flux 는 error 로 끝나지 않고 마지막 이벤트는 done 이어야 한다(500·premature close 금지).
 */
class AiMultiChatFailoverServiceTest {

    private final List<HttpServer> servers = new ArrayList<>();

    @AfterEach
    void tearDown() {
        for (HttpServer s : servers) {
            s.stop(0);
        }
    }

    // ── 스텁 서버 ─────────────────────────────────────────────────────────────

    /** stream/non-stream/openapi 응답을 상황별로 정의하는 간단한 FastAPI 스텁. */
    private static final class Stub {
        final HttpServer server;
        final AtomicInteger streamHits = new AtomicInteger();
        final AtomicInteger nonStreamHits = new AtomicInteger();
        int streamStatus = 200;
        int nonStreamStatus = 200;
        boolean openapiHasStream = true;
        boolean streamFatalErrorEvent = false;
        String name;

        Stub(String name) throws IOException {
            this.name = name;
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/openapi.json", ex -> {
                String body = openapiHasStream
                        ? "{\"paths\":{\"/api/ai/multi-chat/stream\":{},\"/api/ai/multi-chat\":{}}}"
                        : "{\"paths\":{\"/api/ai/multi-chat\":{}}}";
                write(ex, 200, "application/json", body);
            });
            server.createContext("/api/ai/multi-chat/stream", ex -> {
                streamHits.incrementAndGet();
                if (streamStatus != 200) {
                    write(ex, streamStatus, "application/json", "{\"detail\":\"stub " + streamStatus + "\"}");
                    return;
                }
                StringBuilder sb = new StringBuilder();
                sb.append("event: turn_start\ndata: {\"type\":\"turn_start\"}\n\n");
                sb.append("event: agent_answer\ndata: {\"type\":\"agent_answer\",\"agentIndex\":1,\"agentName\":\"교수\",\"answer\":\"from ")
                        .append(name).append("\"}\n\n");
                if (streamFatalErrorEvent) {
                    sb.append("event: error\ndata: {\"type\":\"error\",\"message\":\"boom\"}\n\n");
                    sb.append("event: done\ndata: {\"type\":\"done\",\"status\":\"error\"}\n\n");
                } else {
                    sb.append("event: all_complete\ndata: {\"type\":\"all_complete\",\"answers\":[{\"agentName\":\"교수\",\"answer\":\"from ")
                            .append(name).append("\"}],\"status\":\"COMPLETED\"}\n\n");
                    sb.append("event: done\ndata: {\"type\":\"done\",\"status\":\"done\"}\n\n");
                }
                byte[] bytes = sb.toString().getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "text/event-stream");
                ex.sendResponseHeaders(200, bytes.length);
                try (OutputStream os = ex.getResponseBody()) {
                    os.write(bytes);
                }
            });
            server.createContext("/api/ai/multi-chat", ex -> {
                nonStreamHits.incrementAndGet();
                if (nonStreamStatus != 200) {
                    write(ex, nonStreamStatus, "application/json", "{\"detail\":\"stub " + nonStreamStatus + "\"}");
                    return;
                }
                write(ex, 200, "application/json",
                        "{\"success\":true,\"mode\":\"multi_agent_discussion\",\"answers\":[{\"agentName\":\"교수\",\"answer\":\"non-stream from "
                                + name + "\"}]}");
            });
            server.start();
        }

        String baseUrl() {
            return "http://127.0.0.1:" + server.getAddress().getPort();
        }

        private static void write(HttpExchange ex, int status, String ct, String body) throws IOException {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", ct);
            ex.sendResponseHeaders(status, bytes.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(bytes);
            }
        }
    }


    /** 헤더+이벤트 일부를 chunked 로 보낸 뒤 종료 청크 없이 소켓을 끊는 서버 → 클라이언트는 premature close 를 본다. */
    private static final class RawPrematureServer implements AutoCloseable {
        final ServerSocket ss;
        final AtomicInteger hits = new AtomicInteger();
        final Thread th;
        volatile boolean running = true;

        RawPrematureServer() throws IOException {
            ss = new ServerSocket(0, 8, java.net.InetAddress.getByName("127.0.0.1"));
            th = new Thread(() -> {
                while (running) {
                    try (java.net.Socket sock = ss.accept()) {
                        hits.incrementAndGet();
                        java.io.InputStream in = sock.getInputStream();
                        // 요청 헤더/바디를 대충 읽고(블로킹 방지용 짧은 타임아웃) 응답 시작
                        sock.setSoTimeout(300);
                        byte[] buf = new byte[8192];
                        try { while (in.read(buf) > 0) { /* drain */ } } catch (java.net.SocketTimeoutException ignored) { }
                        OutputStream os = sock.getOutputStream();
                        String head = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n";
                        String body = "event: turn_start\ndata: {\"type\":\"turn_start\"}\n\n"
                                + "event: agent_answer\ndata: {\"type\":\"agent_answer\",\"agentIndex\":1,\"answer\":\"partial from primary\"}\n\n";
                        byte[] b = body.getBytes(StandardCharsets.UTF_8);
                        os.write(head.getBytes(StandardCharsets.UTF_8));
                        os.write((Integer.toHexString(b.length) + "\r\n").getBytes(StandardCharsets.UTF_8));
                        os.write(b);
                        os.write("\r\n".getBytes(StandardCharsets.UTF_8));
                        os.flush();
                        Thread.sleep(150);
                        // 종료 청크(0\r\n\r\n) 없이 끊는다.
                    } catch (Exception ignored) {
                    }
                }
            }, "raw-premature");
            th.setDaemon(true);
            th.start();
        }

        String baseUrl() {
            return "http://127.0.0.1:" + ss.getLocalPort();
        }

        @Override
        public void close() throws IOException {
            running = false;
            ss.close();
        }
    }

    private Stub stub(String name) throws IOException {
        Stub s = new Stub(name);
        servers.add(s.server);
        return s;
    }

    private static String deadUrl() throws IOException {
        try (ServerSocket ss = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))) {
            return "http://127.0.0.1:" + ss.getLocalPort();
        }
    }

    private static AiMultiChatFailoverService service(String primaryUrl, String secondaryUrl) {
        List<AiUpstream> ups = new ArrayList<>();
        ups.add(new AiUpstream("primary", primaryUrl, WebClient.create(primaryUrl)));
        if (secondaryUrl != null) {
            ups.add(new AiUpstream("secondary", secondaryUrl, WebClient.create(secondaryUrl)));
        }
        AiFailoverSettings settings = AiFailoverSettings.defaults()
                .attemptsPerUpstream(2)
                .backoff(Duration.ofMillis(30))
                .circuitCooldown(Duration.ofSeconds(2))
                .streamIdleTimeout(Duration.ofSeconds(5))
                .totalTimeout(Duration.ofSeconds(60))
                .probeEnabled(false);
        return new AiMultiChatFailoverService(new AiUpstreams(ups), new ObjectMapper(), settings);
    }

    private static List<ServerSentEvent<String>> run(AiMultiChatFailoverService svc) {
        return svc.streamMultiChat(1L, "req_test", Map.of("message", "hi", "agents", List.of()), Duration.ofSeconds(10))
                .collectList()
                .block(Duration.ofSeconds(30));
    }

    private static List<String> events(List<ServerSentEvent<String>> evs) {
        List<String> out = new ArrayList<>();
        for (ServerSentEvent<String> e : evs) {
            out.add(e.event());
        }
        return out;
    }

    private static ServerSentEvent<String> find(List<ServerSentEvent<String>> evs, String name) {
        for (ServerSentEvent<String> e : evs) {
            if (name.equals(e.event())) {
                return e;
            }
        }
        return null;
    }

    // ── 시나리오 ──────────────────────────────────────────────────────────────

    @Test
    void primaryHealthy_streamsFromPrimary_andEndsWithSpringDone() throws IOException {
        Stub p = stub("primary");
        Stub s = stub("secondary");
        List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

        assertEquals(List.of("turn_start", "agent_answer", "all_complete", "done"), events(evs));
        assertTrue(find(evs, "all_complete").data().contains("from primary"));
        assertTrue(find(evs, "done").data().contains("\"upstream\":\"primary\""));
        assertEquals(0, s.streamHits.get(), "secondary 는 호출되지 않아야 한다");
    }

    @Test
    void primaryStream404_failsOverToSecondaryStream() throws IOException {
        Stub p = stub("primary");
        p.streamStatus = 404; // ai07 구버전 회귀 재현
        Stub s = stub("secondary");
        List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

        assertEquals(List.of("turn_start", "agent_answer", "all_complete", "done"), events(evs));
        assertTrue(find(evs, "all_complete").data().contains("from secondary"));
        assertEquals(2, p.streamHits.get(), "동일 대상 최대 2회 시도 후 넘어가야 한다");
        assertEquals(1, s.streamHits.get());
        assertEquals(0, p.nonStreamHits.get(), "secondary stream 성공 시 non-stream 폴백은 불필요");
    }

    @Test
    void primaryConnectionRefused_noSecondary_endsWithErrorAndDone_notException() throws IOException {
        String dead = deadUrl(); // connection refused (ai07 restart 중)
        List<ServerSentEvent<String>> evs = run(service(dead, null));

        assertEquals(List.of("error", "done"), events(evs));
        assertTrue(find(evs, "error").data().contains("AI_UPSTREAM_UNAVAILABLE"));
        assertTrue(find(evs, "done").data().contains("\"status\":\"error\""));
    }

    @Test
    void allStreamsDown_fallsBackToNonStream_convertedToAllComplete() throws IOException {
        Stub p = stub("primary");
        p.streamStatus = 404;
        Stub s = stub("secondary");
        s.streamStatus = 503;
        List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

        assertEquals(List.of("all_complete", "done"), events(evs));
        String ac = find(evs, "all_complete").data();
        assertTrue(ac.contains("non-stream from primary"));
        assertTrue(ac.contains("\"fallback\""));
        assertTrue(ac.contains("\"status\":\"COMPLETED\""));
        assertTrue(find(evs, "done").data().contains("\"status\":\"done\""));
    }

    @Test
    void prematureClose_midStream_failsOverToSecondary() throws IOException {
        try (RawPrematureServer p = new RawPrematureServer()) { // all_complete 전에 소켓이 끊김(ai07 restart 중)
            Stub s = stub("secondary");
            List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

            List<String> names = events(evs);
            assertEquals("done", names.get(names.size() - 1));
            assertNotNull(find(evs, "all_complete"));
            assertTrue(find(evs, "all_complete").data().contains("from secondary"));
            assertEquals(1, names.stream().filter("turn_start"::equals).count(), "후순위 업스트림의 turn_start 는 중복 제거");
            assertEquals(1, p.hits.get(), "이벤트를 이미 흘린 뒤에는 같은 대상 재시도 없이 다음 대상으로");
            assertTrue(find(evs, "done").data().contains("\"status\":\"done\""));
        }
    }

    @Test
    void upstreamFatalErrorEvent_failsOverInsteadOfRelayingError() throws IOException {
        Stub p = stub("primary");
        p.streamFatalErrorEvent = true;
        Stub s = stub("secondary");
        List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

        assertFalse(events(evs).contains("error"), "대상 미특정 fatal error 는 중계하지 않고 failover");
        assertTrue(find(evs, "all_complete").data().contains("from secondary"));
    }

    @Test
    void contractFailure422_isNotHiddenByFailover() throws IOException {
        Stub p = stub("primary");
        p.streamStatus = 422;
        Stub s = stub("secondary");
        List<ServerSentEvent<String>> evs = run(service(p.baseUrl(), s.baseUrl()));

        assertEquals(List.of("error", "done"), events(evs));
        assertTrue(find(evs, "error").data().contains("AI_CONTRACT_FAILURE"));
        assertEquals(1, p.streamHits.get(), "계약 오류는 재시도하지 않는다");
        assertEquals(0, s.streamHits.get(), "계약 오류는 다른 서버로 숨기지 않는다");
        assertEquals(0, p.nonStreamHits.get());
    }

    @Test
    void routeProbe_marksMissingStreamRouteNotReady_andSkipsPrimaryStream() throws IOException, InterruptedException {
        Stub p = stub("primary");
        p.openapiHasStream = false; // 구버전 회귀: openapi 에 stream 라우트 없음
        p.streamStatus = 404;
        Stub s = stub("secondary");
        AiMultiChatFailoverService svc = service(p.baseUrl(), s.baseUrl());
        svc.probeAll();
        long deadline = System.currentTimeMillis() + 5000;
        while (System.currentTimeMillis() < deadline
                && !"NOT_READY".equals(((Map<?, ?>) svc.snapshot().get("primary")).get("routeReadiness"))) {
            Thread.sleep(50);
        }
        assertEquals("NOT_READY", ((Map<?, ?>) svc.snapshot().get("primary")).get("routeReadiness"));
        assertEquals("READY", ((Map<?, ?>) svc.snapshot().get("secondary")).get("routeReadiness"));

        List<ServerSentEvent<String>> evs = run(svc);
        assertTrue(find(evs, "all_complete").data().contains("from secondary"));
        assertEquals(0, p.streamHits.get(), "NOT_READY 업스트림의 stream 은 시도조차 하지 않는다");
    }

    @Test
    void circuitRecovers_primaryUsedAgainAfterCooldown() throws IOException, InterruptedException {
        Stub p = stub("primary");
        p.streamStatus = 503;
        Stub s = stub("secondary");
        AiMultiChatFailoverService svc = service(p.baseUrl(), s.baseUrl());

        run(svc); // primary 실패 → circuit open
        assertEquals(Boolean.TRUE, ((Map<?, ?>) svc.snapshot().get("primary")).get("circuitOpen"));
        int hitsAfterFirst = p.streamHits.get();
        run(svc); // cooldown 중: primary 건너뜀
        assertEquals(hitsAfterFirst, p.streamHits.get(), "circuit open 동안 primary stream 미호출");

        p.streamStatus = 200; // ai07 복구
        Thread.sleep(2300);   // cooldown(2s) 경과
        List<ServerSentEvent<String>> evs = run(svc);
        assertTrue(find(evs, "all_complete").data().contains("from primary"), "수동 조치 없이 PRIMARY 로 자동 복귀");
        assertEquals(Boolean.FALSE, ((Map<?, ?>) svc.snapshot().get("primary")).get("circuitOpen"));
    }

    @Test
    void callMultiChat_nonStream_failsOverPrimaryToSecondary() throws IOException {
        Stub p = stub("primary");
        p.nonStreamStatus = 502;
        Stub s = stub("secondary");
        Map<String, Object> resp = service(p.baseUrl(), s.baseUrl())
                .callMultiChat(1L, "req_ns", Map.of("message", "hi"), Duration.ofSeconds(10))
                .block(Duration.ofSeconds(20));
        assertNotNull(resp);
        assertTrue(String.valueOf(resp.get("answers")).contains("non-stream from secondary"));
    }
}
