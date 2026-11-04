package com.studybridge.api.ai.contract.v1;

import com.fasterxml.jackson.databind.JsonNode;

import java.util.List;

/**
 * response-quality.v1 — 사용자 노출 AI 생성물의 품질 게이트 입력/출력(EC2 canonical).
 *
 * 승인(사용자 노출 허용)의 유일한 판정 함수는 {@link #isDisplayable(Output, String)} 이다:
 *   validate(output) 통과 && success && verified && qualityStatus==APPROVED && score!=null && 80<=score<=100
 *   && minimumScore ∈ {null, 80}(승인 기준은 항상 Spring 상수 80 — 평가기가 보낸 값으로 낮출 수 없다)
 *   && hardFail==false && HARD 위반 없음 && mandatoryValidatorsPassed!=false && requestId 일치
 * score 는 자체 rubric 점수이며 "정답일 확률 80%" 가 아니다(보정되지 않음).
 */
public final class ResponseQualityV1 {

    public static final String SCHEMA_VERSION = "response-quality.v1";
    public static final int MINIMUM_SCORE = 80;
    public static final int MAX_OUTPUT_CHARS = 60000;
    public static final int MAX_EVIDENCE_ITEMS = 32;
    public static final int MAX_EVIDENCE_CHARS = 8000;

    private ResponseQualityV1() {
    }

    public enum QualityStatus { PENDING, VALIDATING, APPROVED, REGENERATING, REJECTED, VALIDATION_ERROR }

    public enum TaskType {
        GENERAL_EXPLANATION, CREATIVE_EXPLORATION, STUDYMATE_BASIC, STUDYMATE_SOCRATIC, STUDYMATE_DEBATE,
        STUDYMATE_ROLEPLAY, PDF_SUMMARY, PDF_QA, PDF_QUIZ, WRONG_NOTE_EXPLANATION, SIMILAR_QUESTION, MATH_SOLUTION,
        PLANNER_COACHING, SEMANTIC_GRAPH, VISION_CAPTION, GROUP_STUDY_MESSAGE
    }

    public enum OutputKind {
        @com.fasterxml.jackson.annotation.JsonProperty("text") TEXT,
        @com.fasterxml.jackson.annotation.JsonProperty("quiz_json") QUIZ_JSON,
        @com.fasterxml.jackson.annotation.JsonProperty("graph_json") GRAPH_JSON,
        @com.fasterxml.jackson.annotation.JsonProperty("plan_json") PLAN_JSON,
        @com.fasterxml.jackson.annotation.JsonProperty("vision_text") VISION_TEXT,
        @com.fasterxml.jackson.annotation.JsonProperty("agent_message") AGENT_MESSAGE
    }

    public enum Severity { HARD, MAJOR, MINOR, INFO }

    public record GroundingEvidence(String evidenceId, String sourceType, Long materialId, String documentId,
                                    String sourceRevisionHash, Integer page, String chunkId, String text) { }

    public record Constraints(List<Long> allowedMaterialIds, List<String> allowedDocumentIds, Integer expectedQuestionCount,
                              Integer expectedOptionCount, String expectedAnswer, Integer maxChars, String finishReason,
                              Boolean requireCitations, Boolean allowPiiEcho, Double maxDailyHours, String deadline,
                              List<String> knownPrerequisites, List<String> participants, String expectedPersona,
                              String knowledgeLevel) {
        public static Constraints empty() {
            return new Constraints(null, null, null, null, null, null, null, null, null, null, null, null, null, null, null);
        }
    }

    public record Input(String schemaVersion, String requestId, TaskType taskType, OutputKind outputKind, String modelDigest,
                        String originalRequest, JsonNode proposedOutput, List<GroundingEvidence> groundingEvidence,
                        Constraints constraints, Integer attemptIndex, String evaluationProfile) { }

    public record Violation(String code, Severity severity, String reason, String evidenceId) { }

    public record Dimension(String name, Double score, Double maxScore, String method) { }

    /**
     * mandatoryValidatorsPassed: EC2 canonical v1 에서 추가한 선택 필드(ai07 출력 모델에 추가 요청, 인계 C-RQ-1).
     * 없으면(null) hardFail=false && HARD 위반 없음 으로 파생 판단한다. false 면 승인 불가.
     */
    public record Output(String schemaVersion, String requestId, TaskType taskType, Boolean success, Boolean verified,
                         QualityStatus qualityStatus, Double score, Integer minimumScore, Boolean hardFail,
                         List<Violation> violations, List<Dimension> dimensions, List<String> regenerationHints,
                         String evaluatorVersion, String modelDigest, Integer latencyMs, Boolean mandatoryValidatorsPassed) { }

