package com.studybridge.api.controller;

import com.studybridge.api.dto.LearningRecommendationDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.recommendation.LearningRecommendationService;
import com.studybridge.api.service.recommendation.PlanDiagnosisService;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;

/**
 * 학습 추천(Learning Task / Learning Node / Document-based) + 계획 진단(Optimization Strategy).
 * 모든 경로는 인증 사용자 본인 데이터만 다룬다(서비스에서 userId 소유권 검증).
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
public class LearningRecommendationController {

    private final LearningRecommendationService recommendationService;
    private final PlanDiagnosisService diagnosisService;

    @GetMapping("/planners/{plannerId}/recommendations")
    public ResponseEntity<LearningRecommendationDTO.ListResponse> listForPlanner(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long plannerId) {
        return ResponseEntity.ok(recommendationService.listForPlanner(user.getId(), plannerId));
    }

    @PostMapping("/planners/{plannerId}/recommendations")
    public ResponseEntity<LearningRecommendationDTO.ListResponse> generateForPlanner(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long plannerId) {
        return ResponseEntity.ok(recommendationService.generateForPlanner(user.getId(), plannerId));
    }

    @GetMapping("/materials/{materialId}/recommendations")
    public ResponseEntity<LearningRecommendationDTO.ListResponse> listForMaterial(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long materialId) {
        return ResponseEntity.ok(recommendationService.listForMaterial(user.getId(), materialId));
    }

    @PostMapping("/materials/{materialId}/recommendations")
    public ResponseEntity<LearningRecommendationDTO.ListResponse> generateForMaterial(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long materialId) {
        return ResponseEntity.ok(recommendationService.generateForMaterial(user.getId(), materialId));
    }

    @PostMapping("/recommendations/{id}/accept")
    public ResponseEntity<LearningRecommendationDTO.Item> accept(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long id,
            @RequestBody(required = false) LearningRecommendationDTO.AcceptRequest req) {
        return ResponseEntity.ok(recommendationService.accept(user.getId(), id, req));
    }

    @PostMapping("/recommendations/{id}/reject")
    public ResponseEntity<LearningRecommendationDTO.Item> reject(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long id) {
        return ResponseEntity.ok(recommendationService.reject(user.getId(), id));
    }

    @PostMapping("/recommendations/{id}/complete")
    public ResponseEntity<LearningRecommendationDTO.Item> complete(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long id) {
        return ResponseEntity.ok(recommendationService.complete(user.getId(), id));
    }

    @GetMapping("/recommendations/metrics")
    public ResponseEntity<LearningRecommendationDTO.Metrics> metrics(@AuthenticationPrincipal CustomUserDetails user) {
        return ResponseEntity.ok(recommendationService.metrics(user.getId()));
    }

    /** 계획 진단: A(가용) / W(작업량) / D(부족량) + 마감 창·과부하·선수관계·일정 중복. dailyAvailableMinutes 없으면 A·D 미계산. */
    @GetMapping("/planners/{plannerId}/diagnosis")
    public ResponseEntity<PlanDiagnosisService.Response> diagnosis(
            @AuthenticationPrincipal CustomUserDetails user, @PathVariable Long plannerId,
            @RequestParam(required = false) Integer dailyAvailableMinutes,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate deadline) {
        if (dailyAvailableMinutes != null && (dailyAvailableMinutes < 0 || dailyAvailableMinutes > 24 * 60)) {
            throw new IllegalArgumentException("하루 가용 학습 시간은 0~1440분 사이여야 합니다.");
        }
        return ResponseEntity.ok(diagnosisService.diagnose(user.getId(), plannerId, dailyAvailableMinutes, deadline));
    }
}
