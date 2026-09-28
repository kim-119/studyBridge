package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * AI07 FINAL CONTRACT — {@code POST /api/ai/mindmap/semantic-graph} 의 typed 요청/응답(Spring ↔ AI07 전용).
 * 브라우저에는 노출되지 않는다(브라우저 계약은 {@link MindmapSemanticGraphDTO}).
 *
 * <p>계약 필드는 손실 없이 받는다. 미래 호환을 위해 unknown 필드만 무시한다.</p>
 */
public class MindMapAiDTO {

    public static final String SCHEMA_VERSION = "mindmap.semantic.v1";
    public static final int MAX_QUESTION = 2000;
    public static final int MAX_ANSWERS = 12;
    public static final int MAX_CONTENT = 20000;
    public static final int MAX_AGENT_NAME = 100;
    public static final int MAX_ROLE = 100;

    // ── Request ─────────────────────────────────────────────────────────────

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class MindMapAiRequest {
        @Builder.Default
        private String question = "";
        @Builder.Default
        private List<Answer> answers = new ArrayList<>();
        @Builder.Default
        private Boolean useLlm = Boolean.TRUE;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Answer {
        private String content;
        /** int | string | null — AI07 계약이 혼합 타입을 허용하므로 Object 로 둔다. */
        private Object agentId;
        private String agentName;
        private String role;
    }

    // ── Response ────────────────────────────────────────────────────────────

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class MindMapAiResponse {
        private String schemaVersion;
        private String question;
        private String status;              // OK | DEGRADED | FAILED
        private Boolean degraded;
        private String degradedReason;
        @Builder.Default
        private List<String> degradedReasons = new ArrayList<>();
        private String extractor;           // llm | deterministic | null
        private String analyzer;            // kiwi | rules
        private String analyzerDetail;
        @Builder.Default
        private List<Node> nodes = new ArrayList<>();
        @Builder.Default
        private List<Edge> edges = new ArrayList<>();
        @Builder.Default
        private List<Node> sourceNodes = new ArrayList<>();
        @Builder.Default
        private List<Edge> provenanceEdges = new ArrayList<>();
        @Builder.Default
        private Map<String, Object> stats = new LinkedHashMap<>();
        @Builder.Default
        private List<RejectedConcept> rejected = new ArrayList<>();
        @Builder.Default
        private List<Object> validationErrors = new ArrayList<>();
        // FAILED(422/500/504) 본문에 함께 올 수 있는 메시지 필드(있으면 보존).
        private String message;
        private String errorCode;
        private Object detail;
    }

    /**
     * Concept / Question / Source 노드 공통 typed 표현.
     *  concept: id=c_*, type=concept, level=CORE|PRIMARY|SECONDARY, label, canonicalLabel, aliases, surfaceForms, sources, extractedBy, mentions, visible
     *  question: id=q_*, type=question, level=QUESTION, label, body, visible
     *  source: id=s_*, type=agent, level=SOURCE, label, agentKey
     */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Node {
        private String id;
        private String type;
        private String level;
        private String label;
        private String canonicalLabel;
        private String body;
        @Builder.Default
        private List<String> aliases = new ArrayList<>();
        @Builder.Default
        private List<String> surfaceForms = new ArrayList<>();
        @Builder.Default
        private List<Object> sources = new ArrayList<>();
        @Builder.Default
        private List<String> extractedBy = new ArrayList<>();
        private Integer mentions;
        private Boolean visible;
        private String agentKey;
    }

    /** kind: topic | semantic | provenance. relationKey: TOPIC|DEFINITION|PURPOSE|COMPONENT|PERFORMS|STEP|CAUSE|EFFECT|FEATURE|COMPARISON|EXAMPLE|RELATED|SOURCE */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Edge {
        private String id;
        private String from;
        private String to;
        private String kind;
        private String relation;
        private String relationKey;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class RejectedConcept {
        private String label;
        private String canonicalLabel;
        private String surfaceForm;
        private String reason;
    }
}
