package com.studybridge.api.ai;

import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import com.studybridge.api.service.support.FailoverStubServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.io.IOException;
import java.net.ConnectException;
import java.net.URI;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertSame;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 공통 executor: 순회/분류/로그 정책. HTTP 계층 없는 순수 단위 + 로그 비밀 노출 0 검증. */
class AiFailoverExecutorTest {

    private static final String SECRET = "super-secret-ai-key-0123456789abcdef0123456789abcdef";

    private ListAppender<ILoggingEvent> logs;
    private Logger logger;

    @BeforeEach
    void captureLogs() {
        logger = (Logger) LoggerFactory.getLogger(AiFailoverExecutor.class);
        logs = new ListAppender<>();
        logs.start();
        logger.addAppender(logs);
    }

    @AfterEach
    void detach() {
        logger.detachAppender(logs);
    }

    private static AiUpstreams two(WebClient primary, WebClient secondary) {
        return new AiUpstreams(List.of(new AiUpstream("primary", "http://p", primary), new AiUpstream("secondary", "http://s", secondary)));
    }

    private static WebClient dummy() {
        return WebClient.builder().baseUrl("http://unused").build();
    }

    private static WebClientResponseException http(int status) {
        return WebClientResponseException.create(status, HttpStatus.valueOf(status).getReasonPhrase(), HttpHeaders.EMPTY, new byte[0], null);
    }

