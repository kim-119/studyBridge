package com.studybridge.api.config;

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
import java.util.concurrent.TimeUnit;

@Configuration
public class WebClientConfig {

    @Value("${ai.server.fastapi.base-url:http://localhost:8000}")
    private String fastApiBaseUrl;

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

    @Bean
    public WebClient fastApiWebClient(WebClient.Builder builder) {
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
                .baseUrl(fastApiBaseUrl)
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
