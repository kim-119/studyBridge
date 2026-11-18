package com.studybridge.api.config;

import com.studybridge.api.ai.AiFailoverSettings;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import io.netty.channel.ChannelOption;
import io.netty.handler.timeout.ReadTimeoutHandler;
import io.netty.handler.timeout.WriteTimeoutHandler;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.netty.http.client.HttpClient;
import reactor.netty.resources.ConnectionProvider;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

@Configuration
public class WebClientConfig {

    // PRIMARY(ai07 터널). 레거시 키 base-url 과 primary-base-url 은 같은 env(FASTAPI_PRIMARY_BASE_URL→FASTAPI_BASE_URL)로 해석된다.
    @Value("${ai.server.fastapi.primary-base-url:${ai.server.fastapi.base-url:http://localhost:8000}}")
    private String fastApiBaseUrl;

    // SECONDARY(EC2 로컬 hot-standby :8000). 비어 있으면 secondary 없이 primary 단독.
    @Value("${ai.server.fastapi.secondary-base-url:}")
    private String fastApiSecondaryBaseUrl;

    @Value("${ai.server.fastapi.failover.attempts-per-upstream:2}")
    private int failoverAttemptsPerUpstream;
    @Value("${ai.server.fastapi.failover.backoff-ms:400}")
    private long failoverBackoffMs;
    @Value("${ai.server.fastapi.failover.circuit-cooldown-seconds:15}")
    private long failoverCircuitCooldownSeconds;
    @Value("${ai.server.fastapi.failover.probe-interval-seconds:15}")
    private long failoverProbeIntervalSeconds;
    @Value("${ai.server.fastapi.failover.stream-idle-timeout-seconds:180}")
    private long failoverStreamIdleTimeoutSeconds;
    @Value("${ai.server.fastapi.failover.total-timeout-seconds:900}")
    private long failoverTotalTimeoutSeconds;

    // Intent Router 베이스 URL. 기본값은 기존 FastAPI 베이스(EC2에선 host.docker.internal:18000).
    @Value("${ai.intent-router.base-url:${ai.server.fastapi.base-url:http://localhost:8000}}")
    private String intentRouterBaseUrl;

    // Intent Router 호출은 빠른 분기 판단이므로 짧은 응답 타임아웃(ms)을 둔다.
    @Value("${ai.intent-router.timeout-ms:6000}")
    private long intentRouterTimeoutMs;

    // 하드 상한(connector 레벨). 소크라테스/토론 모드는 오래 걸리므로 충분히 크게 둔다.
    // 실제 요청별 제한은 ChatService의 block(Duration) / per-request responseTimeout로 모드별 제어한다.
    private static final int CONNECT_TIMEOUT_MS = 5000;

    @Value("${ai.server.fastapi.read-timeout-seconds:1800}")
    private int readTimeoutSeconds;

    private static final int WRITE_TIMEOUT_SECONDS = 30;

    // 긴 답변 허용을 위한 코덱 인메모리 버퍼 상한 (기본 256KB → 16MB).
    private static final int MAX_IN_MEMORY_BYTES = 16 * 1024 * 1024;

    /** 기존 서비스들이 주입받는 FastAPI 클라이언트 = PRIMARY 업스트림. */
    @Bean
    public WebClient fastApiWebClient(WebClient.Builder builder) {
        return buildFastApiClient(builder.clone(), fastApiBaseUrl);
    }

    /**
     * PRIMARY → SECONDARY 순서가 고정된 업스트림 목록(멀티에이전트 채팅 failover 전용).
     * secondary-base-url 이 비었거나 primary 와 같으면 primary 단독으로 구성한다.
     */
    @Bean
    public AiUpstreams aiUpstreams(WebClient fastApiWebClient, WebClient.Builder builder) {
        List<AiUpstream> list = new ArrayList<>();
        list.add(new AiUpstream("primary", fastApiBaseUrl.trim(), fastApiWebClient));
        String secondary = fastApiSecondaryBaseUrl == null ? "" : fastApiSecondaryBaseUrl.trim();
        if (!secondary.isEmpty() && !secondary.equalsIgnoreCase(fastApiBaseUrl.trim())) {
            list.add(new AiUpstream("secondary", secondary, buildFastApiClient(builder.clone(), secondary)));
        }
        return new AiUpstreams(list);
    }

