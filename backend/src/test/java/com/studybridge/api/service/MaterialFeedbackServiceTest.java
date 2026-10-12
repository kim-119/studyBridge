package com.studybridge.api.service;

import com.studybridge.api.dto.FeedbackDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialFeedback;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.service.support.FailoverStubServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;

import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.*;

/**
 * P0 "피드백 재생성 중 오류가 발생했습니다" 회귀 테스트.
 * 실제 TCP 스텁(AI07 대역)으로 WebClient 경로를 그대로 태운다.
 */
class MaterialFeedbackServiceTest {

    private static final long USER = 8L;
    private static final long MATERIAL = 303L;

    private FailoverStubServer ai;
    private MaterialRepository materials;
    private MaterialFeedbackRepository feedbacks;
    private AiRequestGuard guard;
    private MaterialFeedbackService service;
    private Material material;
    private MaterialFeedback existing;

    @BeforeEach
    void setUp() throws Exception {
        ai = new FailoverStubServer("/api/ai/feedback");
        materials = mock(MaterialRepository.class);
        feedbacks = mock(MaterialFeedbackRepository.class);
        guard = mock(AiRequestGuard.class);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));

        material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.STUDY_LOG)
                .title("ViewModel 학습일지").learningContent("ViewModel 은 Activity 간에 자동으로 유지된다.").build();
        existing = MaterialFeedback.builder().feedbackId(11L).material(material).feedbackData("기존 피드백").build();
        when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
        when(feedbacks.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.of(existing));
        when(feedbacks.saveAndFlush(any(MaterialFeedback.class))).thenAnswer(inv -> inv.getArgument(0));

        service = new MaterialFeedbackService(materials, feedbacks, ai.client(5), guard,
                mock(PlatformTransactionManager.class), 5, false);
    }

    @AfterEach
    void tearDown() {
        ai.close();
    }

    @Test
    void regenerate_updatesSameRow_insteadOfDeleteInsert() {
        ai.body = "{\"success\":true,\"feedbackData\":\"새 피드백\",\"metadata\":{\"provider\":\"ollama\",\"model\":\"qwen\"}}";

        FeedbackDTO dto = service.regenerate(USER, MATERIAL);

        assertEquals(11L, dto.getFeedbackId(), "같은 행(id 유지)을 갱신해야 한다");
        assertEquals("새 피드백", dto.getFeedbackData());
        assertEquals("새 피드백", existing.getFeedbackData());
        assertNotNull(dto.getRequestId());
        assertEquals("ollama", dto.getProvider());
        verify(feedbacks, never()).delete(any());
        verify(feedbacks, never()).deleteById(any());
        verify(guard).release(any());
        assertTrue(ai.requestBodies.get(0).contains("\"request_id\""));
    }

    @Test
    void aiSuccessFalse_keepsExistingFeedback_andReturnsRetryableCode() {
        ai.body = "{\"success\":false,\"errorCode\":\"UNKNOWN_ERROR\",\"message\":\"x\",\"retryable\":true}";

        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));

        assertEquals("AI_GENERATION_FAILED", e.getCode());
        assertTrue(e.isRetryable());
        assertEquals("UNKNOWN_ERROR", e.getUpstreamCode());
        assertEquals("기존 피드백", existing.getFeedbackData());
        verify(feedbacks, never()).saveAndFlush(any());
        verify(guard).release(any());
    }

    @Test
    void aiTimeoutCode_mapsTo504() {
        ai.body = "{\"success\":false,\"errorCode\":\"AI_TIMEOUT\",\"retryable\":true}";
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, e.getStatus());
        assertEquals("AI_TIMEOUT", e.getCode());
        verify(feedbacks, never()).saveAndFlush(any());
    }

    @Test
    void upstream500_isUnavailable_andNothingSaved() {
        ai.status = 500;
        ai.body = "{\"detail\":\"boom\"}";
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, e.getStatus());
        assertEquals("AI_UPSTREAM_UNAVAILABLE", e.getCode());
        verify(feedbacks, never()).saveAndFlush(any());
    }

    @Test
    void upstream422_isContractError_notRetryable() {
        ai.status = 422;
        ai.body = "{\"detail\":[]}";
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, e.getStatus());
        assertFalse(e.isRetryable());
    }

    @Test
    void emptyFeedbackBody_isInvalid_notStoredAsFailureText() {
        ai.body = "{\"success\":true,\"feedbackData\":\"   \"}";
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals("AI_RESPONSE_INVALID", e.getCode());
        assertEquals("기존 피드백", existing.getFeedbackData(), "예전처럼 '피드백 생성 실패' 문자열로 덮어쓰면 안 된다");
        verify(feedbacks, never()).saveAndFlush(any());
    }

    @Test
    void readTimeout_mapsToAiTimeout() {
        ai.delayMs = 7000; // client response timeout 5s
        ai.body = "{\"success\":true,\"feedbackData\":\"늦은 응답\"}";
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertTrue(e.isRetryable());
        assertEquals("기존 피드백", existing.getFeedbackData());
    }

    @Test
    void inFlightLock_returns409_withoutCallingAi() {
        when(guard.tryLock(anyString(), any())).thenReturn(new AiRequestGuard.Lock("k", "t", false));
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals(HttpStatus.CONFLICT, e.getStatus());
        assertEquals("FEEDBACK_GENERATION_IN_PROGRESS", e.getCode());
        assertEquals(0, ai.hits.get());
    }

    @Test
    void otherUsersMaterial_isForbidden_beforeAnyAiCall() {
        assertThrows(SecurityException.class, () -> service.regenerate(99L, MATERIAL));
        assertEquals(0, ai.hits.get());
        verify(guard, never()).tryLock(anyString(), any());
    }

    @Test
    void lockKey_isUserScoped() {
        assertNotEquals(AiRequestGuard.lockKey("feedback", 1L, MATERIAL), AiRequestGuard.lockKey("feedback", 2L, MATERIAL));
    }

    @Test
    void conceptReviewResponse_isStoredAsJson_withoutTransportFields() {
        ai.body = "{\"success\":true,\"retryable\":false,\"textStatus\":{},\"warnings\":[],"
                + "\"misconceptions\":[{\"claim\":\"ViewModel 은 Activity 간 자동 유지\",\"correction\":\"ViewModelStoreOwner 범위\"}],"
                + "\"verificationPractice\":[\"회전 후 값 유지 확인\"]}";

        FeedbackDTO dto = service.regenerate(USER, MATERIAL);

        assertTrue(dto.getFeedbackData().contains("misconceptions"));
        assertFalse(dto.getFeedbackData().contains("\"success\""));
        assertFalse(dto.getFeedbackData().contains("textStatus"));
    }

    @Test
    void firstGeneration_concurrentInsert_fallsBackToUpdate() {
        when(feedbacks.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.empty(), Optional.empty(), Optional.of(existing));
        AtomicInteger calls = new AtomicInteger();
        when(feedbacks.saveAndFlush(any(MaterialFeedback.class))).thenAnswer(inv -> {
            if (calls.getAndIncrement() == 0) throw new DataIntegrityViolationException("uk material_id");
            return inv.getArgument(0);
        });
        ai.body = "{\"success\":true,\"feedback\":\"첫 피드백\"}";

        FeedbackDTO dto = service.get(USER, MATERIAL);

        assertEquals(11L, dto.getFeedbackId());
        assertEquals("첫 피드백", existing.getFeedbackData());
    }

    @Test
    void emptySource_isRejectedWithoutAiCall() {
        material.setLearningContent(" ");
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.regenerate(USER, MATERIAL));
        assertEquals("FEEDBACK_SOURCE_EMPTY", e.getCode());
        assertEquals(0, ai.hits.get());
    }
}
