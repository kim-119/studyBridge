package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.GroundingEvidence;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.exception.AiUpstreamException;
import org.springframework.http.HttpStatus;

import java.util.ArrayList;
import java.util.List;

/**
 * 플래너·마인드맵·추천 영역(Phase D planner) 품질 게이트 공용 도우미. 공용 게이트 클래스는 바꾸지 않고 이 영역에서만 쓴다.
 *
 *  · visibleText: 사용자에게 보일 문자열 잎을 모두 모은다(키 이름 제외, 숫자·불리언 포함 — 시간·분도 화면에 보인다).
 *  · evidence: Spring 이 가진 원문(플래너 입력·채팅 답변 등)을 평가 근거로 자른다. materialId 는 넣지 않는다
 *    (자료 범위 검사는 PDF 경로 몫 — 넣으면 allowedMaterialIds 가 필요하다).
 *  · failure: 거절 = 422 AI_QUALITY_REJECTED, 평가 불가 = 503 AI_QUALITY_UNAVAILABLE(retryable). 성공 위장 없음.
 */
public final class PlannerQualityGateSupport {

    /** quality_status 컬럼에 기록하는 유일한 값. 게이트 OFF 저장은 null(나중에 게이트를 켜면 미검증으로 취급). */
    public static final String APPROVED = "APPROVED";
    /** 가림 표식과 같이 내려주는 고정 문구. */
    public static final String REDACTED_MESSAGE = "품질 검증 전에 저장된 AI 결과라 표시하지 않습니다. 다시 생성해 주세요.";

    private PlannerQualityGateSupport() {
    }

    public static boolean approved(String qualityStatus) {
        return APPROVED.equals(qualityStatus);
    }

    /** 사용자에게 보일 모든 문자열(구조화 JSON 의 모든 잎 — 키 이름 제외). */
    public static String visibleText(JsonNode n) {
        StringBuilder b = new StringBuilder();
        collect(n, b);
        return b.toString().trim();
    }

    private static void collect(JsonNode n, StringBuilder b) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            return;
        }
        if (n.isTextual()) {
            if (!n.asText().isBlank()) {
                b.append(n.asText().trim()).append('\n');
            }
        } else if (n.isContainerNode()) {
            n.elements().forEachRemaining(x -> collect(x, b));
        } else if (n.isNumber() || n.isBoolean()) {
            b.append(n.asText()).append('\n');
        }
    }

    /** 원문을 평가 근거로 자른다(항목 ≤ 8000자, 최대 32개, 총량 maxTotalChars). 빈 원문이면 빈 목록. */
    public static List<GroundingEvidence> evidence(String sourceType, String idPrefix, String text, int chunkChars, int maxTotalChars) {
        List<GroundingEvidence> out = new ArrayList<>();
        appendEvidence(out, sourceType, idPrefix, text, chunkChars, maxTotalChars);
        return out;
    }

    /** out 에 이어 붙인다(이미 들어 있는 근거 총량을 포함해 maxTotalChars 이하). */
    public static void appendEvidence(List<GroundingEvidence> out, String sourceType, String idPrefix, String text,
                                      int chunkChars, int maxTotalChars) {
        if (text == null || text.isBlank()) {
            return;
        }
        int chunk = Math.max(200, Math.min(chunkChars, ResponseQualityV1.MAX_EVIDENCE_CHARS));
        int total = 0;
        for (GroundingEvidence g : out) {
            total += g.text() == null ? 0 : g.text().length();
        }
        String t = text.trim();
        for (int i = 0, n = 0; i < t.length() && out.size() < ResponseQualityV1.MAX_EVIDENCE_ITEMS && total < maxTotalChars; n++) {
            int end = Math.min(t.length(), i + Math.min(chunk, maxTotalChars - total));
            String piece = t.substring(i, end);
            out.add(new GroundingEvidence(null, sourceType, null, null, null, null, idPrefix + "-c" + n, piece));
            total += piece.length();
            i = end;
        }
    }

    /** 게이트 미승인 → 사용자 실패 계약(전역 예외 처리기가 {status, code, message, retryable} JSON 으로 내린다). */
    public static AiUpstreamException failure(GateDecision d, String requestId, String suffix) {
        String code = d == null || d.errorCode() == null ? GateDecision.REJECTED : d.errorCode();
        boolean rejected = GateDecision.REJECTED.equals(code);
        String msg = GateDecision.userMessage(code) + (suffix == null || suffix.isBlank() ? "" : " " + suffix);
        return new AiUpstreamException(rejected ? HttpStatus.UNPROCESSABLE_ENTITY : HttpStatus.SERVICE_UNAVAILABLE,
                rejected ? GateDecision.REJECTED : GateDecision.UNAVAILABLE, msg, requestId, true, null, null);
    }

    public static String clip(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }
}