    public static ContractJson.Violations validate(Input in) {
        ContractJson.Violations v = new ContractJson.Violations();
        if (in == null) {
            v.add("body:required");
            return v;
        }
        v.check(SCHEMA_VERSION.equals(in.schemaVersion()), "schemaVersion:unsupported");
        v.required(in.requestId(), "requestId");
        v.id(in.requestId(), ContractJson.ID_8_128, "requestId");
        v.required(in.taskType(), "taskType");
        v.required(in.outputKind(), "outputKind");
        v.maxLen(in.modelDigest(), 128, "modelDigest");
        v.required(in.originalRequest(), "originalRequest");
        v.maxLen(in.originalRequest(), 8000, "originalRequest");
        v.check(in.attemptIndex() == null || (in.attemptIndex() >= 0 && in.attemptIndex() <= 2), "attemptIndex:range");
        v.maxLen(in.evaluationProfile(), 64, "evaluationProfile");
        JsonNode po = in.proposedOutput();
        int size = po == null || po.isNull() ? 0 : po.isTextual() ? ContractJson.len(po.asText()) : ContractJson.len(po.toString());
        v.check(size <= MAX_OUTPUT_CHARS, "proposedOutput:too_large");
        List<GroundingEvidence> ev = in.groundingEvidence() == null ? List.of() : in.groundingEvidence();
        v.check(ev.size() <= MAX_EVIDENCE_ITEMS, "groundingEvidence:max_length");
        for (int i = 0; i < ev.size(); i++) {
            GroundingEvidence g = ev.get(i);
            String f = "groundingEvidence[" + i + "]";
            if (g == null) {
                v.add(f + ":required");
                continue;
            }
            v.required(g.sourceType(), f + ".sourceType");
            v.maxLen(g.sourceType(), 32, f + ".sourceType");
            v.check(g.materialId() == null || g.materialId() >= 1, f + ".materialId:ge_1");
            v.maxLen(g.sourceRevisionHash(), 128, f + ".sourceRevisionHash");
            v.check(g.page() == null || g.page() >= 1, f + ".page:ge_1");
            v.maxLen(g.text(), MAX_EVIDENCE_CHARS, f + ".text");
        }
        Constraints c = in.constraints();
        if (c != null) {
            v.check(c.expectedQuestionCount() == null || (c.expectedQuestionCount() >= 1 && c.expectedQuestionCount() <= 50),
                    "constraints.expectedQuestionCount:range");
            v.check(c.expectedOptionCount() == null || (c.expectedOptionCount() >= 2 && c.expectedOptionCount() <= 10),
                    "constraints.expectedOptionCount:range");
            v.maxLen(c.expectedAnswer(), 2000, "constraints.expectedAnswer");
            v.check(c.maxChars() == null || (c.maxChars() >= 1 && c.maxChars() <= MAX_OUTPUT_CHARS), "constraints.maxChars:range");
            v.maxLen(c.finishReason(), 32, "constraints.finishReason");
            v.check(c.maxDailyHours() == null || (c.maxDailyHours() > 0 && c.maxDailyHours() <= 24), "constraints.maxDailyHours:range");
            v.maxLen(c.deadline(), 32, "constraints.deadline");
            v.maxLen(c.expectedPersona(), 64, "constraints.expectedPersona");
            v.maxLen(c.knowledgeLevel(), 32, "constraints.knowledgeLevel");
        }
        return v;
    }

    /** 출력 구조/불변식 검증. APPROVED 인데 승인 규칙을 어기면 계약 위반(수신 즉시 거부). */
    public static ContractJson.Violations validate(Output o) {
        ContractJson.Violations v = new ContractJson.Violations();
        if (o == null) {
            v.add("body:required");
            return v;
        }
        v.check(SCHEMA_VERSION.equals(o.schemaVersion()), "schemaVersion:unsupported");
        v.required(o.requestId(), "requestId");
        v.required(o.taskType(), "taskType");
        v.required(o.success(), "success");
        v.required(o.verified(), "verified");
        v.required(o.qualityStatus(), "qualityStatus");
        v.required(o.hardFail(), "hardFail");
        v.required(o.evaluatorVersion(), "evaluatorVersion");
        v.check(o.minimumScore() == null || o.minimumScore() == MINIMUM_SCORE, "minimumScore:fixed_80");
        if (o.violations() != null) {
            for (int i = 0; i < o.violations().size(); i++) {
                Violation x = o.violations().get(i);
                if (x == null || x.code() == null || x.severity() == null || x.reason() == null) {
                    v.add("violations[" + i + "]:required");
                } else {
                    v.maxLen(x.reason(), 300, "violations[" + i + "].reason");
                }
            }
        }
        if (o.qualityStatus() == QualityStatus.APPROVED && !approvable(o)) {
            v.add("qualityStatus:APPROVED_violates_invariant");
        }
        return v;
    }

    private static boolean approvable(Output o) {
        Double s = o.score();
        boolean noHard = o.violations() == null || o.violations().stream()
                .noneMatch(x -> x != null && x.severity() == Severity.HARD);
        return Boolean.TRUE.equals(o.success()) && Boolean.TRUE.equals(o.verified())
                && s != null && !s.isNaN() && !s.isInfinite() && s >= MINIMUM_SCORE && s <= 100.0
                && (o.minimumScore() == null || o.minimumScore() == MINIMUM_SCORE)
                && Boolean.FALSE.equals(o.hardFail()) && noHard
                && !Boolean.FALSE.equals(o.mandatoryValidatorsPassed());
    }

    /**
     * 사용자 노출 가능 판정의 유일한 진입점. null/평가 실패/requestId 불일치/스키마 불일치는 모두 false(fail-closed).
     */
    public static boolean isDisplayable(Output o, String expectedRequestId) {
        // 수신 경로가 이미 validate 했더라도 여기서 다시 한다(계약 위반 출력은 어떤 경로로 들어와도 노출 불가).
        return o != null
                && validate(o).ok()
                && SCHEMA_VERSION.equals(o.schemaVersion())
                && expectedRequestId != null && expectedRequestId.equals(o.requestId())
                && o.qualityStatus() == QualityStatus.APPROVED
                && approvable(o);
    }
}
