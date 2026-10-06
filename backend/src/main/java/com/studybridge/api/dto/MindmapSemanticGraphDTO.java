package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.List;

/**
 * 학습메이트 답변 → AI07 Semantic MindMap 릴레이 계약(브라우저 ↔ Spring).
 *
 * <p>브라우저는 AI07 내부 DTO 를 알지 못한다. Spring 이 AI07 응답(nodes/edges/sourceNodes/provenanceEdges/status)을
 * 아래 고정 형태(concepts/relations/sources/provenance/status)로 정규화해 내려준다.
 * 개념(concept) 노드의 유일한 출처는 AI07 이며, Spring/React 어디서도 답변 본문을 토큰화해 개념을 만들지 않는다.</p>
 */
public class MindmapSemanticGraphDTO {

    /** 상태값(단일 출처). FAILED 이면 브라우저는 개념 계층을 그리지 않고 명시적 실패 상태를 보여준다. */
    public static final String STATUS_OK = "OK";
    public static final String STATUS_DEGRADED = "DEGRADED";
    public static final String STATUS_FAILED = "FAILED";

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        /** 학습메이트 방 id(소유자 검증 + 캐시 네임스페이스). 필수. */
        private Long roomId;
        private String question;
        @Builder.Default
        private List<AnswerSource> answers = new ArrayList<>();
        /** true 면 캐시를 무시하고 재생성한다(사용자 명시 "다시 생성"). */
        private Boolean forceRefresh;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AnswerSource {
        private Long messageId;
        private String eventId;
        /** 교수(Agent) id — AI07 answers[].agentId(int|string|null) 로 전달된다. */
        private Long agentId;
        private String agentName;
        private String agentRole;
        private String content;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private String status;            // OK | DEGRADED (FAILED 는 HTTP 4xx/5xx 로 내려가며 200 본문에 오지 않는다)
        private boolean degraded;
        private String degradedReason;    // DEGRADED 사유 코드(로그·UI 식별용)
        @Builder.Default
        private List<String> degradedReasons = new ArrayList<>();
        private String schemaVersion;     // AI07 mindmap.semantic.v1
        private String extractor;         // llm | deterministic | null
        private String analyzer;          // kiwi | rules
        private String fingerprint;       // 동일 답변 재요청 식별자(캐시 키 일부)
        private boolean cached;           // 캐시에서 응답했는지
        private Integer rejectedCount;    // AI07 이 거른 표면형/불용어 후보 수(디버그 표시용)
        @Builder.Default
        private java.util.Map<String, Object> stats = new java.util.LinkedHashMap<>();
        @Builder.Default
        private List<Concept> concepts = new ArrayList<>();
        @Builder.Default
        private List<Relation> relations = new ArrayList<>();
        @Builder.Default
        private List<Source> sources = new ArrayList<>();
        @Builder.Default
        private List<Provenance> provenance = new ArrayList<>();
    }

    /** 개념 노드. level: 0=core, 1=primary, 2=secondary(이후는 2로 clamp). */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Concept {
        private String id;
        private String label;             // AI07 canonicalLabel(없으면 label) 그대로
        private Integer level;            // 0=CORE, 1=PRIMARY, 2=SECONDARY
        private String levelName;         // CORE | PRIMARY | SECONDARY
        private String parentId;
        @Builder.Default
        private List<String> aliases = new ArrayList<>();
        @Builder.Default
        private List<String> surfaceForms = new ArrayList<>();
        private Integer mentions;
        private String description;
    }

    /** 개념 ↔ 개념 의미 관계(정의/목적/수행/구성 요소 ...). label 은 AI07 이 준 관계명 그대로. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Relation {
        private String id;
        private String from;
        private String to;
        private String label;             // AI07 relation(정의/목적/구성 요소/...)
        private String type;              // AI07 kind(topic|semantic)
        private String relationKey;       // TOPIC|DEFINITION|PURPOSE|COMPONENT|PERFORMS|STEP|CAUSE|EFFECT|FEATURE|COMPARISON|EXAMPLE|RELATED
    }

    /** 출처(교수/에이전트) 노드 — 개념이 아니다. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Source {
        private String id;
        private String label;
        private String kind;      // agent
        private String agentKey;
        private String agentName;
        private String agentRole;
    }

    /** 출처 → 개념 provenance 간선. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Provenance {
        private String id;
        private String from;
        private String to;
        private String label;      // 출처
        private String relationKey; // SOURCE
    }
}
