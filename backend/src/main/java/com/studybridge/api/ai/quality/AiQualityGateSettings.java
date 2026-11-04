package com.studybridge.api.ai.quality;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Global Response Quality Gate 설정(환경변수, 기본 OFF).
 *  · enabled=false: 기존 동작 그대로(게이트 미적용). 보안·동의·소유권 검사는 이 플래그와 무관하게 항상 적용된다.
 *  · enabled=true : 사용자 노출 AI 결과는 response-quality.v1 승인(80점 규칙)을 통과한 것만 노출·저장·캐시한다.
 *    게이트가 연결되지 않은 사용자 노출 AI 경로는 AiQualityGateCoverage 가 503(AI_QUALITY_GATE_NOT_WIRED)으로 막는다.
 *  · 최소 점수는 계약상 80 고정(설정 불가). 재생성은 0..2 회로 제한.
 */
@Component
public class AiQualityGateSettings {

    private final boolean enabled;
    private final int maxRegenerations;
    private final long evaluateTimeoutMs;
    private final int maxConcurrency;
    private final long queueWaitMs;
    private final int circuitFailureThreshold;
    private final long circuitOpenMs;
    private final String evaluatePath;
    private final int streamMaxMessageChars;
    private final int streamMaxTotalChars;

    public AiQualityGateSettings(
            @Value("${ai.quality-gate.enabled:${AI_RESPONSE_QUALITY_GATE_ENABLED:false}}") boolean enabled,
            @Value("${ai.quality-gate.max-regenerations:${AI_QUALITY_MAX_REGENERATIONS:2}}") int maxRegenerations,
            @Value("${ai.quality-gate.evaluate-timeout-ms:${AI_QUALITY_EVALUATE_TIMEOUT_MS:8000}}") long evaluateTimeoutMs,
            @Value("${ai.quality-gate.max-concurrency:${AI_QUALITY_EVAL_MAX_CONCURRENCY:2}}") int maxConcurrency,
            @Value("${ai.quality-gate.queue-wait-ms:${AI_QUALITY_EVAL_QUEUE_WAIT_MS:2000}}") long queueWaitMs,
            @Value("${ai.quality-gate.circuit-failure-threshold:${AI_QUALITY_CIRCUIT_FAILURE_THRESHOLD:5}}") int circuitFailureThreshold,
            @Value("${ai.quality-gate.circuit-open-ms:${AI_QUALITY_CIRCUIT_OPEN_MS:30000}}") long circuitOpenMs,
            @Value("${ai.quality-gate.evaluate-path:${AI_QUALITY_EVALUATE_PATH:/api/ai/quality/evaluate}}") String evaluatePath,
            @Value("${ai.quality-gate.stream-max-message-chars:60000}") int streamMaxMessageChars,
            @Value("${ai.quality-gate.stream-max-total-chars:400000}") int streamMaxTotalChars) {
        this.enabled = enabled;
        this.maxRegenerations = Math.max(0, Math.min(2, maxRegenerations));
        this.evaluateTimeoutMs = Math.max(500, evaluateTimeoutMs);
        this.maxConcurrency = Math.max(1, maxConcurrency);
        this.queueWaitMs = Math.max(0, queueWaitMs);
        this.circuitFailureThreshold = Math.max(1, circuitFailureThreshold);
        this.circuitOpenMs = Math.max(1000, circuitOpenMs);
        this.evaluatePath = evaluatePath;
        this.streamMaxMessageChars = Math.max(1000, streamMaxMessageChars);
        this.streamMaxTotalChars = Math.max(this.streamMaxMessageChars, streamMaxTotalChars);
    }

    public static AiQualityGateSettings forTest(boolean enabled) {
        return new AiQualityGateSettings(enabled, 2, 2000, 2, 200, 3, 1000, "/api/ai/quality/evaluate", 60000, 400000);
    }

    public boolean enabled() { return enabled; }

    public int maxRegenerations() { return maxRegenerations; }

    public long evaluateTimeoutMs() { return evaluateTimeoutMs; }

    public int maxConcurrency() { return maxConcurrency; }

    public long queueWaitMs() { return queueWaitMs; }

    public int circuitFailureThreshold() { return circuitFailureThreshold; }

    public long circuitOpenMs() { return circuitOpenMs; }

    public String evaluatePath() { return evaluatePath; }

    public int streamMaxMessageChars() { return streamMaxMessageChars; }

    public int streamMaxTotalChars() { return streamMaxTotalChars; }
}
