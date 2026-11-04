package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.LearningMateDTO;
import com.studybridge.api.service.support.ChatGateStubServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 학습메이트 질문 중심 경로(POST /api/learning-mate/chat) 품질 게이트(Phase D):
 *  79 거절 → 재생성 → 80 승인만 노출, 3회 거절·hardFail·평가기 503 은 명시적 실패(본문 0), 첫 생성 실패는 기존 계약, 게이트 OFF 회귀 없음.
 *  이 경로는 DB/Redis 에 저장하지 않는다(응답만).
 */
class LearningMateQualityGateTest {

    static final ObjectMapper M = new ObjectMapper();
    ChatGateStubServer stub;
    volatile boolean generationFails;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
        stub.json("/api/ai/multi-chat", n -> generationFails ? null
                : "{\"status\":\"COMPLETED\",\"answers\":[{\"agentName\":\"돌리\",\"answer\":\"CANARYL 초안 " + n
                        + ": 재귀는 자기 자신을 다시 호출하는 함수입니다.\"}]}");
    }

    @AfterEach
    void down() {
        stub.close();
    }

    LearningMateService service(boolean gateOn) {
        LearningMateService s = new LearningMateService(stub.client(), M);
        ReflectionTestUtils.setField(s, "aiTimeoutSeconds", 10L);
        s.setQualityGate(stub.gate(gateOn));
        return s;
    }

    static LearningMateDTO.Request req(String mode) {
        LearningMateDTO.Request r = new LearningMateDTO.Request();
        r.setQuestion("재귀 함수가 뭐야?");
        r.setMode(mode);
        return r;
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/learning-mate/chat"})
    @Test
    void rejected79ThenApproved80ShowsOnlyRegeneratedDraft() throws Exception {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        LearningMateDTO.Response r = service(true).chat(req("explain"));
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals("APPROVED", r.getQualityStatus());
        assertEquals(80.0, r.getQualityScore());
        assertTrue(r.getAnswer().contains("초안 2"), "재생성된 두 번째 초안만 노출");
        assertFalse(r.getAnswer().contains("초안 1"));
        assertEquals(2, stub.calls("/api/ai/multi-chat"));
        assertEquals(Boolean.TRUE, stub.generationBodies.get(1).get("forceRegenerate").asBoolean(), "재생성은 캐시 우회");
        assertTrue(stub.generationBodies.get(1).get("requestId").asText().endsWith("-r1"));
        assertEquals("STUDYMATE_BASIC", stub.evaluations.get(0).get("taskType").asText());
        assertEquals("agent_message", stub.evaluations.get(0).get("outputKind").asText());
        assertTrue(ChatGateStubServer.proposedText(stub.evaluations.get(0)).contains("초안 1"), "화면에 보일 평탄화 답변 전체를 평가");
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/learning-mate/chat"})
    @Test
    void threeRejectionsAreExplicitFailureWithoutDraft() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        LearningMateDTO.Response r = service(true).chat(req("socratic"));
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
        assertEquals(Boolean.TRUE, r.getRetryable());
        assertEquals("REJECTED", r.getQualityStatus());
        assertNull(r.getAnswer());
        assertFalse(M.writeValueAsString(r).contains("CANARYL"), "거절 초안 미노출");
        assertEquals(3, stub.calls("/api/ai/multi-chat"), "최초 1 + 재생성 2");
        assertEquals("STUDYMATE_SOCRATIC", stub.evaluations.get(0).get("taskType").asText());
    }

    @Test
    void hardFailIsRejectedAndEvaluatorDownIsUnavailable() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(95, "REJECTED", true);
        LearningMateDTO.Response hard = service(true).chat(req("debate"));
        assertEquals("AI_QUALITY_REJECTED", hard.getErrorCode());
        assertNull(hard.getAnswer());

        stub.policy = (n, in) -> null;
        int before = stub.calls("/api/ai/multi-chat");
        LearningMateDTO.Response down = service(true).chat(req("explain"));
        assertEquals("AI_QUALITY_UNAVAILABLE", down.getErrorCode());
        assertEquals("VALIDATION_ERROR", down.getQualityStatus());
        assertNull(down.getAnswer());
        assertEquals(before + 1, stub.calls("/api/ai/multi-chat"), "평가기 장애 시 재생성하지 않는다");
    }

    @Test
    void firstGenerationFailureKeepsLegacyContract() {
        generationFails = true;
        LearningMateDTO.Response r = service(true).chat(req("explain"));
        assertEquals("AI_ERROR", r.getErrorCode());
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals(0, stub.evaluations.size(), "생성 실패면 평가하지 않는다");
        assertEquals(1, stub.calls("/api/ai/multi-chat"));
    }

    @Test
    void gateOffIsLegacyBehaviour() throws Exception {
        LearningMateDTO.Response r = service(false).chat(req("explain"));
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertTrue(r.getAnswer().contains("CANARYL 초안 1"));
        assertNull(r.getQualityStatus());
        assertEquals(0, stub.evaluations.size());
        String body = M.writeValueAsString(r);
        assertFalse(body.contains("qualityStatus") || body.contains("verified") || body.contains("retryable"), "게이트 OFF 응답 형태 불변");
    }
}
