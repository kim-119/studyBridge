package com.studybridge.api.controller;

import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.SocraticReviewService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

/**
 * 소크라테스 복습 세션 프록시. React→Spring→ai07(materialId 소유권 검증 후 호출).
 *  - 세션 시작/답변/완료/복습일 일정 등록.
 */
@RestController
@RequestMapping("/api/materials/{materialId}/socratic-review")
@RequiredArgsConstructor
public class SocraticReviewController {

    private final SocraticReviewService socraticReviewService;

    @PostMapping("/sessions")
    public ResponseEntity<Map<String, Object>> start(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody(required = false) Map<String, Object> body) {
        return ResponseEntity.ok(socraticReviewService.startSession(userDetails.getId(), materialId, body == null ? Map.of() : body));
    }

    @PostMapping("/sessions/{sessionId}/answers")
    public ResponseEntity<Map<String, Object>> answer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable String sessionId,
            @RequestBody(required = false) Map<String, Object> body) {
        String answer = body != null && body.get("answer") != null ? body.get("answer").toString() : "";
        return ResponseEntity.ok(socraticReviewService.submitAnswer(userDetails.getId(), materialId, sessionId, answer));
    }

    @PostMapping("/sessions/{sessionId}/finish")
    public ResponseEntity<Map<String, Object>> finish(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable String sessionId) {
        return ResponseEntity.ok(socraticReviewService.finishSession(userDetails.getId(), materialId, sessionId));
    }

    @PostMapping("/sessions/{sessionId}/schedule-review")
    public ResponseEntity<Map<String, Object>> scheduleReview(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable String sessionId,
            @RequestBody(required = false) Map<String, Object> body) {
        String reviewDate = body != null && body.get("reviewDate") != null ? body.get("reviewDate").toString() : null;
        return ResponseEntity.ok(socraticReviewService.scheduleReview(userDetails.getId(), materialId, sessionId, reviewDate));
    }
}
