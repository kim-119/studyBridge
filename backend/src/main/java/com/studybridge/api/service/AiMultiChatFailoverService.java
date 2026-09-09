package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverSettings;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.io.IOException;
import java.net.ConnectException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 멀티에이전트 채팅(/api/ai/multi-chat[/stream]) 업스트림 failover.
 *
 * <pre>
 *  PRIMARY stream (ai07 :18000)  ─실패→  SECONDARY stream (EC2 :8000)  ─실패→  non-stream /api/ai/multi-chat (primary→secondary)
 *                                                                             → Spring 이 all_complete SSE 로 변환
 * </pre>
 *
 * 규칙
 *  - 리액티브 체인을 끝까지 유지한다: block()/Thread.sleep 없음, 서비스 내부 subscribe 없음(구독은 MVC 가 한다).
 *  - failover 대상 실패: connection refused / connect·read·idle timeout / 404 / 405 / 5xx / premature close / 업스트림 fatal error 이벤트.
 *  - contract/config 실패(400/401/403/422)는 다른 서버로 숨기지 않고 [AI-CONTRACT] ERROR 로그 + error 이벤트로 명시 종료한다.
 *  - 동일 업스트림 재시도는 첫 이벤트 수신 전 실패에만, 최대 attempts-per-upstream(≤3), 지수 backoff. 무한 retry 금지.
 *  - 실패한 업스트림은 circuit cooldown 동안 건너뛰고, 만료되면 자동으로 다시 시도한다(ai07 복구 시 수동 조치 없이 PRIMARY 복귀).
 *  - /openapi.json 프로브가 stream 라우트 부재(=구버전 회귀)를 확인하면 그 업스트림의 stream 단계를 건너뛴다.
 *  - 어떤 경우에도 예외를 컨트롤러로 던지지 않는다: 최종 실패도 error + done 이벤트로 HTTP/SSE 를 정상 종료한다(500 금지).
 */
@Service
@Slf4j
public class AiMultiChatFailoverService {

    public static final String STREAM_PATH = "/api/ai/multi-chat/stream";
    public static final String NON_STREAM_PATH = "/api/ai/multi-chat";
    private static final String OPENAPI_PATH = "/openapi.json";

    private static final ParameterizedTypeReference<ServerSentEvent<String>> SSE_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {};

    /** 실패 분류. FAILOVER = 다음 대상으로 넘어간다, CONTRACT = 설정/계약 오류(숨기지 않고 명시 종료). */
    public enum FailureKind { FAILOVER, CONTRACT }

    /** 라우트 표면 프로브 결과. UNKNOWN(프로브 실패)은 시도 허용, NOT_READY(라우트 부재 확정)만 stream 을 건너뛴다. */
    public enum RouteReadiness { READY, NOT_READY, UNKNOWN }

    private final AiUpstreams upstreams;
    private final ObjectMapper objectMapper;
    private final AiFailoverSettings settings;
    private final Map<String, UpstreamState> states = new ConcurrentHashMap<>();
    private ScheduledExecutorService prober;

    public AiMultiChatFailoverService(AiUpstreams upstreams, ObjectMapper objectMapper, AiFailoverSettings settings) {
        this.upstreams = upstreams;
        this.objectMapper = objectMapper;
        this.settings = settings;
        for (AiUpstream up : upstreams.ordered()) {
            states.put(up.name(), new UpstreamState());
        }
    }

    // ───────────────────────── 업스트림 상태(circuit + route readiness) ─────────────────────────

    static final class UpstreamState {
        volatile long circuitOpenUntilMs = 0L;
        volatile RouteReadiness readiness = RouteReadiness.UNKNOWN;
        volatile String lastFailure = "";
        volatile long lastProbeMs = 0L;
    }

