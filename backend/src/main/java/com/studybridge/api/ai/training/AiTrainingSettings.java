package com.studybridge.api.ai.training;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 학습 후보 수집/전달 설정(모두 기본 OFF).
 *  · collection-enabled=false: 승인 답변이 있어도 outbox 행을 만들지 않는다(동의 API 는 항상 동작 — 동의 기록·철회는 플래그와 무관).
 *  · dispatch-enabled=false : outbox 를 ai07 로 보내지 않는다(행은 PENDING 으로 남음). ai07 collect-v1 도 기본 503 COLLECTION_DISABLED.
 *  · consent-version: 현재 고지문 버전. 다른 버전으로 받은 동의는 유효하지 않다(재동의 필요).
 */
@Component
public class AiTrainingSettings {

    private final boolean collectionEnabled;
    private final boolean dispatchEnabled;
    private final String consentVersion;
    private final String collectPath;
    private final String withdrawalPath;
    private final String deletionPath;
    private final int maxAttempts;
    private final int batchSize;
    private final long sendTimeoutMs;

    public AiTrainingSettings(
            @Value("${ai.training.collection-enabled:${AI_TRAINING_COLLECTION_ENABLED:false}}") boolean collectionEnabled,
            @Value("${ai.training.dispatch-enabled:${AI_TRAINING_OUTBOX_DISPATCH_ENABLED:false}}") boolean dispatchEnabled,
            @Value("${ai.training.consent-version:tc-2026-11}") String consentVersion,
            @Value("${ai.training.collect-path:/api/training-candidates/collect-v1}") String collectPath,
            @Value("${ai.training.withdrawal-path:/api/training-candidates/consent-withdrawal}") String withdrawalPath,
            @Value("${ai.training.deletion-path:/api/training-candidates/deletion}") String deletionPath,
            @Value("${ai.training.max-attempts:8}") int maxAttempts,
            @Value("${ai.training.batch-size:20}") int batchSize,
            @Value("${ai.training.send-timeout-ms:10000}") long sendTimeoutMs) {
        this.collectionEnabled = collectionEnabled;
        this.dispatchEnabled = dispatchEnabled;
        this.consentVersion = consentVersion;
        this.collectPath = collectPath;
        this.withdrawalPath = withdrawalPath;
        this.deletionPath = deletionPath;
        this.maxAttempts = Math.max(1, maxAttempts);
        this.batchSize = Math.max(1, Math.min(100, batchSize));
        this.sendTimeoutMs = Math.max(1000, sendTimeoutMs);
    }

    public static AiTrainingSettings forTest(boolean collection, boolean dispatch) {
        return new AiTrainingSettings(collection, dispatch, "tc-2026-11", "/api/training-candidates/collect-v1",
                "/api/training-candidates/consent-withdrawal", "/api/training-candidates/deletion", 3, 20, 3000);
    }

    public boolean collectionEnabled() { return collectionEnabled; }

    public boolean dispatchEnabled() { return dispatchEnabled; }

    public String consentVersion() { return consentVersion; }

    public String collectPath() { return collectPath; }

    public String withdrawalPath() { return withdrawalPath; }

    public String deletionPath() { return deletionPath; }

    public int maxAttempts() { return maxAttempts; }

    public int batchSize() { return batchSize; }

    public long sendTimeoutMs() { return sendTimeoutMs; }
}
