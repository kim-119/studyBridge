package com.studybridge.api.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotSame;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.service.VisionUpstreamClient;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import com.studybridge.api.service.VisionUpstreamClient.VisionResult;
import java.net.SocketAddress;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.IntSupplier;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.Disposable;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.netty.DisposableServer;
import reactor.netty.http.client.HttpClient;
import reactor.netty.http.server.HttpServer;
import reactor.netty.resources.ConnectionPoolMetrics;
import reactor.netty.resources.ConnectionProvider;

/**
 * 화면공유 AI 전용 연결 풀(WebClientConfig): 비전 요청이 몰려 풀이 포화돼도 다른 AI 호출(reactor-netty 전역 풀)은 영향받지 않고,
 * 포화·획득 타임아웃은 응답 타임아웃과 구분된 오류로 끝나며, 취소된 요청은 연결을 돌려준다. ai07 은 로컬 스텁 서버.
 */
class VisionConnectionPoolTest {

    private static final String ANSWER = "{\"requestId\":\"x\",\"answer\":\"ok\",\"model\":\"m\"}";

    private DisposableServer server;
    private volatile Sinks.Empty<Void> hold;
    private final AtomicInteger visionInflight = new AtomicInteger();
    private final AtomicInteger visionReceived = new AtomicInteger();
    private final AtomicInteger serverConnections = new AtomicInteger();
    private final AtomicInteger serverConnectionsOpened = new AtomicInteger();
    private final Map<String, ConnectionPoolMetrics> metrics = new ConcurrentHashMap<>();
    private ConnectionProvider provider;
    private VisionUpstreamClient vision;
    private String base;
    private final ObjectMapper om = new ObjectMapper();

    @BeforeEach
    void setUp() {
        server = HttpServer.create().host("127.0.0.1").port(0)
                .doOnChannelInit((observer, channel, remote) -> {   // TCP 연결 단위(요청 단위 아님)
                    serverConnections.incrementAndGet();
                    serverConnectionsOpened.incrementAndGet();
                    channel.closeFuture().addListener(f -> serverConnections.decrementAndGet());
                })
                .route(r -> r
                        .post("/api/ai/vision/analyze", (req, res) -> req.receive().aggregate().then(Mono.defer(() -> {
                            visionInflight.incrementAndGet();
                            visionReceived.incrementAndGet();
                            Sinks.Empty<Void> h = hold;
                            return (h == null ? Mono.<Void>empty() : h.asMono())
                                    .then(res.header("Content-Type", "application/json").sendString(Mono.just(ANSWER)).then())
                                    .doFinally(s -> visionInflight.decrementAndGet());
                        })))
                        .get("/api/other", (req, res) -> res.sendString(Mono.just("ok"))))
                .bindNow();
        base = "http://127.0.0.1:" + server.port();
    }

    @AfterEach
    void tearDown() {
        Sinks.Empty<Void> h = hold;
        if (h != null) h.tryEmitEmpty();
        if (provider != null) provider.disposeLater().block(Duration.ofSeconds(5));
        server.disposeNow(Duration.ofSeconds(5));
    }

    /** 운영과 같은 생성 경로(WebClientConfig 정적 팩토리) + 테스트용 풀 지표 수집. */
    private void visionPool(int maxConnections, int pendingMax, Duration acquireTimeout, Duration maxIdle) {
        provider = WebClientConfig.visionConnectionProviderBuilder(maxConnections, pendingMax, acquireTimeout, maxIdle)
                .metrics(true, () -> new ConnectionProvider.MeterRegistrar() {
                    @Override
                    public void registerMetrics(String poolName, String id, SocketAddress remote, ConnectionPoolMetrics m) {
                        metrics.put(poolName, m);
                    }
                })
                .build();
        WebClient webClient = WebClient.builder().baseUrl(base)
                .clientConnector(new ReactorClientHttpConnector(WebClientConfig.visionHttpClient(provider, 30)))
                .build();
        vision = new VisionUpstreamClient(webClient, om, "/api/ai/vision/analyze", "test-key", 30);
    }

    private ConnectionPoolMetrics pool() {
        return metrics.get("screen-ai-vision");
    }

    private Mono<VisionResult> analyze(int i) {
        return vision.analyze(new VisionCall("req-" + i, 25L, "str", 2L, 3L, "q", "AAAA", "image/jpeg"));
    }

