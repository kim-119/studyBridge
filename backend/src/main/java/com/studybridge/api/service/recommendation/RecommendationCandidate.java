package com.studybridge.api.service.recommendation;

import java.util.List;
import java.util.Map;

/**
 * 저장 전 추천 후보. 규칙(RULE) 또는 AI07 후보(EC2 검증 통과분, AI)가 같은 형태로 합쳐진다.
 *
 * @param targetKey 중복 판정 키의 일부(예: ch3, p1234, kw:행렬). 같은 출처·유형·targetKey 는 같은 후보로 본다.
 */
public record RecommendationCandidate(
        String type,
        String title,
        String reason,
        String targetKey,
        List<Evidence> evidence,
        boolean verificationRequired,
        String verificationNote,
        Map<String, Object> score,
        String generator,
        String modelProvider,
        String modelName) {

    /** 근거 데이터 1건. type 예: PLANNER, PLAN_ANALYSIS, MATERIAL, TOC, QUIZ, REVIEW_NOTE, STUDY_NOTE, ROADMAP_NODE, SCHEDULE. */
    public record Evidence(String type, String id, String label) {}

    public static final String RULE = "RULE";
    public static final String AI = "AI";

    // 유형 — 사용자 플래너(Learning Task)
    public static final String NEXT_CHAPTER = "NEXT_CHAPTER";
    public static final String CONCEPT_REVIEW = "CONCEPT_REVIEW";
    public static final String PRACTICE = "PRACTICE";
    public static final String PREREQUISITE_GAP = "PREREQUISITE_GAP";
    public static final String APPLICATION = "APPLICATION";
    public static final String WRONG_ANSWER_REVIEW = "WRONG_ANSWER_REVIEW";
    // 로드맵(Learning Node)
    public static final String ROADMAP_NODE = "ROADMAP_NODE";
    // 문서 기반(Document-based)
    public static final String DOCUMENT_CONCEPT_REVIEW = "DOCUMENT_CONCEPT_REVIEW";
    public static final String DOCUMENT_PRACTICE = "DOCUMENT_PRACTICE";
    public static final String DOCUMENT_DEEP_DIVE = "DOCUMENT_DEEP_DIVE";
    public static final String DOCUMENT_REVIEW = "DOCUMENT_REVIEW";

    public static final List<String> TASK_TYPES = List.of(NEXT_CHAPTER, CONCEPT_REVIEW, PRACTICE, PREREQUISITE_GAP, APPLICATION, WRONG_ANSWER_REVIEW);
    public static final List<String> DOCUMENT_TYPES = List.of(DOCUMENT_CONCEPT_REVIEW, DOCUMENT_PRACTICE, DOCUMENT_DEEP_DIVE, DOCUMENT_REVIEW, WRONG_ANSWER_REVIEW);

    public static RecommendationCandidate rule(String type, String title, String reason, String targetKey,
                                               List<Evidence> evidence, boolean verificationRequired, String verificationNote) {
        return new RecommendationCandidate(type, title, reason, targetKey, evidence, verificationRequired, verificationNote,
                null, RULE, null, null);
    }

    public RecommendationCandidate withScore(Map<String, Object> s) {
        return new RecommendationCandidate(type, title, reason, targetKey, evidence, verificationRequired, verificationNote,
                s, generator, modelProvider, modelName);
    }
}
