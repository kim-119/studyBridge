package com.studybridge.api.service.support;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import io.netty.channel.ChannelOption;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * PRIMARY/SECONDARY FastAPI 스텁(JDK HttpServer, 실제 TCP). 경로별 상태/본문/지연을 지정하고
 * 호출 횟수·Authorization 헤더를 기록한다. {@link #refusedClient()} 는 닫힌 포트를 가리키는 클라이언트(connection refused).
 */
public final class FailoverStubServer implements AutoCloseable {

    public final HttpServer server;
    public final AtomicInteger hits = new AtomicInteger();
    public final List<String> authorizationHeaders = new CopyOnWriteArrayList<>();
    public final List<String> requestBodies = new CopyOnWriteArrayList<>();
    public volatile int status = 200;
    public volatile String body = "{}";
    public volatile long delayMs = 0;

    public FailoverStubServer(String path) throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext(path, this::handle);
        server.start();
    }

    private void handle(HttpExchange ex) throws IOException {
        hits.incrementAndGet();
        authorizationHeaders.add(ex.getRequestHeaders().getFirst("Authorization"));
        requestBodies.add(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
        if (delayMs > 0) {
            try { Thread.sleep(delayMs); } catch (InterruptedException ignored) { Thread.currentThread().interrupt(); }
        }
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.sendResponseHeaders(status, bytes.length);
        try (OutputStream os = ex.getResponseBody()) { os.write(bytes); }
    }

    public String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    /** 응답 타임아웃 responseTimeoutSeconds 를 가진 WebClient(운영 WebClientConfig 와 같은 Reactor Netty 커넥터). */
    public WebClient client(int responseTimeoutSeconds) {
        return client(baseUrl(), responseTimeoutSeconds);
    }

    public static WebClient client(String baseUrl, int responseTimeoutSeconds) {
        HttpClient http = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, 2000)
                .responseTimeout(Duration.ofSeconds(responseTimeoutSeconds));
        return WebClient.builder()
                .baseUrl(baseUrl)
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .clientConnector(new ReactorClientHttpConnector(http))
                .build();
    }

    /** 아무도 listen 하지 않는 포트 → connection refused. */
    public static WebClient refusedClient() throws IOException {
        int port;
        try (ServerSocket s = new ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))) {
            port = s.getLocalPort();
        }
        return client("http://127.0.0.1:" + port, 5);
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