    private static void await(IntSupplier actual, int expected, long ms) {
        long until = System.currentTimeMillis() + ms;
        while (actual.getAsInt() != expected && System.currentTimeMillis() < until) {
            try {
                Thread.sleep(10);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
        assertEquals(expected, actual.getAsInt());
    }

    private static ScreenAiException screenAiError(CompletableFuture<VisionResult> f) throws Exception {
        try {
            f.get(10, TimeUnit.SECONDS);
        } catch (ExecutionException e) {
            return assertInstanceOf(ScreenAiException.class, e.getCause());
        }
        throw new AssertionError("성공하면 안 된다");
    }

    @Test
    void saturatedVisionPool_failsWithBusyAndOverloaded_whileSharedPoolCallsStayFast() throws Exception {
        visionPool(2, 2, Duration.ofMillis(1500), Duration.ofSeconds(4));
        hold = Sinks.empty();

        List<CompletableFuture<VisionResult>> held = new ArrayList<>();
        for (int i = 0; i < 2; i++) held.add(analyze(i).toFuture());
        await(visionInflight::get, 2, 5000);                 // 최대 연결 2개가 ai07 에 도달
        List<CompletableFuture<VisionResult>> queued = new ArrayList<>();
        for (int i = 2; i < 4; i++) queued.add(analyze(i).toFuture());
        await(() -> pool().pendingAcquireSize(), 2, 5000);  // 나머지는 Spring 대기열(연결 없음)
        assertEquals(2, pool().acquiredSize());
        assertEquals(2, visionInflight.get());

        // 대기열(2)까지 가득 → 즉시 429 SCREEN_AI_BUSY (ai07 에 보내지 않음)
        long t0 = System.nanoTime();
        ScreenAiException full = screenAiError(analyze(9).toFuture());
        assertTrue(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t0) < 1000);
        assertEquals("SCREEN_AI_BUSY", full.getCode());
        assertEquals(429, full.getStatus().value());
        assertTrue(full.isRetryable());

        // 같은 ai07 주소로 가는 기존 AI 호출(HttpClient.create() = 전역 풀, fastApiWebClient 와 같은 경로)은 막히지 않는다
        WebClient shared = WebClient.builder().baseUrl(base).clientConnector(new ReactorClientHttpConnector(HttpClient.create())).build();
        long s0 = System.nanoTime();
        List<String> replies = Flux.range(0, 20)
                .flatMap(i -> shared.get().uri("/api/other").retrieve().bodyToMono(String.class), 20)
                .collectList().block(Duration.ofSeconds(5));
        long sharedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - s0);
        assertEquals(20, replies.size());
        assertTrue(sharedMs < 2000, "전역 풀 호출이 비전 포화에 막혔다: " + sharedMs + "ms");

        // 대기열에서 연결을 못 얻은 요청 → 503 SCREEN_AI_OVERLOADED (응답 타임아웃 504 와 구분)
        for (CompletableFuture<VisionResult> q : queued) {
            ScreenAiException e = screenAiError(q);
            assertEquals("SCREEN_AI_OVERLOADED", e.getCode());
            assertEquals(503, e.getStatus().value());
        }

        // ai07 이 응답하면 잡혀 있던 2건은 정상 완료, 풀은 비어 있다
        hold.tryEmitEmpty();
        for (CompletableFuture<VisionResult> h : held) assertEquals("ok", h.get(5, TimeUnit.SECONDS).answer());
        await(() -> pool().acquiredSize(), 0, 3000);
        assertEquals(0, pool().pendingAcquireSize());
        assertEquals(2, pool().maxAllocatedSize());
    }

    @Test
    void cancelledRequests_returnTheirConnections_andQueuedCancelIsNeverSentToAi07() throws Exception {
        visionPool(2, 8, Duration.ofSeconds(30), Duration.ofSeconds(4));
        hold = Sinks.empty();

        Disposable a = analyze(1).subscribe();
        Disposable b = analyze(2).subscribe();
        await(visionInflight::get, 2, 5000);
        await(serverConnections::get, 2, 3000);
        Disposable queued = analyze(3).subscribe();
        await(() -> pool().pendingAcquireSize(), 1, 5000);

        // 대기 중 취소: reactor-netty 1.1 은 대기열 자리를 연결이 빌 때(또는 획득 타임아웃) 정리한다 — 그때 ai07 로 보내지 않고 버린다.
        queued.dispose();

        // 진행 중 취소 → ai07 연결이 끊기고(ai07 은 연결 끊김 시 추론 취소) 풀 슬롯이 돌아온다
        a.dispose();
        b.dispose();
        await(visionInflight::get, 0, 3000);
        await(serverConnections::get, 0, 3000);
        await(() -> pool().acquiredSize(), 0, 3000);
        await(() -> pool().pendingAcquireSize(), 0, 3000);
        assertEquals(2, visionReceived.get(), "대기 중 취소된 요청이 ai07 로 전송됐다");

        // 돌아온 슬롯으로 다음 요청이 바로 진행된다
        hold = null;
        for (int i = 0; i < 4; i++) assertEquals("ok", analyze(10 + i).block(Duration.ofSeconds(5)).answer());
        await(() -> pool().acquiredSize(), 0, 3000);
        assertEquals(6, visionReceived.get());
    }

    @Test
    void idleConnectionsAreRetiredBeforeServerKeepAliveCloses() throws Exception {
        visionPool(2, 8, Duration.ofSeconds(30), Duration.ofMillis(300));
        assertEquals("ok", analyze(1).block(Duration.ofSeconds(5)).answer());
        await(() -> pool().acquiredSize(), 0, 2000);
        assertEquals("ok", analyze(2).block(Duration.ofSeconds(5)).answer());   // 유휴 짧음 → 재사용
        assertEquals(1, serverConnectionsOpened.get());
        Thread.sleep(600);
        assertEquals("ok", analyze(3).block(Duration.ofSeconds(5)).answer());   // max-idle 초과 → 새 연결
        assertEquals(2, serverConnectionsOpened.get());
    }

    @Test
    void beansWireDedicatedPool_andDisposeOnShutdown() {
        AnnotationConfigApplicationContext ctx = new AnnotationConfigApplicationContext();
        ctx.registerBean(WebClient.Builder.class, WebClient::builder);
        ctx.register(WebClientConfig.class);
        ctx.refresh();
        ConnectionProvider p = ctx.getBean("visionConnectionProvider", ConnectionProvider.class);
        assertEquals(2, p.maxConnections());
        WebClient visionClient = ctx.getBean("visionWebClient", WebClient.class);
        WebClient fastApi = ctx.getBean("fastApiWebClient", WebClient.class);
        assertNotSame(visionClient, fastApi);
        ctx.close();
        await(() -> p.isDisposed() ? 1 : 0, 1, 3000);
    }
}
