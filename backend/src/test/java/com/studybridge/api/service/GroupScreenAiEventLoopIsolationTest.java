package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ScreenAiDTO.AnalyzeRequest;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.VisionUpstreamClient.VisionResult;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.data.redis.core.script.RedisScript;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.BaseSubscriber;
import reactor.core.publisher.Mono;
import reactor.core.publisher.Sinks;
import reactor.core.scheduler.Schedulers;
import reactor.netty.DisposableServer;
import reactor.netty.http.client.HttpClient;
import reactor.netty.http.server.HttpServer;
import reactor.netty.resources.ConnectionProvider;
import reactor.netty.resources.LoopResources;

/**
 * 화면공유 AI 응답 처리 체인의 이벤트 루프 보호와 잠금 정리.
 *
 * <p>실제 reactor-netty 클라이언트(이벤트 루프 1개 — 운영 reactor-http-epoll 의 축소판)로 로컬 스텁 ai07 을 호출하고, 같은 루프를 쓰는
 * "다른 AI 호출"이 막히는지 계속 재 본다. RDS(UserRepository)·Redis(AiRequestGuard/StringRedisTemplate) 지연·장애는 테스트 더블로만
 * 주입한다(운영 RDS·Redis 미사용).</p>
 */
class GroupScreenAiEventLoopIsolationTest {

    private static final long GROUP = 25L;
    private static final String SID = "group_study_25";
    private static final long NOW = GroupVideoCallServiceTest.CLOCK.millis();
    private static final long SLOW_MS = 2000;
    /** 이벤트 루프가 막히지 않았다고 볼 상한. 정상 왕복은 수 ms, 막히면 SLOW_MS 근처. */
    private static final long STALL_LIMIT_MS = 700;
    private static final String ANSWER = "{\"requestId\":\"x\",\"answer\":\"화면 분석 결과\",\"model\":\"qwen3-vl:4b-instruct\",\"latencyMs\":5}";

    private static LoopResources serverLoop;
    private static LoopResources clientLoop;

    private final ObjectMapper om = new ObjectMapper();
    private DisposableServer server;
    private ConnectionProvider visionPool;
    private ConnectionProvider otherPool;
    private WebClient other;
    private volatile Sinks.Empty<Void> hold;
    private volatile int visionStatus = 200;
    private volatile String visionBody = ANSWER;
    private final AtomicInteger visionInflight = new AtomicInteger();

    private OpenViduService openVidu;
    private GroupStudyMemberRepository members;
    private UserRepository users;
    private ScreenAiConsentStore consent;
    private AiRequestGuard guard;
    private final List<Map<String, Object>> connections = new ArrayList<>();
    private String jpeg;

    @BeforeAll
    static void loops() {
        serverLoop = LoopResources.create("stub-ai07", 1, 2, true);
        clientLoop = LoopResources.create("test-reactor-http", 1, 1, true);
    }

    @AfterAll
    static void disposeLoops() {
        serverLoop.disposeLater().block(Duration.ofSeconds(5));
        clientLoop.disposeLater().block(Duration.ofSeconds(5));
    }

