package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * learning-context.v1 — Spring 이 조립해 ai07 로 보내는 사용자 학습 컨텍스트(EC2 canonical).
 *  · PDF 원문(PDF_ORIGINAL)과 AI 요약/과거 AI 답변/사용자 메모를 같은 신뢰로 다루지 않는다: trustLevel 은 sourceType 상한을
 *    넘을 수 없고(넘게 주장하면 수신측이 강등), EC2 는 처음부터 상한 이하로만 보낸다.
 *  · materialId(Long, Spring materials PK) 와 documentId(문자열, pgvector 문서 식별자)는 서로 다른 식별자다.
 *  · content 는 항상 untrusted data — 수신측은 격리 블록(&lt;untrusted_*&gt;)으로만 프롬프트에 넣는다.
 *  · usedSources 는 실제 contextItems 의 id 만 가리킬 수 있다(단순 문자열 존재 ≠ 근거 사용).
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public record LearningContextV1(
        String schemaVersion,
        String requestId,
        String pseudonymousUserKey,
        Long materialId,
        String documentId,
        String currentQuestion,
        List<ContextItem> contextItems,
        Integer tokenBudget,
        List<String> usedSources) {

    public static final String SCHEMA_VERSION = "learning-context.v1";
    public static final int MAX_CONTEXT_ITEMS = 64;
    public static final int MAX_ITEM_CHARS = 4000;
    public static final int MAX_TOTAL_CHARS = 24000;

    public enum Kind {
        @JsonProperty("pdf_chunk") PDF_CHUNK,
        @JsonProperty("summary") SUMMARY,
        @JsonProperty("wrong_note") WRONG_NOTE,
        @JsonProperty("quiz_result") QUIZ_RESULT,
        @JsonProperty("planner_review") PLANNER_REVIEW,
        @JsonProperty("user_memo") USER_MEMO,
        @JsonProperty("chat_turn") CHAT_TURN,
        @JsonProperty("agent_feedback") AGENT_FEEDBACK
    }

    public enum SourceType { PDF_ORIGINAL, USER_PROVIDED_TEXT, AI_SUMMARY, AI_ANSWER, USER_MEMO, SYSTEM_RECORD, CHAT_MESSAGE }

    /** 낮은 → 높은 신뢰 순서(ordinal = rank). */
    public enum TrustLevel { AI_GENERATED, USER_ASSERTED, SYSTEM_RECORD, SOURCE_PRIMARY }

    public static final Map<SourceType, TrustLevel> MAX_TRUST_BY_SOURCE = Map.of(
            SourceType.PDF_ORIGINAL, TrustLevel.SOURCE_PRIMARY,
            SourceType.SYSTEM_RECORD, TrustLevel.SYSTEM_RECORD,
            SourceType.USER_PROVIDED_TEXT, TrustLevel.USER_ASSERTED,
            SourceType.USER_MEMO, TrustLevel.USER_ASSERTED,
            SourceType.CHAT_MESSAGE, TrustLevel.USER_ASSERTED,
            SourceType.AI_SUMMARY, TrustLevel.AI_GENERATED,
            SourceType.AI_ANSWER, TrustLevel.AI_GENERATED);

    public record Provenance(String origin, String legacyField, Double retrievalScore, String documentRevision,
                             List<String> notes) { }

    public record ContextItem(String id, Kind kind, String role, String content, SourceType sourceType, String sourceId,
                              String sourceRevisionHash, Integer page, String chunkId, OffsetDateTime createdAt,
                              String qualityStatus, Provenance provenance, TrustLevel trustLevel) {

        /** 적용 신뢰 = min(주장, sourceType 상한). */
        public TrustLevel effectiveTrust() {
            TrustLevel cap = MAX_TRUST_BY_SOURCE.get(sourceType);
            return trustLevel.ordinal() > cap.ordinal() ? cap : trustLevel;
        }
    }

    public static ContractJson.Violations validate(LearningContextV1 c) {
        ContractJson.Violations v = new ContractJson.Violations();
        if (c == null) {
            v.add("body:required");
            return v;
        }
        v.check(SCHEMA_VERSION.equals(c.schemaVersion()), "schemaVersion:unsupported");
        v.required(c.requestId(), "requestId");
        v.id(c.requestId(), ContractJson.ID_1_128, "requestId");
        v.check(ContractJson.pseudonymous(c.pseudonymousUserKey()), "pseudonymousUserKey:pseudonymous");
        v.check(c.materialId() == null || c.materialId() >= 1, "materialId:ge_1");
        v.id(c.documentId(), ContractJson.ID_1_128, "documentId");
        v.maxLen(c.currentQuestion(), 4000, "currentQuestion");
        v.check(c.tokenBudget() == null || (c.tokenBudget() >= 256 && c.tokenBudget() <= 32768), "tokenBudget:range");
        List<ContextItem> items = c.contextItems() == null ? List.of() : c.contextItems();
        v.check(items.size() <= MAX_CONTEXT_ITEMS, "contextItems:max_length");
        int total = 0;
        Set<String> ids = new HashSet<>();
        boolean duplicate = false;
        for (int i = 0; i < items.size(); i++) {
            ContextItem it = items.get(i);
            String f = "contextItems[" + i + "]";
            if (it == null) {
                v.add(f + ":required");
                continue;
            }
            v.required(it.id(), f + ".id");
            v.id(it.id(), ContractJson.ID_1_128, f + ".id");
            v.required(it.kind(), f + ".kind");
            v.required(it.content(), f + ".content");
            v.maxLen(it.content(), MAX_ITEM_CHARS, f + ".content");
            v.required(it.sourceType(), f + ".sourceType");
            v.required(it.sourceId(), f + ".sourceId");
            v.id(it.sourceId(), ContractJson.ID_1_128, f + ".sourceId");
            v.id(it.chunkId(), ContractJson.ID_1_128, f + ".chunkId");
            v.maxLen(it.sourceRevisionHash(), 128, f + ".sourceRevisionHash");
            v.check(it.page() == null || (it.page() >= 1 && it.page() <= 100000), f + ".page:range");
            v.required(it.createdAt(), f + ".createdAt");
            v.required(it.qualityStatus(), f + ".qualityStatus");
            v.maxLen(it.qualityStatus(), 32, f + ".qualityStatus");
            v.required(it.trustLevel(), f + ".trustLevel");
            // untrusted context 가 system 역할을 가장하지 못하게 user/assistant 만 허용
            v.check(it.role() == null || "user".equals(it.role()) || "assistant".equals(it.role()), f + ".role:user_or_assistant");
            Provenance p = it.provenance();
            v.required(p, f + ".provenance");
            if (p != null) {
                v.required(p.origin(), f + ".provenance.origin");
                v.maxLen(p.origin(), 64, f + ".provenance.origin");
                v.maxLen(p.legacyField(), 64, f + ".provenance.legacyField");
                v.maxLen(p.documentRevision(), 128, f + ".provenance.documentRevision");
                v.check(p.retrievalScore() == null || (p.retrievalScore() >= -1.0 && p.retrievalScore() <= 1.0),
                        f + ".provenance.retrievalScore:range");
                v.check(p.notes() == null || p.notes().size() <= 8, f + ".provenance.notes:max_length");
            }
            if (it.kind() == Kind.PDF_CHUNK && it.sourceType() != SourceType.PDF_ORIGINAL) {
                v.add(f + ":pdf_chunk_requires_PDF_ORIGINAL");
            }
            if (it.sourceType() == SourceType.PDF_ORIGINAL && (it.chunkId() == null || it.page() == null)) {
                v.add(f + ":PDF_ORIGINAL_requires_chunkId_and_page");
            }
            if (it.kind() == Kind.CHAT_TURN && it.role() == null) {
                v.add(f + ":chat_turn_requires_role");
            }
            if (it.content() != null) {
                total += ContractJson.len(it.content());
            }
            if (it.id() != null && !ids.add(it.id())) {
                duplicate = true;
            }
        }
        v.check(total <= MAX_TOTAL_CHARS, "contextItems:total_chars");
        v.check(!duplicate, "contextItems:duplicate_id");
        if (c.usedSources() != null) {
            v.check(c.usedSources().size() <= MAX_CONTEXT_ITEMS, "usedSources:max_length");
            v.check(ids.containsAll(c.usedSources()), "usedSources:unknown_reference");
        }
        return v;
    }
}
