package com.studybridge.api.ai.contract.v1;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.text.Normalizer;
import java.time.OffsetDateTime;
import java.util.EnumSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;

/**
 * training-sample.v1 — EC2 가 동의·권리 확인을 거쳐 ai07 수집 훅(/api/training-candidates/collect-v1)에 넘기는 학습 후보(EC2 canonical).
 *  · 사용자 노출 승인(품질 80점)과 학습 데이터 권한은 별개다. EC2 는 MODEL_TRAINING 동의가 있을 때만 이 샘플을 만든다.
 *  · ai07 은 trainingEligibility 주장을 그대로 믿지 않고 자체 자격 판정과 AND 한다(TRAIN_ELIGIBLE 는 ai07 검수 단계).
 *  · 서명된 본문으로만 보낸다(X-AI-Contract-Signature, AI_TRAINING_SAMPLE_SIGNING_KEY).
 */
public record TrainingSampleV1(
        String schemaVersion,
        String eventId,
        String pseudonymousUserKey,
        String consentVersion,
        OffsetDateTime consentTimestamp,
        SourceKind sourceKind,
        String sourceRevisionHash,
        RightsStatus rightsStatus,
        String question,
        String candidateAnswer,
        String verifiedAnswer,
        Verification verification,
        List<Evidence> evidence,
        Feedback feedback,
        QualityLabel qualityLabel,
        String qualityEvaluatorVersion,
        String modelName,
        String modelDigest,
        String promptTemplateVersion,
        String contentHash,
        OffsetDateTime createdAt,
        String deletionTrackingId,
        String retentionPolicy,
        Eligibility trainingEligibility) {

    public static final String SCHEMA_VERSION = "training-sample.v1";

    public enum SourceKind { PDF_QA, PDF_SUMMARY, PDF_QUIZ, GENERAL_QA, MATH, CODE, WRONG_NOTE, FREE_RESPONSE }

    public enum RightsStatus {
        USER_OWNED_VERIFIED, LICENSED_VERIFIED, PUBLIC_DOMAIN_VERIFIED, NO_THIRD_PARTY_CONTENT, THIRD_PARTY_UNVERIFIED, UNKNOWN
    }

    public static final Set<RightsStatus> RIGHTS_OK = EnumSet.of(RightsStatus.USER_OWNED_VERIFIED, RightsStatus.LICENSED_VERIFIED,
            RightsStatus.PUBLIC_DOMAIN_VERIFIED, RightsStatus.NO_THIRD_PARTY_CONTENT);

    public enum QualityLabel { UNLABELED, REVIEWER_VERIFIED, DETERMINISTIC_GOLD, UNVERIFIABLE, INCORRECT }

    public enum VerificationMethod { HUMAN_REVIEW, MATH_CHECK, CODE_TESTS, EXACT_MATCH_GOLD, PDF_SPAN_MATCH, LLM_JUDGE, NONE }

    public record Evidence(String sourceType, Long materialId, String documentId, String sourceRevisionHash, Integer page,
                           String chunkId, String quote) { }

    public record Feedback(Integer score, String reasonCode, OffsetDateTime updatedAt, List<Integer> history) { }

    public record Eligibility(Boolean consentGranted, List<String> consentScope, Boolean consentWithdrawn,
                              OffsetDateTime decidedAt) { }

    public record Verification(VerificationMethod method, String reviewerId, OffsetDateTime verifiedAt, String goldReference) { }

    public static ContractJson.Violations validate(TrainingSampleV1 s) {
        ContractJson.Violations v = new ContractJson.Violations();
        if (s == null) {
            v.add("body:required");
            return v;
        }
        v.check(SCHEMA_VERSION.equals(s.schemaVersion()), "schemaVersion:unsupported");
        v.required(s.eventId(), "eventId");
        v.id(s.eventId(), ContractJson.ID_8_128, "eventId");
        v.check(ContractJson.pseudonymous(s.pseudonymousUserKey()), "pseudonymousUserKey:pseudonymous");
        v.maxLen(s.consentVersion(), 32, "consentVersion");
        v.required(s.sourceKind(), "sourceKind");
        v.maxLen(s.sourceRevisionHash(), 128, "sourceRevisionHash");
        v.required(s.rightsStatus(), "rightsStatus");
        v.required(s.question(), "question");
        v.check(s.question() == null || ContractJson.len(s.question()) >= 1, "question:min_length");
        v.maxLen(s.question(), 4000, "question");
        v.required(s.candidateAnswer(), "candidateAnswer");
        v.check(s.candidateAnswer() == null || ContractJson.len(s.candidateAnswer()) >= 1, "candidateAnswer:min_length");
        v.maxLen(s.candidateAnswer(), 12000, "candidateAnswer");
        v.maxLen(s.verifiedAnswer(), 12000, "verifiedAnswer");
        // 생성 경로(파싱을 거치지 않음)에도 같은 경계: 고립 서러게이트(C-JSON-2)·연도 범위(C-TIME-2).
        v.check(!ContractJson.hasLoneSurrogate(s.question()) && !ContractJson.hasLoneSurrogate(s.candidateAnswer())
                && !ContractJson.hasLoneSurrogate(s.verifiedAnswer()), "text:lone_surrogate");
        v.check(ContractJson.yearInRange(s.consentTimestamp()) && ContractJson.yearInRange(s.createdAt()), "datetime:year_range");
        if (s.verification() != null) {
            v.required(s.verification().method(), "verification.method");
            v.maxLen(s.verification().reviewerId(), 64, "verification.reviewerId");
            v.maxLen(s.verification().goldReference(), 256, "verification.goldReference");
        }
        List<Evidence> ev = s.evidence() == null ? List.of() : s.evidence();
        v.check(ev.size() <= 16, "evidence:max_length");
        for (int i = 0; i < ev.size(); i++) {
            Evidence e = ev.get(i);
            String f = "evidence[" + i + "]";
            if (e == null) {
                v.add(f + ":required");
                continue;
            }
            v.required(e.sourceType(), f + ".sourceType");
            v.maxLen(e.sourceType(), 32, f + ".sourceType");
            v.check(e.materialId() == null || e.materialId() >= 1, f + ".materialId:ge_1");
            v.maxLen(e.documentId(), 128, f + ".documentId");
            v.maxLen(e.sourceRevisionHash(), 128, f + ".sourceRevisionHash");
            v.check(e.page() == null || e.page() >= 1, f + ".page:ge_1");
            v.maxLen(e.chunkId(), 128, f + ".chunkId");
            v.maxLen(e.quote(), 4000, f + ".quote");
        }
        if (s.feedback() != null) {
            Feedback fb = s.feedback();
            v.check(fb.score() != null && fb.score() >= -1 && fb.score() <= 1, "feedback.score:range");
            v.maxLen(fb.reasonCode(), 64, "feedback.reasonCode");
            v.required(fb.updatedAt(), "feedback.updatedAt");
            v.check(fb.history() == null || fb.history().size() <= 64, "feedback.history:max_length");
        }
        v.maxLen(s.qualityEvaluatorVersion(), 64, "qualityEvaluatorVersion");
        v.required(s.modelName(), "modelName");
        v.maxLen(s.modelName(), 64, "modelName");
        v.maxLen(s.modelDigest(), 128, "modelDigest");
        v.maxLen(s.promptTemplateVersion(), 64, "promptTemplateVersion");
        v.required(s.createdAt(), "createdAt");
        v.required(s.deletionTrackingId(), "deletionTrackingId");
        v.id(s.deletionTrackingId(), ContractJson.ID_8_128, "deletionTrackingId");
        v.required(s.retentionPolicy(), "retentionPolicy");
        v.maxLen(s.retentionPolicy(), 64, "retentionPolicy");
        Eligibility el = s.trainingEligibility();
        v.required(el, "trainingEligibility");
        if (el != null) {
            v.required(el.consentGranted(), "trainingEligibility.consentGranted");
            v.check(el.consentScope() == null || el.consentScope().size() <= 8, "trainingEligibility.consentScope:max_length");
            v.required(el.decidedAt(), "trainingEligibility.decidedAt");
        }
        String h = s.contentHash();
        if (h == null || !ContractJson.HEX64.matcher(h).matches()) {
            v.add("contentHash:lower_sha256_hex");
        } else if (s.question() != null && s.candidateAnswer() != null
                && !h.equals(contentHash(s.question(), s.candidateAnswer()))) {
            v.add("contentHash:mismatch");
        }
        return v;
    }

    /** EC2/ai07 공통 해시: NFKC + Python str 공백 규칙(\s+ → ' ', strip) 후 question + "\n" + answer 의 SHA-256(소문자 hex). */
    public static String contentHash(String question, String answer) {
        String joined = normalizeForHash(question) + "\n" + normalizeForHash(answer);
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(joined.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    public static String normalizeForHash(String text) {
        String t = Normalizer.normalize(text == null ? "" : text, Normalizer.Form.NFKC);
        StringBuilder sb = new StringBuilder(t.length());
        boolean inSpace = false;
        for (int i = 0; i < t.length(); ) {
            int cp = t.codePointAt(i);
            i += Character.charCount(cp);
            if (isPythonSpace(cp)) {
                inSpace = true;
            } else {
                if (inSpace && sb.length() > 0) {
                    sb.append(' ');
                }
                inSpace = false;
                sb.appendCodePoint(cp);
            }
        }
        return sb.toString();
    }

    /**
     * Python str.isspace()/re '\s'(유니코드) 와 같은 집합: 양방향 유형 WS/B/S 또는 일반 범주 Zs.
     * Java Character.isWhitespace 는 NBSP 계열을 빼고 \x1c-\x1f 를 넣는 등 달라서 직접 열거한다.
     */
    static boolean isPythonSpace(int cp) {
        if (cp >= 0x09 && cp <= 0x0d) {
            return true;
        }
        if (cp >= 0x1c && cp <= 0x20) {
            return true;
        }
        if (cp == 0x85 || cp == 0xa0 || cp == 0x1680 || cp == 0x2028 || cp == 0x2029 || cp == 0x202f || cp == 0x205f
                || cp == 0x3000) {
            return true;
        }
        return cp >= 0x2000 && cp <= 0x200a;
    }
}
