package com.studybridge.api.config;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.core.env.MapPropertySource;
import org.springframework.http.HttpHeaders;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 공용 fastApiWebClient 가 모든 ai07 호출에 내부 Bearer 를 싣는다(감사: 28개 호출부 중 3곳만 보내던 문제).
 * 키가 비면 헤더 없음(기존 동작), 호출별 Authorization 은 기본값보다 우선한다.
 */
class FastApiInternalAuthHeaderTest {

        static List<String> call(String apiKey, String explicit) throws Exception {
                List<String> seen = new CopyOnWriteArrayList<>();
                HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/summary", ex -> {
                        seen.add(String.valueOf(ex.getRequestHeaders().getFirst("Authorization")));
                        ex.sendResponseHeaders(200, 2);
                        ex.getResponseBody().write("{}".getBytes());
                        ex.close();
                });
                server.start();
                AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext();
                try {
                        ctx.getEnvironment().getPropertySources().addFirst(new MapPropertySource("t", java.util.Map.of(
                                        "ai.server.fastapi.primary-base-url", "http://127.0.0.1:" + server.getAddress().getPort(),
                                        "ai.server.api-key", apiKey)));
                        ctx.registerBean(WebClient.Builder.class, WebClient::builder);
                        ctx.register(WebClientConfig.class);
                        ctx.refresh();
                        WebClient wc = ctx.getBean("fastApiWebClient", WebClient.class);
                        WebClient.RequestBodySpec spec = wc.post().uri("/api/ai/summary");
                        if (explicit != null) {
                                spec.header(HttpHeaders.AUTHORIZATION, explicit);
                        }
                        spec.bodyValue("{}").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5));
                        return seen;
                } finally {
                        ctx.close();
                        server.stop(0);
                }
        }

        @Test
        void defaultBearerIsSentWhenKeyConfigured() throws Exception {
                assertEquals(List.of("Bearer " + "x".repeat(64)), call("x".repeat(64), null));
        }

        @Test
        void noHeaderWhenKeyMissing() throws Exception {
                assertEquals(List.of("null"), call("", null));
        }

        @Test
        void explicitHeaderOverridesDefault() throws Exception {
                assertEquals(List.of("Bearer explicit"), call("x".repeat(64), "Bearer explicit"));
        }
}
