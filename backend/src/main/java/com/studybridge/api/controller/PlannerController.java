package com.studybridge.api.controller;

import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.PlannerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@Slf4j
@RestController
@RequestMapping("/api/planners")
@RequiredArgsConstructor
public class PlannerController {

    private final PlannerService plannerService;
    private final com.studybridge.api.service.PlannerAiService plannerAiService;

    @PostMapping
    public ResponseEntity<PlannerDTO.Response> create(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody PlannerDTO.Request request) {
        return ResponseEntity.ok(plannerService.create(userDetails.getId(), request));
    }

    @GetMapping
    public ResponseEntity<List<PlannerDTO.Response>> list(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(plannerService.getMyPlanners(userDetails.getId()));
    }

    /**
     * 로드맵(12주×7일=84일) → 플래너 84개 자동 생성.
     * 오직 플래너 도메인(planners 테이블)에만 저장한다. 주간일정/schedule/calendar 도메인과는 무관하다.
     */
    @PostMapping("/from-roadmap")
    public ResponseEntity<PlannerDTO.FromRoadmapResponse> fromRoadmap(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody PlannerDTO.FromRoadmapRequest request) {
        return ResponseEntity.ok(plannerService.createFromRoadmap(userDetails.getId(), request));
    }

    @PutMapping("/{plannerId}")
    public ResponseEntity<PlannerDTO.Response> update(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId,
            @RequestBody PlannerDTO.Request request) {
        return ResponseEntity.ok(plannerService.update(userDetails.getId(), plannerId, request));
    }

    @GetMapping("/{plannerId}")
    public ResponseEntity<PlannerDTO.Response> get(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerService.get(userDetails.getId(), plannerId));
    }

    /** PDF 생성 → S3 저장 → 자료보관함(Material, PLANNER) 연결 */
    @PostMapping("/{plannerId}/pdf")
    public ResponseEntity<PlannerDTO.Response> generatePdf(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerService.generateAndArchive(userDetails.getId(), plannerId));
    }

    /** 자료보관함에 저장 (PDF 생성/보관과 동일 동작) */
    @PostMapping("/{plannerId}/archive")
    public ResponseEntity<PlannerDTO.Response> archive(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerService.generateAndArchive(userDetails.getId(), plannerId));
    }

    @GetMapping("/{plannerId}/download-url")
    public ResponseEntity<Map<String, String>> downloadUrl(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(Map.of("downloadUrl", plannerService.getDownloadUrl(userDetails.getId(), plannerId)));
    }

    @DeleteMapping("/{plannerId}")
    public ResponseEntity<Void> delete(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        plannerService.delete(userDetails.getId(), plannerId);
        return ResponseEntity.noContent().build();
    }

    // ---------- 공부 플래너 전용 AI (학습 실행 관리) ----------
    // 로드맵/퀴즈/문서질문/요약 없음. 플래너를 실행 가능한 계획으로 정리하고 피드백만 한다.

    /** AI 피드백 및 다음 학습 추천 */
    @PostMapping("/{plannerId}/ai-assist")
    public ResponseEntity<com.studybridge.api.dto.PlannerAiDTO.AssistResponse> aiAssist(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerAiService.assist(userDetails.getId(), plannerId));
    }

    /** 저장된 AI 피드백 조회 */
    @GetMapping("/{plannerId}/ai-result")
    public ResponseEntity<com.studybridge.api.dto.PlannerAiDTO.AssistResponse> aiResult(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerAiService.getAiResult(userDetails.getId(), plannerId));
    }
}