    @Bean
    public AiFailoverSettings aiFailoverSettings() {
        return AiFailoverSettings.defaults()
                .attemptsPerUpstream(failoverAttemptsPerUpstream)
                .backoff(Duration.ofMillis(Math.max(50, failoverBackoffMs)))
                .circuitCooldown(Duration.ofSeconds(Math.max(1, failoverCircuitCooldownSeconds)))
                .probeInterval(Duration.ofSeconds(Math.max(5, failoverProbeIntervalSeconds)))
                .streamIdleTimeout(Duration.ofSeconds(Math.max(30, failoverStreamIdleTimeoutSeconds)))
                .totalTimeout(Duration.ofSeconds(Math.max(60, failoverTotalTimeoutSeconds)));
    }

    private WebClient buildFastApiClient(WebClient.Builder builder, String baseUrl) {
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(Duration.ofSeconds(readTimeoutSeconds))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(readTimeoutSeconds, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS)));

        // 긴 AI 답변(협업/검증/토론)에서 기본 코덱 버퍼(256KB) 초과로 응답이 잘리거나 실패하지 않도록 상향.
        ExchangeStrategies exchangeStrategies = ExchangeStrategies.builder()
                .codecs(configurer -> configurer.defaultCodecs().maxInMemorySize(MAX_IN_MEMORY_BYTES))
                .build();

        return builder
                .baseUrl(baseUrl)
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .exchangeStrategies(exchangeStrategies)
                .build();
    }

    // 화면공유 AI 분석(ai07 Vision) 전용 타임아웃. ai07 최악 대기(VisionGate 120s + GPU 슬롯 30s) + 추론 90s = 240s 보다 길게.
    //  공용 FASTAPI_TIMEOUT(180s, PDF 추출)·read-timeout-seconds(1800s, 멀티챗 스트림)와 분리해 서로 영향을 주지 않는다.
    @Value("${ai.vision.timeout-seconds:260}")
    private int visionTimeoutSeconds;

    // 화면공유 AI 전용 연결 풀(ai.vision.pool.*). 다른 클라이언트는 HttpClient.create() = reactor-netty 전역 풀(주소당 16연결)을
    //  ai07 :18000 에 함께 쓰므로, 비전이 그 풀을 점유하지 않도록 따로 둔다.
    //  max-connections 2 = ai07 GPU 동시 추론 1(VISION_MAX_CONCURRENCY·비전 Ollama NUM_PARALLEL) + 다음 1건 대기. 그룹당 한도(2)도 같다.
    //  pending-acquire-max 8 = ai07 VISION_MAX_QUEUE 와 같은 대기 규모. 넘치면 즉시 429(SCREEN_AI_BUSY).
    //  acquire-timeout 45s = 연결 획득(대기열) 제한. 응답 제한(timeout-seconds)과 별개이며, 45 + 앞선 1건 90 + GPU 슬롯 30 + 추론 90 < 260.
    //  max-idle 4s = ai07 uvicorn keep-alive(기본 5s)보다 먼저 유휴 연결을 버려, 서버가 닫는 중인 연결에 요청을 싣지 않는다.
    @Value("${ai.vision.pool.max-connections:2}")
    private int visionMaxConnections;
    @Value("${ai.vision.pool.pending-acquire-max:8}")
    private int visionPendingAcquireMax;
    @Value("${ai.vision.pool.acquire-timeout-seconds:45}")
    private int visionAcquireTimeoutSeconds;
    @Value("${ai.vision.pool.max-idle-seconds:4}")
    private int visionMaxIdleSeconds;

    @Bean(destroyMethod = "dispose")
    public ConnectionProvider visionConnectionProvider() {
        return visionConnectionProviderBuilder(visionMaxConnections, visionPendingAcquireMax,
                Duration.ofSeconds(Math.max(1, visionAcquireTimeoutSeconds)), Duration.ofSeconds(Math.max(1, visionMaxIdleSeconds)))
                .build();
    }

    static ConnectionProvider.Builder visionConnectionProviderBuilder(int maxConnections, int pendingAcquireMax,
                                                                      Duration acquireTimeout, Duration maxIdleTime) {
        return ConnectionProvider.builder("screen-ai-vision")
                .maxConnections(Math.max(1, maxConnections))
                .pendingAcquireMaxCount(Math.max(1, pendingAcquireMax))
                .pendingAcquireTimeout(acquireTimeout)
                .maxIdleTime(maxIdleTime);
    }

    static HttpClient visionHttpClient(ConnectionProvider provider, int timeoutSeconds) {
        int timeout = Math.max(30, timeoutSeconds);
        return HttpClient.create(provider)
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(Duration.ofSeconds(timeout))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(timeout, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS)));
    }

    /**
     * ai07 Vision 전용 WebClient = PRIMARY(ai07 터널) 고정. secondary(EC2 :8000)는 키가 다르고 비전 데몬이 없어 failover 하지 않는다.
     * 응답은 JSON 한 건(답변 최대 6000자)이라 코덱 버퍼는 1MB 면 충분하다.
     */
    @Bean
    public WebClient visionWebClient(WebClient.Builder builder, ConnectionProvider visionConnectionProvider) {
        return builder.clone()
                .baseUrl(fastApiBaseUrl)
                .clientConnector(new ReactorClientHttpConnector(visionHttpClient(visionConnectionProvider, visionTimeoutSeconds)))
                .exchangeStrategies(ExchangeStrategies.builder()
                        .codecs(configurer -> configurer.defaultCodecs().maxInMemorySize(1024 * 1024))
                        .build())
                .build();
    }

    // AI 학습 내비게이터(ai07 적응형 학습 엔진 /api/ai/planner/adaptive) 전용 응답 상한. ai07 요청 예산 30초(LLM 이 늦으면 규칙 결과로 200)
    //  + 여유 → 45초. 공용 fastApiWebClient(1800s)·비전(260s)·FASTAPI_TIMEOUT 과 분리해 서로 영향을 주지 않는다.
    @Value("${ai.planner.adaptive.timeout-seconds:45}")
    private int adaptiveTimeoutSeconds;
    // 전용 연결 풀: max-connections 8 = ai07 전체 동시 처리 한도(ADAPTIVE_MAX_INFLIGHT). 넘치는 요청은 짧게 기다린 뒤 429.
    //  max-idle 4s = ai07 uvicorn keep-alive(5s)보다 먼저 유휴 연결을 버려, 서버가 닫는 중인 연결에 요청을 싣지 않는다.
    @Value("${ai.planner.adaptive.pool.max-connections:8}")
    private int adaptiveMaxConnections;
    @Value("${ai.planner.adaptive.pool.pending-acquire-max:16}")
    private int adaptivePendingAcquireMax;
    @Value("${ai.planner.adaptive.pool.acquire-timeout-seconds:5}")
    private int adaptiveAcquireTimeoutSeconds;
    @Value("${ai.planner.adaptive.pool.max-idle-seconds:4}")
    private int adaptiveMaxIdleSeconds;

    /**
     * 적응형 학습 엔진 WebClient = PRIMARY(ai07 터널) 고정. secondary(EC2 :8000)는 키가 달라 failover 하지 않는다.
     * 연결 풀은 빈으로 등록하지 않는다(비전 풀 주입이 이름으로 해석되는 기존 구성을 건드리지 않기 위해).
     */
    @Bean
    public WebClient adaptivePlannerWebClient(WebClient.Builder builder) {
        ConnectionProvider provider = ConnectionProvider.builder("adaptive-planner")
                .maxConnections(Math.max(1, adaptiveMaxConnections))
                .pendingAcquireMaxCount(Math.max(1, adaptivePendingAcquireMax))
                .pendingAcquireTimeout(Duration.ofSeconds(Math.max(1, adaptiveAcquireTimeoutSeconds)))
                .maxIdleTime(Duration.ofSeconds(Math.max(1, adaptiveMaxIdleSeconds)))
                .build();
        int timeout = Math.max(40, adaptiveTimeoutSeconds);
        HttpClient httpClient = HttpClient.create(provider)
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(Duration.ofSeconds(timeout))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(timeout, TimeUnit.SECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS)));
        return builder.clone()
                .baseUrl(fastApiBaseUrl)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .exchangeStrategies(ExchangeStrategies.builder()
                        .codecs(configurer -> configurer.defaultCodecs().maxInMemorySize(2 * 1024 * 1024))
                        .build())
                .build();
    }

    /**
     * Intent Router 전용 WebClient. 짧은 connect/response 타임아웃(분기 판단용).
     * 실제 요청별 상한은 IntentRouterService의 block(timeoutMs)로 한 번 더 제어한다.
     */
    @Bean
    public WebClient intentRouterWebClient(WebClient.Builder builder) {
        int responseTimeoutMs = (int) Math.max(1000, intentRouterTimeoutMs);
        HttpClient httpClient = HttpClient.create()
                .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, CONNECT_TIMEOUT_MS)
                .responseTimeout(Duration.ofMillis(responseTimeoutMs))
                .doOnConnected(conn -> conn
                        .addHandlerLast(new ReadTimeoutHandler(responseTimeoutMs, TimeUnit.MILLISECONDS))
                        .addHandlerLast(new WriteTimeoutHandler(WRITE_TIMEOUT_SECONDS, TimeUnit.SECONDS)));

        return builder
                .baseUrl(intentRouterBaseUrl)
                .defaultHeader(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                .clientConnector(new ReactorClientHttpConnector(httpClient))
                .build();
    }
}
