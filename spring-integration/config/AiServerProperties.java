package com.studybridge.config;  // TODO: 실제 패키지 경로로 변경

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * AI 서버(FastAPI) 연결 설정.
 * application.yml의 ai.server.* 값을 바인딩한다.
 *
 * <pre>
 * ai:
 *   server:
 *     base-url: http://localhost:8000
 *     api-key: studybridge-internal-secret
 *     connect-timeout-ms: 5000
 *     read-timeout-ms: 60000
 * </pre>
 */
@Component
@ConfigurationProperties(prefix = "ai.server")
public class AiServerProperties {

    private String baseUrl = "http://localhost:8000";
    private String apiKey  = "";
    private long   connectTimeoutMs = 5000L;
    private long   readTimeoutMs    = 60000L;

    // ── Getters / Setters ──────────────────────────────────────────────

    public String getBaseUrl()               { return baseUrl; }
    public void   setBaseUrl(String v)       { this.baseUrl = v; }

    public String getApiKey()                { return apiKey; }
    public void   setApiKey(String v)        { this.apiKey = v; }

    public long   getConnectTimeoutMs()      { return connectTimeoutMs; }
    public void   setConnectTimeoutMs(long v){ this.connectTimeoutMs = v; }

    public long   getReadTimeoutMs()         { return readTimeoutMs; }
    public void   setReadTimeoutMs(long v)   { this.readTimeoutMs = v; }
}