    @PostConstruct
    void startProbe() {
        if (!settings.probeEnabled()) {
            return;
        }
        prober = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "ai-upstream-probe");
            t.setDaemon(true);
            return t;
        });
        long period = Math.max(5, settings.probeInterval().toSeconds());
        prober.scheduleWithFixedDelay(this::probeAll, 2, period, TimeUnit.SECONDS);
        log.info("[AI-UPSTREAM] failover 구성 upstreams={} attemptsPerUpstream={} cooldown={}s probe={}s idle={}s total={}s",
                describeUpstreams(), settings.attemptsPerUpstream(), settings.circuitCooldown().toSeconds(),
                period, settings.streamIdleTimeout().toSeconds(), settings.totalTimeout().toSeconds());
    }

    @PreDestroy
    void stopProbe() {
        if (prober != null) {
            prober.shutdownNow();
        }
    }

    /** 요청 경로 밖(전용 데몬 스레드)에서 /openapi.json 을 읽어 stream 라우트 존재 여부를 갱신한다. */
    void probeAll() {
        for (AiUpstream up : upstreams.ordered()) {
            probeOne(up);
        }
    }

    void probeOne(AiUpstream up) {
        UpstreamState st = states.get(up.name());
        up.client().get().uri(OPENAPI_PATH)
                .retrieve()
                .bodyToMono(String.class)
                .timeout(Duration.ofSeconds(8))
                .subscribe(
                        json -> {
                            boolean has = json != null && json.contains("\"" + STREAM_PATH + "\"");
                            setReadiness(up, st, has ? RouteReadiness.READY : RouteReadiness.NOT_READY,
                                    has ? "route present" : "route MISSING in openapi (regression)");
                        },
                        err -> setReadiness(up, st, RouteReadiness.UNKNOWN, "probe failed: " + brief(err)));
    }

    private void setReadiness(AiUpstream up, UpstreamState st, RouteReadiness next, String note) {
        RouteReadiness prev = st.readiness;
        st.readiness = next;
        st.lastProbeMs = System.currentTimeMillis();
        if (prev != next) {
            if (next == RouteReadiness.READY) {
                log.info("[AI-UPSTREAM] {} ({}) route READY — {}", up.name(), up.baseUrl(), note);
            } else {
                log.warn("[AI-UPSTREAM] {} ({}) route {} — {}", up.name(), up.baseUrl(), next, note);
            }
        }
    }

    private boolean circuitOpen(UpstreamState st) {
        return System.currentTimeMillis() < st.circuitOpenUntilMs;
    }

    private void openCircuit(AiUpstream up, Throwable cause) {
        UpstreamState st = states.get(up.name());
        boolean wasOpen = circuitOpen(st);
        st.circuitOpenUntilMs = System.currentTimeMillis() + settings.circuitCooldown().toMillis();
        st.lastFailure = brief(cause);
        if (!wasOpen) {
            log.warn("[AI-UPSTREAM] {} circuit OPEN for {}s — {}", up.name(), settings.circuitCooldown().toSeconds(), st.lastFailure);
        }
    }

    private void markHealthy(AiUpstream up) {
        UpstreamState st = states.get(up.name());
        if (circuitOpen(st)) {
            log.info("[AI-UPSTREAM] {} circuit CLOSED (recovered)", up.name());
        }
        st.circuitOpenUntilMs = 0L;
    }

    /** stream 단계 후보: circuit 닫힘 + 라우트 NOT_READY 아님. 후보가 없으면 최후 수단으로 전체를 순서대로 시도한다. */
    List<AiUpstream> streamCandidates() {
        List<AiUpstream> out = new ArrayList<>();
        for (AiUpstream up : upstreams.ordered()) {
            UpstreamState st = states.get(up.name());
            if (!circuitOpen(st) && st.readiness != RouteReadiness.NOT_READY) {
                out.add(up);
            }
        }
        return out.isEmpty() ? upstreams.ordered() : out;
    }

    /** non-stream 단계 후보: circuit 닫힌 업스트림 먼저, 그 다음 열린 것(최후 수단). */
    List<AiUpstream> nonStreamCandidates() {
        List<AiUpstream> healthy = new ArrayList<>();
        List<AiUpstream> degraded = new ArrayList<>();
        for (AiUpstream up : upstreams.ordered()) {
            (circuitOpen(states.get(up.name())) ? degraded : healthy).add(up);
        }
        healthy.addAll(degraded);
        return healthy;
    }

    /** 진단용 스냅샷(민감정보 없음). */
    public Map<String, Object> snapshot() {
        Map<String, Object> out = new LinkedHashMap<>();
        for (AiUpstream up : upstreams.ordered()) {
            UpstreamState st = states.get(up.name());
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("baseUrl", up.baseUrl());
            row.put("routeReadiness", st.readiness.name());
            row.put("circuitOpen", circuitOpen(st));
            row.put("lastFailure", st.lastFailure);
            out.put(up.name(), row);
        }
        return out;
    }

    // ───────────────────────── 요청 컨텍스트(관측성) ─────────────────────────

    /** 요청 1건의 관측 필드. 프롬프트/크리덴셜은 절대 담지 않는다. */
    static final class Ctx {
        final Long roomId;
        final String requestId;
        final long startedAt = System.currentTimeMillis();
        final AtomicReference<String> selectedUpstream = new AtomicReference<>("none");
        final AtomicReference<String> mode = new AtomicReference<>("none");
        final AtomicReference<Integer> httpStatus = new AtomicReference<>(null);
        final List<String> fallbackReasons = Collections.synchronizedList(new ArrayList<>());
        final AtomicBoolean allComplete = new AtomicBoolean(false);
        final AtomicBoolean finished = new AtomicBoolean(false);
        final AtomicInteger relayed = new AtomicInteger(0);
        final AtomicReference<String> result = new AtomicReference<>("pending");

        Ctx(Long roomId, String requestId) {
            this.roomId = roomId;
            this.requestId = requestId;
        }

        long elapsedMs() {
            return System.currentTimeMillis() - startedAt;
        }

        String fallbackReason() {
            synchronized (fallbackReasons) {
                return fallbackReasons.isEmpty() ? "none" : String.join(" | ", fallbackReasons);
            }
        }
    }

    // ───────────────────────── 공개 API ─────────────────────────

    /**
     * 멀티에이전트 채팅 SSE 스트림(failover 포함). 반환 Flux 는 절대 error 로 끝나지 않으며,
     * 마지막 이벤트는 항상 Spring 이 만든 done 이다(업스트림 done 은 삼킨다).
     *
     * @param nonStreamTimeout non-stream 폴백 1회 호출 상한(모드별 AI 타임아웃)
     */
    public Flux<ServerSentEvent<String>> streamMultiChat(Long roomId, String requestId,
                                                        Map<String, Object> requestBody, Duration nonStreamTimeout) {
        final Ctx ctx = new Ctx(roomId, requestId);
        final List<AiUpstream> order = streamCandidates();

        Flux<ServerSentEvent<String>> body = streamTier(order, 0, ctx, requestBody)
                .onErrorResume(err -> {
                    if (classify(err) == FailureKind.CONTRACT) {
                        return contractFailure(ctx, err);
                    }
                    ctx.fallbackReasons.add("stream-exhausted:" + brief(err));
                    return nonStreamTier(nonStreamCandidates(), 0, ctx, requestBody, nonStreamTimeout, 1)
                            .flatMapMany(resp -> Flux.just(allCompleteEvent(resp, ctx)))
                            .onErrorResume(err2 -> {
                                if (classify(err2) == FailureKind.CONTRACT) {
                                    return contractFailure(ctx, err2);
                                }
                                ctx.result.set("failed");
                                log.error("[AI-STREAM] roomId={} requestId={} 모든 업스트림 실패 — {}", roomId, requestId, brief(err2));
                                return Flux.just(errorEvent(ctx, "AI_UPSTREAM_UNAVAILABLE",
                                        "AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요."));
                            });
                })
                .filter(ev -> {
                    // 후순위 업스트림이 다시 보내는 turn_start 는 중복이므로 버린다(브라우저 UI 리셋 방지).
                    return !("turn_start".equals(ev.event()) && ctx.relayed.get() > 0);
                })
                .doOnNext(ev -> {
                    ctx.relayed.incrementAndGet();
                    if ("all_complete".equals(ev.event())) {
                        ctx.allComplete.set(true);
                        if ("pending".equals(ctx.result.get())) {
                            ctx.result.set("all_complete");
                        }
                    }
                })
                .concatWith(Flux.defer(() -> Flux.just(doneEvent(ctx, ctx.allComplete.get() ? "done" : "error"))))
                .doOnNext(ev -> {
                    if ("done".equals(ev.event())) {
                        ctx.finished.set(true);
                    }
                });

        // 전체 상한: 초과 시 업스트림을 끊고 error + done 으로 정상 종료한다.
        return body
                .takeUntilOther(Mono.delay(settings.totalTimeout()))
                .concatWith(Flux.defer(() -> {
                    if (ctx.finished.get()) {
                        return Flux.empty();
                    }
                    ctx.result.set("timeout");
                    return Flux.just(
                            errorEvent(ctx, "AI_TOTAL_TIMEOUT", "AI 응답이 제한 시간을 초과했습니다. 잠시 후 다시 시도해 주세요."),
                            doneEvent(ctx, "error"));
                }))
                .doFinally(sig -> logSummary(ctx, String.valueOf(sig)));
    }

    /**
     * non-stream /api/ai/multi-chat 호출(failover 포함). 기본채팅 1차/2차/3차 오케스트레이션이 사용한다.
     * 실패 시 Mono.error 로 끝나며 호출자가 onErrorResume 으로 처리한다(컨트롤러 예외 아님).
     */
    public Mono<Map<String, Object>> callMultiChat(Long roomId, String requestId,
                                                   Map<String, Object> requestBody, Duration perCallTimeout) {
        final Ctx ctx = new Ctx(roomId, requestId);
        return nonStreamTier(nonStreamCandidates(), 0, ctx, requestBody, perCallTimeout, 1)
                .doOnSuccess(m -> {
                    ctx.result.set("ok");
                    logSummary(ctx, "onSuccess");
                })
                .doOnError(e -> {
                    ctx.result.set("failed");
                    logSummary(ctx, "onError");
                });
    }

    // ───────────────────────── stream 단계 ─────────────────────────

    private Flux<ServerSentEvent<String>> streamTier(List<AiUpstream> order, int idx, Ctx ctx, Map<String, Object> body) {
        if (idx >= order.size()) {
            return Flux.error(new UpstreamExhaustedException("no stream upstream left"));
        }
        AiUpstream up = order.get(idx);
        return streamFrom(up, ctx, body, 1)
                .onErrorResume(err -> {
                    if (classify(err) == FailureKind.CONTRACT) {
                        return Flux.error(err);
                    }
                    if (idx + 1 < order.size()) {
                        return streamTier(order, idx + 1, ctx, body);
                    }
                    return Flux.error(err);
                });
    }

    private Flux<ServerSentEvent<String>> streamFrom(AiUpstream up, Ctx ctx, Map<String, Object> body, int attempt) {
        final long t0 = System.currentTimeMillis();
        final AtomicBoolean emitted = new AtomicBoolean(false);
        final AtomicBoolean sawAllComplete = new AtomicBoolean(false);

        return up.client().post()
                .uri(STREAM_PATH)
                .accept(MediaType.TEXT_EVENT_STREAM)
                .bodyValue(body)
                .retrieve()
                .bodyToFlux(SSE_TYPE)
                .timeout(settings.streamIdleTimeout())
                .concatMap(ev -> {
                    String event = ev.event() != null ? ev.event() : "message";
                    if (emitted.compareAndSet(false, true)) {
                        ctx.selectedUpstream.set(up.name());
                        ctx.mode.set("stream");
                        ctx.httpStatus.set(200);
                        markHealthy(up);
                        log.info("[AI-UPSTREAM] roomId={} requestId={} upstream={} tier=stream attempt={} first event='{}' after {}ms",
                                ctx.roomId, ctx.requestId, up.name(), attempt, event, System.currentTimeMillis() - t0);
                    }
                    if ("done".equals(event)) {
                        // done 은 Spring 이 마지막에 자체 생성한다(업스트림 done 은 삼킨다).
                        return Flux.<ServerSentEvent<String>>empty();
                    }
                    if ("error".equals(event) && isFatalErrorEvent(ev.data())) {
                        // 대상 에이전트가 특정되지 않은 fatal error = 업스트림 생성 실패 → failover.
                        return Flux.<ServerSentEvent<String>>error(new UpstreamFatalEventException(up.name()));
                    }
                    if ("all_complete".equals(event)) {
                        sawAllComplete.set(true);
                    }
                    return Flux.just(ev);
                })
                .concatWith(Flux.defer(() -> sawAllComplete.get()
                        ? Flux.<ServerSentEvent<String>>empty()
                        : Flux.<ServerSentEvent<String>>error(new UpstreamIncompleteException(up.name(), emitted.get()))))
                .onErrorResume(err -> {
                    FailureKind kind = classify(err);
                    long elapsed = System.currentTimeMillis() - t0;
                    Integer status = statusOf(err);
                    log.warn("[AI-UPSTREAM] roomId={} requestId={} upstream={} tier=stream attempt={} FAILED kind={} status={} emitted={} elapsedMs={} reason={}",
                            ctx.roomId, ctx.requestId, up.name(), attempt, kind, status, emitted.get(), elapsed, brief(err));
                    if (status != null) {
                        ctx.httpStatus.set(status);
                    }
                    if (kind == FailureKind.CONTRACT) {
                        return Flux.error(err);
                    }
                    // 첫 이벤트 전 실패만 같은 대상 재시도(짧은 지수 backoff). 이벤트를 이미 흘린 뒤엔 재생성 중복을 피해 다음 대상으로.
                    if (!emitted.get() && attempt < settings.attemptsPerUpstream()) {
                        Duration wait = backoff(attempt);
                        ctx.fallbackReasons.add(up.name() + ":stream#" + attempt + ":" + brief(err) + "→retry");
                        return Mono.delay(wait).thenMany(Flux.defer(() -> streamFrom(up, ctx, body, attempt + 1)));
                    }
                    openCircuit(up, err);
                    ctx.fallbackReasons.add(up.name() + ":stream#" + attempt + ":" + brief(err));
                    return Flux.error(new UpstreamExhaustedException(up.name() + " stream: " + brief(err), err));
                });
    }

    // ───────────────────────── non-stream 단계 ─────────────────────────

    private Mono<Map<String, Object>> nonStreamTier(List<AiUpstream> order, int idx, Ctx ctx,
                                                    Map<String, Object> body, Duration timeout, int attempt) {
        if (idx >= order.size()) {
            return Mono.error(new UpstreamExhaustedException("no non-stream upstream left"));
        }
        AiUpstream up = order.get(idx);
        final long t0 = System.currentTimeMillis();
        return up.client().post()
                .uri(NON_STREAM_PATH)
                .accept(MediaType.APPLICATION_JSON)
                .bodyValue(body)
                .retrieve()
                .bodyToMono(MAP_TYPE)
                .timeout(timeout)
                .doOnNext(resp -> {
                    ctx.selectedUpstream.set(up.name());
                    ctx.mode.set("non-stream");
                    ctx.httpStatus.set(200);
                    markHealthy(up);
                    log.info("[AI-UPSTREAM] roomId={} requestId={} upstream={} tier=non-stream attempt={} OK elapsedMs={}",
                            ctx.roomId, ctx.requestId, up.name(), attempt, System.currentTimeMillis() - t0);
                })
                .onErrorResume(err -> {
                    FailureKind kind = classify(err);
                    Integer status = statusOf(err);
                    log.warn("[AI-UPSTREAM] roomId={} requestId={} upstream={} tier=non-stream attempt={} FAILED kind={} status={} elapsedMs={} reason={}",
                            ctx.roomId, ctx.requestId, up.name(), attempt, kind, status, System.currentTimeMillis() - t0, brief(err));
                    if (status != null) {
                        ctx.httpStatus.set(status);
                    }
                    if (kind == FailureKind.CONTRACT) {
                        return Mono.error(err);
                    }
                    // 연결 단계 오류(refused/connect timeout)만 같은 대상 재시도. 생성 타임아웃/5xx 는 바로 다음 대상.
                    if (isConnectionError(err) && attempt < settings.attemptsPerUpstream()) {
                        ctx.fallbackReasons.add(up.name() + ":non-stream#" + attempt + ":" + brief(err) + "→retry");
                        return Mono.delay(backoff(attempt))
                                .then(Mono.defer(() -> nonStreamTier(order, idx, ctx, body, timeout, attempt + 1)));
                    }
                    openCircuit(up, err);
                    ctx.fallbackReasons.add(up.name() + ":non-stream#" + attempt + ":" + brief(err));
                    return nonStreamTier(order, idx + 1, ctx, body, timeout, 1);
                });
    }

    // ───────────────────────── 이벤트 빌더 ─────────────────────────

    private Flux<ServerSentEvent<String>> contractFailure(Ctx ctx, Throwable err) {
        ctx.result.set("contract_failure");
        Integer status = statusOf(err);
        log.error("[AI-CONTRACT] roomId={} requestId={} upstream={} status={} — 설정/계약 오류라 다른 서버로 숨기지 않고 종료합니다: {}",
                ctx.roomId, ctx.requestId, ctx.selectedUpstream.get(), status, brief(err));
        return Flux.just(errorEvent(ctx, "AI_CONTRACT_FAILURE",
                "AI 서버 요청 형식/인증 오류가 발생했습니다. 관리자에게 문의해 주세요."));
    }

    ServerSentEvent<String> errorEvent(Ctx ctx, String code, String message) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("type", "error");
        data.put("code", code);
        data.put("message", message);
        data.put("requestId", ctx.requestId);
        data.put("phase", "ERROR");
        data.put("visible", true);
        data.put("status", "error");
        return sse("error", toJson(data));
    }

    ServerSentEvent<String> doneEvent(Ctx ctx, String status) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("type", "done");
        data.put("status", status);
        data.put("requestId", ctx.requestId);
        data.put("phase", "DONE");
        data.put("visible", false);
        data.put("upstream", ctx.selectedUpstream.get());
        data.put("mode", ctx.mode.get());
        data.put("elapsedMs", ctx.elapsedMs());
        return sse("done", toJson(data));
    }

    /** non-stream 응답(JSON)을 스트림 계약의 all_complete 이벤트로 변환한다. */
    ServerSentEvent<String> allCompleteEvent(Map<String, Object> resp, Ctx ctx) {
        Map<String, Object> data = new LinkedHashMap<>(resp != null ? resp : Map.of());
        data.put("type", "all_complete");
        data.putIfAbsent("status", "COMPLETED");
        data.putIfAbsent("answers", List.of());
        Map<String, Object> fb = new LinkedHashMap<>();
        fb.put("upstream", ctx.selectedUpstream.get());
        fb.put("mode", "non-stream");
        fb.put("reason", ctx.fallbackReason());
        data.put("fallback", fb);
        data.put("requestId", ctx.requestId);
        return sse("all_complete", toJson(data));
    }

    private static ServerSentEvent<String> sse(String event, String json) {
        return ServerSentEvent.<String>builder(json).event(event).build();
    }

    private String toJson(Map<String, Object> data) {
        try {
            return objectMapper.writeValueAsString(data);
        } catch (Exception e) {
            return "{}";
        }
    }

    /** 업스트림 error 이벤트가 특정 에이전트(agentIndex/agentId) 범위가 아니면 fatal 로 본다. */
    private boolean isFatalErrorEvent(String data) {
        if (data == null || data.isBlank()) {
            return true;
        }
        try {
            Map<String, Object> m = objectMapper.readValue(data, new TypeReference<Map<String, Object>>() {});
            return m.get("agentIndex") == null && m.get("agentId") == null;
        } catch (Exception e) {
            return true;
        }
    }

    // ───────────────────────── 분류/유틸 ─────────────────────────

    public static FailureKind classify(Throwable err) {
        Throwable t = unwrap(err);
        if (t instanceof WebClientResponseException wre) {
            int s = wre.getStatusCode().value();
            if (s == 400 || s == 401 || s == 403 || s == 422) {
                return FailureKind.CONTRACT;
            }
            if (s == 404 || s == 405 || s >= 500) {
                return FailureKind.FAILOVER;
            }
            return s >= 400 && s < 500 ? FailureKind.CONTRACT : FailureKind.FAILOVER;
        }
        return FailureKind.FAILOVER;
    }

    static boolean isConnectionError(Throwable err) {
        Throwable t = unwrap(err);
        if (t instanceof WebClientRequestException) {
            Throwable c = t.getCause();
            if (c instanceof ConnectException) {
                return true;
            }
            String cn = c != null ? c.getClass().getSimpleName() : "";
            String msg = String.valueOf(t.getMessage());
            return cn.contains("ConnectTimeout") || msg.contains("Connection refused") || msg.contains("connection timed out");
        }
        return t instanceof ConnectException;
    }

    private static Integer statusOf(Throwable err) {
        Throwable t = unwrap(err);
        if (t instanceof WebClientResponseException wre) {
            HttpStatusCode sc = wre.getStatusCode();
            // 2xx 뒤 본문 중단은 "HTTP 상태 실패"가 아니므로 상태코드를 실패 원인으로 기록하지 않는다.
            return sc.is2xxSuccessful() ? null : sc.value();
        }
        return null;
    }

    private static Throwable unwrap(Throwable err) {
        Throwable t = err;
        while (t instanceof UpstreamExhaustedException && t.getCause() != null) {
            t = t.getCause();
        }
        return t;
    }

    private Duration backoff(int attempt) {
        long base = settings.backoff().toMillis();
        long ms = Math.min(2000L, base * (1L << Math.max(0, attempt - 1)));
        long jitter = ThreadLocalRandom.current().nextLong(0, Math.max(1, ms / 4));
        return Duration.ofMillis(ms + jitter);
    }

    static String brief(Throwable err) {
        if (err == null) {
            return "null";
        }
        Throwable t = err;
        if (t instanceof WebClientResponseException wre) {
            String path = wre.getRequest() != null ? wre.getRequest().getMethod() + " " + wre.getRequest().getURI().getPath() : "";
            if (wre.getStatusCode().is2xxSuccessful()) {
                // 응답은 200 이었지만 본문 스트림이 중간에 끊긴 경우(premature close 등): 상태코드가 아니라 원인을 남긴다.
                Throwable c = wre.getCause();
                return "stream aborted after HTTP 200 (" + (c != null ? c.getClass().getSimpleName() + ": " + c.getMessage() : wre.getMessage()) + ") " + path;
            }
            return "HTTP " + wre.getStatusCode().value() + " " + path;
        }
        if (t instanceof TimeoutException) {
            return "timeout";
        }
        if (t instanceof WebClientRequestException) {
            Throwable c = t.getCause();
            return "request: " + (c != null ? c.getClass().getSimpleName() + ": " + c.getMessage() : t.getMessage());
        }
        if (t instanceof IOException) {
            return t.getClass().getSimpleName() + ": " + t.getMessage();
        }
        String m = t.getMessage();
        String s = t.getClass().getSimpleName() + (m != null ? ": " + m : "");
        return s.length() > 200 ? s.substring(0, 200) : s;
    }

    private String describeUpstreams() {
        StringBuilder sb = new StringBuilder();
        for (AiUpstream up : upstreams.ordered()) {
            if (sb.length() > 0) {
                sb.append(", ");
            }
            sb.append(up.name()).append('=').append(up.baseUrl());
        }
        return sb.toString();
    }

    private void logSummary(Ctx ctx, String signal) {
        log.info("[AI-STREAM-RESULT] roomId={} requestId={} upstream={} mode={} httpStatus={} fallbackReason=\"{}\" elapsedMs={} result={} allComplete={} eventsRelayed={} signal={}",
                ctx.roomId, ctx.requestId, ctx.selectedUpstream.get(), ctx.mode.get(), ctx.httpStatus.get(),
                ctx.fallbackReason(), ctx.elapsedMs(), ctx.result.get(), ctx.allComplete.get(), ctx.relayed.get(), signal);
    }

    // ───────────────────────── 내부 예외 ─────────────────────────

    /** 한 업스트림의 stream/non-stream 시도가 모두 소진됨(failover 대상). */
    public static final class UpstreamExhaustedException extends RuntimeException {
        public UpstreamExhaustedException(String msg) { super(msg); }
        public UpstreamExhaustedException(String msg, Throwable cause) { super(msg, cause); }
    }

    /** 업스트림이 fatal error 이벤트(대상 에이전트 미특정)를 보냄(failover 대상). */
    public static final class UpstreamFatalEventException extends RuntimeException {
        public UpstreamFatalEventException(String upstream) { super(upstream + " sent fatal error event"); }
    }

    /** 업스트림 스트림이 all_complete 없이 닫힘(premature close 등, failover 대상). */
    public static final class UpstreamIncompleteException extends RuntimeException {
        public UpstreamIncompleteException(String upstream, boolean emitted) {
            super(upstream + " stream closed without all_complete (emitted=" + emitted + ")");
        }
    }
}
