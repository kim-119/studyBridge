package com.studybridge.api.controller;

import com.studybridge.api.dto.PlanAnalysisDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.PlanAnalysisException;
import com.studybridge.api.service.PlanAnalysisService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

/**
 * AI 계획 분석 / 다음 학습 추천 / 진행률 API.
 * 메모는 기존 MaterialController(/api/materials/{id}/memo)를 재사용한다.
 */
@Slf4j
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class PlanAnalysisController {

    private final PlanAnalysisService planAnalysisService;

    /** 분석 생성/재생성. */
    @PostMapping("/materials/{materialId}/plan-analysis")
    public ResponseEntity<PlanAnalysisDTO.Response> analyze(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        try {
            return ResponseEntity.ok(planAnalysisService.analyze(userDetails.getId(), materialId));
        } catch (PlanAnalysisException e) {
            log.warn("[plan-analysis] materialId={} errorCode={} msg={}", materialId, e.getErrorCode(), e.getMessage());
            return ResponseEntity.status(statusFor(e.getErrorCode()))
                    .body(PlanAnalysisDTO.Response.builder()
                            .materialId(materialId).empty(true).errorCode(e.getErrorCode())
                            .summary(e.getMessage()).build());
        } catch (Exception e) {
            log.error("[plan-analysis] materialId={} UNEXPECTED", materialId, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(PlanAnalysisDTO.Response.builder()
                            .materialId(materialId).empty(true).errorCode("PLAN_ANALYSIS_SAVE_FAILED")
                            .summary("AI 계획 분석에 실패했습니다. 다시 시도해 주세요.").build());
        }
    }

    /** 저장된 분석 조회. */
    @GetMapping("/materials/{materialId}/plan-analysis")
    public ResponseEntity<PlanAnalysisDTO.Response> get(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(planAnalysisService.get(userDetails.getId(), materialId));
    }

    /** 항목 완료/숨김 상태 변경 (체크 또는 지우기). */
    @PatchMapping("/plan-analysis/items/{itemId}")
    public ResponseEntity<PlanAnalysisDTO.Response> patchItem(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long itemId,
            @RequestBody PlanAnalysisDTO.ItemPatchRequest req) {
        return ResponseEntity.ok(planAnalysisService.updateItem(
                userDetails.getId(), itemId, req.getCompleted(), req.getHidden()));
    }

    /** 다음 학습 추천(미완료 항목 기반) 재생성. */
    @PostMapping("/materials/{materialId}/plan-recommendation")
    public ResponseEntity<PlanAnalysisDTO.RecommendationResponse> recommend(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        try {
            return ResponseEntity.ok(planAnalysisService.recommend(userDetails.getId(), materialId));
        } catch (PlanAnalysisException e) {
            return ResponseEntity.status(statusFor(e.getErrorCode()))
                    .body(PlanAnalysisDTO.RecommendationResponse.builder()
                            .recommendations(java.util.List.of()).errorCode(e.getErrorCode()).build());
        }
    }

    /** 진행률 조회. */
    @GetMapping("/materials/{materialId}/progress")
    public ResponseEntity<PlanAnalysisDTO.Progress> progress(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(planAnalysisService.get(userDetails.getId(), materialId).getProgress());
    }

    private HttpStatus statusFor(String errorCode) {
        if ("PLAN_ANALYSIS_TEXT_EMPTY".equals(errorCode) || "PLAN_ANALYSIS_CONTRACT_VIOLATION".equals(errorCode)) {
            return HttpStatus.UNPROCESSABLE_ENTITY;
        }
        return HttpStatus.INTERNAL_SERVER_ERROR;
    }
}
