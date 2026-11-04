package com.studybridge.api.ai.quality;

import com.studybridge.api.ai.contract.v1.ResponseQualityV1;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 게이트 판정(사용자 노출 여부). approved 는 ResponseQualityV1.isDisplayable 결과만 반영한다.
 * reasonCodes 에는 위반 코드/평가기 오류 코드만 담는다(평가 사유 원문·답변 원문은 담지 않음).
 */
public record GateDecision(boolean approved, ResponseQualityV1.QualityStatus qualityStatus, Double score, String errorCode,
                           List<String> reasonCodes, String evaluatorVersion, String modelDigest, int attempts,
                           long latencyMs) {

    /** 사용자 실패 계약 코드. */
    public static final String REJECTED = "AI_QUALITY_REJECTED";
    public static final String UNAVAILABLE = "AI_QUALITY_UNAVAILABLE";
    public static final String NOT_WIRED = "AI_QUALITY_GATE_NOT_WIRED";

    public static GateDecision approved(ResponseQualityV1.Output o, int attempts, long latencyMs) {
        return new GateDecision(true, ResponseQualityV1.QualityStatus.APPROVED, o.score(), null, List.of(),
                o.evaluatorVersion(), o.modelDigest(), attempts, latencyMs);
    }

    public static GateDecision rejected(ResponseQualityV1.Output o, int attempts, long latencyMs) {
        List<String> codes = o.violations() == null ? List.of()
                : o.violations().stream().filter(v -> v != null && v.code() != null).map(ResponseQualityV1.Violation::code)
                .distinct().limit(10).toList();
        ResponseQualityV1.QualityStatus st = o.qualityStatus() == ResponseQualityV1.QualityStatus.VALIDATION_ERROR
                ? ResponseQualityV1.QualityStatus.VALIDATION_ERROR : ResponseQualityV1.QualityStatus.REJECTED;
        return new GateDecision(false, st, o.score(), st == ResponseQualityV1.QualityStatus.VALIDATION_ERROR ? UNAVAILABLE : REJECTED,
                codes, o.evaluatorVersion(), o.modelDigest(), attempts, latencyMs);
    }

    /** 평가 자체가 불가(타임아웃/503/429/서킷 오픈/계약 위반 응답) → 노출 금지. */
    public static GateDecision unavailable(String evaluatorErrorCode, int attempts, long latencyMs) {
        return new GateDecision(false, ResponseQualityV1.QualityStatus.VALIDATION_ERROR, null, UNAVAILABLE,
                List.of(evaluatorErrorCode), null, null, attempts, latencyMs);
    }

    /**
     * 같은 스트림에서 같은 에이전트의 같은 본문이 이미 승인됨 → 그 승인의 재사용(QualityStreamGate 전용, 새 평가 없음).
     * 호출자는 식별자·본문 필드가 정확히 일치함을 확인한 뒤에만 쓴다.
     */
    public static GateDecision reused() {
        return new GateDecision(true, ResponseQualityV1.QualityStatus.APPROVED, null, null, List.of("REUSED_SAME_STREAM_APPROVAL"), null,
                null, 0, 0);
    }

    /** 생성 단계 실패/빈 초안 등 평가할 본문이 없음. */
    public static GateDecision noDraft(String code, int attempts) {
        return new GateDecision(false, ResponseQualityV1.QualityStatus.REJECTED, null, REJECTED, List.of(code), null, null,
                attempts, 0);
    }

    /** 사용자 응답에 싣는 실패 계약(기존 DTO 의 success/errorCode/retryable 와 같은 어휘). */
    public Map<String, Object> failureBody(String requestId) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("success", false);
        m.put("qualityStatus", qualityStatus.name());
        m.put("verified", false);
        m.put("errorCode", errorCode);
        m.put("retryable", true);
        m.put("message", userMessage(errorCode));
        m.put("attempts", attempts);
        if (requestId != null) {
            m.put("requestId", requestId);
        }
        return m;
    }

    public static String userMessage(String errorCode) {
        if (UNAVAILABLE.equals(errorCode)) {
            return "지금은 AI 답변의 품질을 확인할 수 없어 답변을 표시하지 않았습니다. 잠시 후 다시 시도해 주세요.";
        }
        if (NOT_WIRED.equals(errorCode)) {
            return "이 기능은 AI 답변 품질 검증 연결 전이라 잠시 사용할 수 없습니다.";
        }
        return "AI가 만든 답변이 품질 기준을 통과하지 못해 표시하지 않았습니다. 다시 시도해 주세요.";
    }
}