    @Test
    void classify_policy_matches_multichat() {
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(400)));
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(401)));
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(403)));
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(409)));
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(422)));
        assertEquals(AiFailoverExecutor.FailureKind.CONTRACT, AiFailoverExecutor.classify(http(429)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(http(404)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(http(405)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(http(500)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(http(502)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(http(504)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(
                new WebClientRequestException(new ConnectException("Connection refused"), org.springframework.http.HttpMethod.POST, URI.create("http://p/x"), HttpHeaders.EMPTY)));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(new TimeoutException("t")));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(new IllegalStateException("Timeout on blocking read for 60000000000 NANOSECONDS")));
        assertEquals(AiFailoverExecutor.FailureKind.FAILOVER, AiFailoverExecutor.classify(new java.io.UncheckedIOException(new java.io.IOException("reset"))));
    }

    @Test
    void primary_success_never_touches_secondary() {
        AtomicInteger p = new AtomicInteger(), s = new AtomicInteger();
        AiFailoverExecutor ex = new AiFailoverExecutor(two(dummy(), dummy()));
        AiFailoverExecutor.Result<String> r = ex.execute("/x", up -> {
            (up.name().equals("primary") ? p : s).incrementAndGet();
            return "ok-" + up.name();
        });
        assertEquals("ok-primary", r.value());
        assertEquals("primary", r.upstreamName());
        assertEquals(1, r.attempts());
        assertEquals(1, p.get());
        assertEquals(0, s.get());
        assertTrue(logs.list.isEmpty(), "정상 요청은 로그를 남기지 않는다");
    }

    @Test
    void failover_exception_moves_to_secondary_and_logs_events() {
        AiFailoverExecutor ex = new AiFailoverExecutor(two(dummy(), dummy()));
        AiFailoverExecutor.Result<String> r = ex.execute("/api/ai/x", up -> {
            if (up.name().equals("primary")) throw http(500);
            return "from-secondary";
        });
        assertEquals("from-secondary", r.value());
        assertEquals("secondary", r.upstreamName());
        assertEquals(2, r.attempts());
        String all = String.join("\n", logs.list.stream().map(ILoggingEvent::getFormattedMessage).toList());
        assertTrue(all.contains("AI_PRIMARY_FAILED"), all);
        assertTrue(all.contains("endpoint=/api/ai/x"), all);
        assertTrue(all.contains("nextUpstream=SECONDARY"), all);
        assertTrue(all.contains("AI_SECONDARY_SELECTED"), all);
        assertTrue(all.contains("reason=HTTP 500"), all);
    }

    @Test
    void contract_exception_is_rethrown_without_failover() {
        AtomicInteger s = new AtomicInteger();
        AiFailoverExecutor ex = new AiFailoverExecutor(two(dummy(), dummy()));
        for (int status : new int[]{400, 401, 403, 422}) {
            WebClientResponseException thrown = assertThrows(WebClientResponseException.class, () -> ex.execute("/x", up -> {
                if (up.name().equals("primary")) throw http(status);
                s.incrementAndGet();
                return "never";
            }));
            assertEquals(status, thrown.getStatusCode().value());
        }
        assertEquals(0, s.get(), "4xx contract 실패는 secondary 를 호출하지 않는다");
        assertFalse(String.join("\n", logs.list.stream().map(ILoggingEvent::getFormattedMessage).toList()).contains("AI_PRIMARY_FAILED"));
    }

    @Test
    void both_fail_rethrows_last_exception_and_logs_all_failed() {
        AiFailoverExecutor ex = new AiFailoverExecutor(two(dummy(), dummy()));
        WebClientResponseException thrown = assertThrows(WebClientResponseException.class, () -> ex.execute("/x", up -> {
            throw up.name().equals("primary") ? http(500) : http(503);
        }));
        assertEquals(503, thrown.getStatusCode().value(), "마지막(secondary) 예외가 전파된다");
        String all = String.join("\n", logs.list.stream().map(ILoggingEvent::getFormattedMessage).toList());
        assertTrue(all.contains("AI_ALL_UPSTREAMS_FAILED"), all);
    }

    @Test
    void response_policy_retries_on_secondary_and_returns_structured_failure_when_both_fail() {
        AiFailoverExecutor ex = new AiFailoverExecutor(two(dummy(), dummy()));
        // primary: 200 + 일시 실패 본문 → secondary 성공 본문
        AiFailoverExecutor.Result<Map<String, Object>> r = ex.execute("/q",
                up -> up.name().equals("primary") ? Map.of("success", false, "errorCode", "AI_TIMEOUT") : Map.of("success", true),
                m -> Boolean.FALSE.equals(m.get("success")) ? String.valueOf(m.get("errorCode")) : null);
        assertEquals(true, r.value().get("success"));
        assertEquals("secondary", r.upstreamName());

        // primary: 일시 실패 본문, secondary: 예외 → primary 의 구조화 실패 응답을 반환(호출자가 domain 실패로 처리)
        Map<String, Object> primaryFail = Map.of("success", false, "errorCode", "AI_TIMEOUT");
        AiFailoverExecutor.Result<Map<String, Object>> r2 = ex.execute("/q",
                up -> { if (up.name().equals("primary")) return primaryFail; throw http(500); },
                m -> Boolean.FALSE.equals(m.get("success")) ? String.valueOf(m.get("errorCode")) : null);
        assertSame(primaryFail, r2.value());
        assertEquals("primary", r2.upstreamName());

        // 둘 다 일시 실패 본문 → 마지막(secondary) 본문 반환 + ALL_FAILED 로그
        AiFailoverExecutor.Result<Map<String, Object>> r3 = ex.execute("/q",
                up -> Map.of("success", false, "errorCode", "AI_TIMEOUT", "from", up.name()),
                m -> Boolean.FALSE.equals(m.get("success")) ? String.valueOf(m.get("errorCode")) : null);
        assertEquals("secondary", r3.value().get("from"));
        assertTrue(String.join("\n", logs.list.stream().map(ILoggingEvent::getFormattedMessage).toList()).contains("AI_ALL_UPSTREAMS_FAILED"));
    }

    @Test
    void single_upstream_failure_propagates_without_secondary() {
        AiFailoverExecutor ex = AiFailoverExecutor.single(dummy());
        assertThrows(WebClientResponseException.class, () -> ex.execute("/x", up -> { throw http(500); }));
        assertFalse(ex.upstreams().hasSecondary());
    }

    /** K3: Authorization 헤더가 붙은 실제 HTTP 실패(401/500/refused)를 failover 로그로 남겨도 키가 새지 않는다. */
    @Test
    void k3_logs_never_contain_api_key() throws IOException {
        try (FailoverStubServer primary = new FailoverStubServer("/x"); FailoverStubServer secondary = new FailoverStubServer("/x")) {
            primary.status = 500;
            primary.body = "{\"detail\":\"boom\"}";
            secondary.status = 200;
            secondary.body = "{\"ok\":true}";
            AiFailoverExecutor ex = new AiFailoverExecutor(two(primary.client(5), secondary.client(5)));
            ex.execute("/x", up -> up.client().post().uri("/x").header(HttpHeaders.AUTHORIZATION, "Bearer " + SECRET)
                    .bodyValue("{}").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5)));
            // refused primary
            AiFailoverExecutor ex2 = new AiFailoverExecutor(two(FailoverStubServer.refusedClient(), secondary.client(5)));
            ex2.execute("/x", up -> up.client().post().uri("/x").header(HttpHeaders.AUTHORIZATION, "Bearer " + SECRET)
                    .bodyValue("{}").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5)));
            // both fail → exception message/log
            AiFailoverExecutor ex3 = new AiFailoverExecutor(two(primary.client(5), primary.client(5)));
            assertThrows(WebClientResponseException.class, () -> ex3.execute("/x", up -> up.client().post().uri("/x")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + SECRET).bodyValue("{}").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5))));

            assertEquals(2, secondary.hits.get());
            assertEquals("Bearer " + SECRET, secondary.authorizationHeaders.get(0), "secondary 에도 같은 credential 이 전달된다");
            assertFalse(logs.list.isEmpty());
            for (ILoggingEvent e : logs.list) {
                String msg = e.getFormattedMessage();
                assertFalse(msg.contains(SECRET), "API key 가 로그에 노출됨: " + msg);
                assertFalse(msg.toLowerCase().contains("authorization"), "Authorization 헤더가 로그에 노출됨: " + msg);
            }
        }
    }
}