    @BeforeEach
    void setUp() throws Exception {
        hold = null;
        server = HttpServer.create().host("127.0.0.1").port(0).runOn(serverLoop)
                .route(r -> r
                        .post("/api/ai/vision/analyze", (req, res) -> req.receive().aggregate().then(Mono.defer(() -> {
                            visionInflight.incrementAndGet();
                            Sinks.Empty<Void> h = hold;
                            return (h == null ? Mono.<Void>empty() : h.asMono())
                                    .then(res.status(visionStatus).header("Content-Type", "application/json").sendString(Mono.just(visionBody)).then())
                                    .doFinally(s -> visionInflight.decrementAndGet());
                        })))
                        .get("/api/other", (req, res) -> res.sendString(Mono.just("ok"))))
                .bindNow();
        String base = "http://127.0.0.1:" + server.port();
        visionPool = ConnectionProvider.create("t-vision", 2);
        otherPool = ConnectionProvider.create("t-other", 8);
        WebClient vision = WebClient.builder().baseUrl(base)
                .clientConnector(new ReactorClientHttpConnector(HttpClient.create(visionPool).runOn(clientLoop))).build();
        other = WebClient.builder().baseUrl(base)
                .clientConnector(new ReactorClientHttpConnector(HttpClient.create(otherPool).runOn(clientLoop))).build();
        upstream = new VisionUpstreamClient(vision, om, "/api/ai/vision/analyze", "test-key", 30);

        openVidu = mock(OpenViduService.class);
        members = mock(GroupStudyMemberRepository.class);
        users = mock(UserRepository.class);
        consent = mock(ScreenAiConsentStore.class);
        guard = mock(AiRequestGuard.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(eq(GROUP), anyLong(), eq(GroupStudyMemberStatus.JOINED))).thenReturn(true);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
        when(guard.allow(anyString(), anyInt(), any())).thenReturn(true);
        when(consent.isAllowed(eq(GROUP), anyString(), anyLong())).thenReturn(true);
        when(openVidu.listConnections(SID, false)).thenReturn(connections);
        for (long id = 1; id <= 3; id++) {
            User u = new User();
            u.setDisplayName("사용자" + id);
            when(users.findById(id)).thenReturn(Optional.of(u));
        }
        connections.add(conn("con_B", sd(2L, "PRIMARY", null), "str_con_B_CAMERA", "CAMERA"));
        connections.add(conn("con_C", sd(3L, "PRIMARY", null), "str_con_C_CAMERA", "CAMERA"));
        connections.add(conn("con_SB", sd(2L, "SCREEN", "con_B"), "str_SB_SCREEN", "SCREEN"));
        jpeg = ScreenAiImageValidatorTest.jpegB64(1280, 720);
        service = newService(guard);

        // 루프 예열(첫 연결 비용이 측정에 섞이지 않게)
        assertEquals("ok", other.get().uri("/api/other").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(5)));
    }

    private VisionUpstreamClient upstream;
    private GroupScreenAiService service;

    private GroupScreenAiService newService(AiRequestGuard g) {
        GroupVideoCallService video = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
        return new GroupScreenAiService(video, openVidu, members, users, om, consent, g, upstream,
                GroupVideoCallServiceTest.CLOCK, true, 1000, 1024 * 1024, 1280, 32, 6, 30);
    }

    @AfterEach
    void tearDown() {
        Sinks.Empty<Void> h = hold;
        if (h != null) h.tryEmitEmpty();
        service.shutdown();
        server.disposeNow(Duration.ofSeconds(5));
        visionPool.disposeLater().block(Duration.ofSeconds(5));
        otherPool.disposeLater().block(Duration.ofSeconds(5));
    }

    // ── 픽스처 ──

    private String sd(long userId, String kind, String owner) {
        return VideoConnectionMetadata.toServerData(om, GROUP, userId, VideoConnectionMetadata.Kind.valueOf(kind), owner, null, "WEB", NOW - 5_000);
    }

    private static Map<String, Object> conn(String id, String serverData, String streamId, String typeOfVideo) {
        Map<String, Object> c = new HashMap<>();
        c.put("connectionId", id);
        c.put("status", "active");
        c.put("serverData", serverData);
        c.put("clientData", "{}");
        c.put("activeAt", NOW - 30_000);
        c.put("publishers", List.of(Map.of("streamId", streamId, "mediaOptions", Map.of("typeOfVideo", typeOfVideo))));
        return c;
    }

    private AnalyzeRequest req(String clientRequestId) {
        return new AnalyzeRequest("con_SB", "str_SB_SCREEN", "이 화면을 설명해 줘", jpeg, "image/jpeg", clientRequestId);
    }

    /** Spring MVC DeferredResultSubscriber 처럼 무제한 요청 → onComplete 에서 결과 확정(onNext 에서 취소하지 않는다). */
    private static <T> CompletableFuture<T> subscribeLikeSpringMvc(Mono<T> mono) {
        CompletableFuture<T> f = new CompletableFuture<>();
        mono.subscribe(new BaseSubscriber<T>() {
            private T value;

            @Override
            protected void hookOnNext(T v) {
                value = v;
            }

            @Override
            protected void hookOnComplete() {
                f.complete(value);
            }

            @Override
            protected void hookOnError(Throwable t) {
                f.completeExceptionally(t);
            }
        });
        return f;
    }

    /** 같은 이벤트 루프의 "다른 AI 호출"을 50ms 간격으로 계속 보내 최대 왕복 시간을 잰다. */
    private final class LoopProbe implements AutoCloseable {
        private final AtomicBoolean running = new AtomicBoolean(true);
        private final AtomicLong maxMs = new AtomicLong();
        private final AtomicInteger samples = new AtomicInteger();
        private final Thread thread = new Thread(() -> {
            while (running.get()) {
                long t0 = System.nanoTime();
                other.get().uri("/api/other").retrieve().bodyToMono(String.class).block(Duration.ofSeconds(10));
                maxMs.accumulateAndGet(TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t0), Math::max);
                samples.incrementAndGet();
                try {
                    Thread.sleep(50);
                } catch (InterruptedException e) {
                    return;
                }
            }
        }, "loop-probe");

        LoopProbe() {
            thread.setDaemon(true);
            thread.start();
        }

        long stopAndMaxMs() throws InterruptedException {
            running.set(false);
            thread.join(15_000);
            return maxMs.get();
        }

        @Override
        public void close() {
            running.set(false);
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void awaitVisionInflight(int n) {
        long until = System.currentTimeMillis() + 5000;
        while (visionInflight.get() < n && System.currentTimeMillis() < until) sleep(10);
        assertEquals(n, visionInflight.get());
    }

    // ── 4. RDS 지연 ──

    @Test
    void slowRds_sharerNameIsResolvedOnRequestThread_neverOnEventLoop() throws Exception {
        List<Boolean> onEventLoop = new CopyOnWriteArrayList<>();
        when(users.findById(2L)).thenAnswer(inv -> {
            onEventLoop.add(Schedulers.isInNonBlockingThread());
            sleep(SLOW_MS);
            User u = new User();
            u.setDisplayName("사용자2");
            return Optional.of(u);
        });

        LoopProbe probe = new LoopProbe();
        try (probe) {
            Map<String, Object> res = subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_rds_slow_1"))).get(10, TimeUnit.SECONDS);
            sleep(200);
            @SuppressWarnings("unchecked") Map<String, Object> sharer = (Map<String, Object>) res.get("sharer");
            assertEquals("사용자2", sharer.get("name"));
            assertEquals("화면 분석 결과", res.get("answer"));
        }
        long max = probe.stopAndMaxMs();
        assertEquals(List.of(false), onEventLoop, "공유자 이름(RDS) 조회는 요청 스레드에서 한 번만");
        assertTrue(max < STALL_LIMIT_MS, "다른 AI 호출이 이벤트 루프에서 " + max + "ms 막혔다");
        verify(guard, timeout(2000).times(1)).release(any());
    }

    @Test
    void rdsFailureWhileResolvingSharerName_releasesLockOnce_andNeverCallsAi07() {
        when(users.findById(2L)).thenThrow(new org.springframework.dao.DataAccessResourceFailureException("rds down"));
        assertThrows(org.springframework.dao.DataAccessResourceFailureException.class,
                () -> service.analyze(3L, GROUP, req("cr_rds_down_1")));
        verify(guard, times(1)).release(any());
        assertEquals(0, visionInflight.get());
    }

    // ── 5. Redis 지연 · 실패 ──

    @Test
    void slowRedisRelease_runsOffEventLoop_andOtherAiCallsKeepFlowing() throws Exception {
        List<String> releaseThreads = new CopyOnWriteArrayList<>();
        List<Boolean> releaseOnEventLoop = new CopyOnWriteArrayList<>();
        CountDownLatch released = new CountDownLatch(1);
        doAnswer(inv -> {
            releaseThreads.add(Thread.currentThread().getName());
            releaseOnEventLoop.add(Schedulers.isInNonBlockingThread());
            sleep(SLOW_MS);
            released.countDown();
            return null;
        }).when(guard).release(any());

        LoopProbe probe = new LoopProbe();
        long answeredIn;
        try (probe) {
            long t0 = System.nanoTime();
            Map<String, Object> res = subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_redis_slow"))).get(10, TimeUnit.SECONDS);
            answeredIn = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - t0);
            assertEquals("화면 분석 결과", res.get("answer"));
            assertTrue(released.await(SLOW_MS * 3, TimeUnit.MILLISECONDS));
        }
        long max = probe.stopAndMaxMs();
        assertEquals(List.of(false), releaseOnEventLoop, "잠금 해제(Redis)가 이벤트 루프에서 실행됐다: " + releaseThreads);
        assertTrue(answeredIn < SLOW_MS, "응답이 Redis 해제를 기다렸다: " + answeredIn + "ms");
        assertTrue(max < STALL_LIMIT_MS, "다른 AI 호출이 이벤트 루프에서 " + max + "ms 막혔다");
        verify(guard, times(1)).release(any());
    }

    @Test
    void redisFailingOnRelease_isContained_attemptedOnceWithOwnerToken() throws Exception {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        @SuppressWarnings("unchecked") ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        when(ops.setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);
        when(ops.increment(anyString())).thenReturn(1L);
        AtomicInteger releaseCalls = new AtomicInteger();
        List<Boolean> onEventLoop = new CopyOnWriteArrayList<>();
        List<Object> tokens = new CopyOnWriteArrayList<>();
        when(redis.execute(any(RedisScript.class), anyList(), any(Object[].class))).thenAnswer(inv -> {
            releaseCalls.incrementAndGet();
            onEventLoop.add(Schedulers.isInNonBlockingThread());
            tokens.add(inv.getArgument(2));
            sleep(500);
            throw new RedisConnectionFailureException("redis timeout");
        });
        AiRequestGuard realGuard = new AiRequestGuard(redis);
        service.shutdown();
        service = newService(realGuard);

        Map<String, Object> res = subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_redis_fail"))).get(10, TimeUnit.SECONDS);
        assertEquals("화면 분석 결과", res.get("answer"));
        long until = System.currentTimeMillis() + 3000;
        while (releaseCalls.get() == 0 && System.currentTimeMillis() < until) sleep(20);
        sleep(700);
        assertEquals(1, releaseCalls.get());
        assertEquals(List.of(false), onEventLoop);
        // 해제는 잠금을 잡을 때 받은 토큰으로만(다른 요청의 잠금을 지우지 않는다)
        org.mockito.ArgumentCaptor<String> token = org.mockito.ArgumentCaptor.forClass(String.class);
        verify(ops).setIfAbsent(anyString(), token.capture(), any(Duration.class));
        assertEquals(token.getValue(), tokens.get(0));
    }

    @Test
    void redisDownAtLock_failsOpen_andReleaseIsNoop() throws Exception {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.opsForValue()).thenThrow(new RedisConnectionFailureException("redis down"));
        service.shutdown();
        service = newService(new AiRequestGuard(redis));

        Map<String, Object> res = subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_redis_down"))).get(10, TimeUnit.SECONDS);
        assertEquals("화면 분석 결과", res.get("answer"));
        sleep(200);
        verify(redis, never()).execute(any(RedisScript.class), anyList(), any(Object[].class));
    }

    // ── 3. 취소 ──

    @Test
    void cancelViaDelete_releasesBeforeDeleteReturns_closesUpstream_andDropsLateAnswer() throws Exception {
        hold = Sinks.empty();
        AtomicInteger values = new AtomicInteger();
        CompletableFuture<Throwable> error = new CompletableFuture<>();
        service.analyze(3L, GROUP, req("cr_cancel_001")).subscribe(v -> values.incrementAndGet(), error::complete);
        awaitVisionInflight(1);

        // DELETE 요청 스레드(Tomcat)에서 취소 → 응답 전에 잠금이 풀려 있어야 같은 사용자의 다음 질문이 바로 들어온다(기존 동작 유지)
        Map<String, Object> res = service.cancel(3L, GROUP, "cr_cancel_001");
        assertEquals(true, res.get("cancelled"));
        verify(guard, times(1)).release(any());
        assertEquals("SCREEN_AI_CANCELLED", ((ScreenAiException) error.get(2, TimeUnit.SECONDS)).getCode());

        // ai07 쪽 연결이 끊겨야 ai07 이 추론을 취소한다
        long until = System.currentTimeMillis() + 3000;
        while (visionInflight.get() > 0 && System.currentTimeMillis() < until) sleep(20);
        assertEquals(0, visionInflight.get(), "취소 후 ai07 요청 연결이 남아 있다");

        hold.tryEmitEmpty();   // 늦게 도착하는 답변이 있어도 사용자에게 전달되지 않는다
        sleep(300);
        assertEquals(0, values.get());
        assertEquals(false, service.cancel(3L, GROUP, "cr_cancel_001").get("cancelled"));
        verify(guard, times(1)).release(any());

        // 연결 풀 슬롯이 돌아와 다음 요청이 정상 처리된다(풀 2개를 넘게 반복)
        hold = null;
        for (int i = 0; i < 3; i++) {
            assertEquals("화면 분석 결과", subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_after_" + i + "_x"))).get(5, TimeUnit.SECONDS).get("answer"));
        }
    }

    @Test
    void responseAndCancelRacing_releaseExactlyOnce_andOneOutcome() throws Exception {
        VisionUpstreamClient racing = mock(VisionUpstreamClient.class);
        when(racing.timeout()).thenReturn(Duration.ofSeconds(260));
        when(racing.configured()).thenReturn(true);
        AiRequestGuard counting = mock(AiRequestGuard.class);
        when(counting.allow(anyString(), anyInt(), any())).thenReturn(true);
        AtomicInteger seq = new AtomicInteger();
        when(counting.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "tok" + seq.incrementAndGet(), true));
        Map<String, AtomicInteger> releases = new java.util.concurrent.ConcurrentHashMap<>();
        doAnswer(inv -> {
            releases.computeIfAbsent(((AiRequestGuard.Lock) inv.getArgument(0)).token(), k -> new AtomicInteger()).incrementAndGet();
            return null;
        }).when(counting).release(any());
        GroupVideoCallService video = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
        GroupScreenAiService svc = new GroupScreenAiService(video, openVidu, members, users, om, consent, counting, racing,
                GroupVideoCallServiceTest.CLOCK, true, 1000, 1024 * 1024, 1280, 32, 6, 30);
        try {
            int rounds = 30;
            for (int i = 0; i < rounds; i++) {
                Sinks.One<VisionResult> answer = Sinks.one();
                when(racing.analyze(any())).thenReturn(answer.asMono());
                String crid = "cr_race_" + i + "_xx";
                AtomicInteger signals = new AtomicInteger();
                CountDownLatch done = new CountDownLatch(1);
                svc.analyze(3L, GROUP, req(crid)).subscribe(v -> signals.incrementAndGet(), e -> { signals.incrementAndGet(); done.countDown(); }, done::countDown);
                CountDownLatch go = new CountDownLatch(1);
                Thread a = new Thread(() -> { await(go); answer.tryEmitValue(new VisionResult("r", "late", "m", 1L, 0L, 1L)); });
                Thread b = new Thread(() -> { await(go); svc.cancel(3L, GROUP, crid); });
                a.start();
                b.start();
                go.countDown();
                a.join(5000);
                b.join(5000);
                assertTrue(done.await(5, TimeUnit.SECONDS));
                assertEquals(1, signals.get(), "응답과 취소 중 하나만 전달돼야 한다");
            }
            long until = System.currentTimeMillis() + 3000;
            while (releases.size() < rounds && System.currentTimeMillis() < until) sleep(20);
            assertEquals(rounds, releases.size());
            releases.forEach((tok, n) -> assertEquals(1, n.get(), "잠금 " + tok + " 중복 해제"));
        } finally {
            svc.shutdown();
        }
    }

    private static void await(CountDownLatch l) {
        try {
            l.await();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // ── 타임아웃 · AI 오류 ──

    @Test
    void upstreamTimeoutOnTimerThread_releasesOnceOffEventLoop() throws Exception {
        VisionUpstreamClient slow = mock(VisionUpstreamClient.class);
        when(slow.timeout()).thenReturn(Duration.ofSeconds(260));
        when(slow.configured()).thenReturn(true);
        when(slow.analyze(any())).thenReturn(Mono.<VisionResult>never().timeout(Duration.ofMillis(200))
                .onErrorMap(e -> VisionUpstreamClient.mapTransportError("r", e)));
        List<Boolean> onEventLoop = new CopyOnWriteArrayList<>();
        doAnswer(inv -> { onEventLoop.add(Schedulers.isInNonBlockingThread()); return null; }).when(guard).release(any());
        GroupVideoCallService video = GroupVideoCallServiceTest.newService(openVidu, members, om, 2500, 1500);
        GroupScreenAiService svc = new GroupScreenAiService(video, openVidu, members, users, om, consent, guard, slow,
                GroupVideoCallServiceTest.CLOCK, true, 1000, 1024 * 1024, 1280, 32, 6, 30);
        try {
            Throwable e = assertThrows(java.util.concurrent.ExecutionException.class,
                    () -> subscribeLikeSpringMvc(svc.analyze(3L, GROUP, req("cr_timeout_1"))).get(5, TimeUnit.SECONDS)).getCause();
            assertEquals("SCREEN_AI_TIMEOUT", ((ScreenAiException) e).getCode());
            verify(guard, timeout(2000).times(1)).release(any());
            assertEquals(List.of(false), onEventLoop);
        } finally {
            svc.shutdown();
        }
    }

    @Test
    void ai07ErrorOnEventLoop_releasesOnceOffEventLoop_andMapsError() throws Exception {
        visionStatus = 503;
        visionBody = "{\"error\":{\"code\":\"VISION_QUEUE_TIMEOUT\",\"retryable\":true}}";
        List<Boolean> onEventLoop = new CopyOnWriteArrayList<>();
        doAnswer(inv -> { onEventLoop.add(Schedulers.isInNonBlockingThread()); return null; }).when(guard).release(any());

        Throwable e = assertThrows(java.util.concurrent.ExecutionException.class,
                () -> subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_ai_err_1"))).get(5, TimeUnit.SECONDS)).getCause();
        ScreenAiException se = assertInstanceOf(ScreenAiException.class, e);
        assertEquals("SCREEN_AI_OVERLOADED", se.getCode());
        assertEquals(503, se.getStatus().value());
        verify(guard, timeout(2000).times(1)).release(any());
        assertEquals(List.of(false), onEventLoop);
    }

    @Test
    void releaseQueueRejection_neverBlocksTheLoop_lockLeftToTtl() {
        // 정리 스케줄러가 닫힌 극단 상황(종료 중 등): 이벤트 루프에서 Redis 를 부르지 않고 TTL 만료에 맡긴다.
        service.shutdown();
        List<Boolean> onEventLoop = new CopyOnWriteArrayList<>();
        doAnswer(inv -> { onEventLoop.add(Schedulers.isInNonBlockingThread()); return null; }).when(guard).release(any());
        Map<String, Object> res = assertDoesNotThrowGet(service.analyze(3L, GROUP, req("cr_reject_1")));
        assertEquals("화면 분석 결과", res.get("answer"));
        sleep(200);
        assertFalse(onEventLoop.contains(true));
    }

    private static Map<String, Object> assertDoesNotThrowGet(Mono<Map<String, Object>> mono) {
        try {
            return subscribeLikeSpringMvc(mono).get(5, TimeUnit.SECONDS);
        } catch (Exception e) {
            throw new AssertionError(e);
        }
    }

    @Test
    void normalCompletion_releasesOnce_andLeavesNoCancelHandle() throws Exception {
        Map<String, Object> res = subscribeLikeSpringMvc(service.analyze(3L, GROUP, req("cr_normal_1"))).get(5, TimeUnit.SECONDS);
        assertNotNull(res.get("requestId"));
        assertNull(res.get("error"));
        verify(guard, timeout(2000).times(1)).release(any());
        assertEquals(false, service.cancel(3L, GROUP, "cr_normal_1").get("cancelled"));
    }
}
