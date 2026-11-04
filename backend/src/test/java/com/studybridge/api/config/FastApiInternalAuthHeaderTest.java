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
 * Phase C(ai07 인계 2.2): intentRouterWebClient(POST /api/ai/intent/route)와 PdfExtractionService RestTemplate
 * (POST /api/extract, 비전 폴백, RAG ingest)도 같은 키를 싣는다 — Spring→ai07 Bearer 누락 0.
 */
class FastApiInternalAuthHeaderTest {

        static List<String> call(String apiKey, String explicit) throws Exception {
                return call("fastApiWebClient", "/api/ai/summary", apiKey, explicit);
        }

        static List<String> call(String bean, String path, String apiKey, String explicit) throws Exception {
                List<String> seen = new CopyOnWriteArrayList<>();
                HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext(path, ex -> {
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
                                        "ai.intent-router.base-url", "http://127.0.0.1:" + server.getAddress().getPort(),
                                        "ai.server.api-key", apiKey)));
                        ctx.registerBean(WebClient.Builder.class, WebClient::builder);
                        ctx.register(WebClientConfig.class);
                        ctx.refresh();
                        WebClient wc = ctx.getBean(bean, WebClient.class);
                        WebClient.RequestBodySpec spec = wc.post().uri(path);
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

        @Test
        void intentRouterClientSendsBearer() throws Exception {
                assertEquals(List.of("Bearer " + "y".repeat(64)), call("intentRouterWebClient", "/api/ai/intent/route", "y".repeat(64), null));
                assertEquals(List.of("null"), call("intentRouterWebClient", "/api/ai/intent/route", "", null));
        }

        @Test
        void pdfExtractionRestTemplateSendsBearer() throws Exception {
                List<String> seen = new CopyOnWriteArrayList<>();
                HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/", ex -> {
                        seen.add(ex.getRequestURI().getPath() + " " + ex.getRequestHeaders().getFirst("Authorization"));
                        byte[] out = "{\"text\":\"\"}".getBytes();
                        ex.getResponseHeaders().add("Content-Type", "application/json");
                        ex.sendResponseHeaders(200, out.length);
                        ex.getResponseBody().write(out);
                        ex.close();
                });
                server.start();
                try {
                        com.studybridge.api.repository.MaterialRepository repo = org.mockito.Mockito.mock(com.studybridge.api.repository.MaterialRepository.class);
                        com.studybridge.api.service.PdfExtractionService svc = new com.studybridge.api.service.PdfExtractionService(repo,
                                        org.mockito.Mockito.mock(com.studybridge.api.service.StudyNoteAnalysisService.class),
                                        new org.springframework.boot.web.client.RestTemplateBuilder(),
                                        "http://127.0.0.1:" + server.getAddress().getPort() + "/api/extract", 5000, "z".repeat(64));
                        svc.sendToFastApiForExtraction(1L, "%PDF-1.4 tiny".getBytes(), "a.pdf", "application/pdf");
                        assertEquals(true, seen.size() >= 1, "추출 호출이 있어야 한다");
                        for (String s : seen) {
                                assertEquals(true, s.endsWith("Bearer " + "z".repeat(64)), "Bearer 누락: " + s.substring(0, s.indexOf(' ')));
                        }
                        assertEquals(true, seen.get(0).startsWith("/api/extract "));
                } finally {
                        server.stop(0);
                }
        }
}
