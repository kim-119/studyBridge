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
