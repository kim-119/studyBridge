package com.studybridge.api.ai.memory;

import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.LearningContextV1;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * Learning Memory(learning-context.v1 → ai07 multi-chat) 설정. 기본 OFF.
 *  · enabled=false(기본): ChatService 는 조립기를 부르지 않는다 → ai07 요청 바이트·헤더가 기존과 같다.
 *  · maxTotalChars: contextItems content 합계 상한(코드포인트, 기본 6000). 계약 상한 24000 을 넘을 수 없다.
 *  · maxItemChars : 항목 하나의 상한(기본 1200, 계약 상한 4000).
 *  · scopeTtlSeconds: X-AI-Scope 토큰 수명(기본·최대 120초).
 */
@Component
public class LearningMemorySettings {

    public static final int MAX_SCOPE_TTL_SECONDS = 120;

    private final boolean enabled;
    private final int maxTotalChars;
    private final int maxItemChars;
    private final int chatTurns;
    private final int pdfChunks;
    private final int scopeTtlSeconds;

    public LearningMemorySettings(
            @Value("${ai.learning-memory.enabled:${AI_LEARNING_MEMORY_ENABLED:false}}") boolean enabled,
            @Value("${ai.learning-memory.max-total-chars:${AI_LEARNING_MEMORY_MAX_TOTAL_CHARS:6000}}") int maxTotalChars,
            @Value("${ai.learning-memory.max-item-chars:${AI_LEARNING_MEMORY_MAX_ITEM_CHARS:1200}}") int maxItemChars,
            @Value("${ai.learning-memory.chat-turns:${AI_LEARNING_MEMORY_CHAT_TURNS:8}}") int chatTurns,
            @Value("${ai.learning-memory.pdf-chunks:${AI_LEARNING_MEMORY_PDF_CHUNKS:2}}") int pdfChunks,
            @Value("${ai.learning-memory.scope-ttl-seconds:${AI_LEARNING_MEMORY_SCOPE_TTL_SECONDS:120}}") int scopeTtlSeconds) {
        this.enabled = enabled;
        this.maxTotalChars = clamp(maxTotalChars, 256, LearningContextV1.MAX_TOTAL_CHARS);
        this.maxItemChars = clamp(maxItemChars, 80, LearningContextV1.MAX_ITEM_CHARS);
        this.chatTurns = clamp(chatTurns, 0, 20);
        this.pdfChunks = clamp(pdfChunks, 0, 8);
        this.scopeTtlSeconds = clamp(scopeTtlSeconds, 1, Math.min(MAX_SCOPE_TTL_SECONDS, AiContractSigning.MAX_TOKEN_TTL_SECONDS));
    }

    public static LearningMemorySettings forTest(boolean enabled) {
        return new LearningMemorySettings(enabled, 6000, 1200, 8, 2, 120);
    }

    public static LearningMemorySettings forTest(boolean enabled, int maxTotalChars, int maxItemChars) {
        return new LearningMemorySettings(enabled, maxTotalChars, maxItemChars, 8, 2, 120);
    }

    private static int clamp(int v, int lo, int hi) {
        return Math.max(lo, Math.min(hi, v));
    }

    public boolean enabled() { return enabled; }

    public int maxTotalChars() { return maxTotalChars; }

    public int maxItemChars() { return maxItemChars; }

    public int chatTurns() { return chatTurns; }

    public int pdfChunks() { return pdfChunks; }

    public int scopeTtlSeconds() { return scopeTtlSeconds; }
}
