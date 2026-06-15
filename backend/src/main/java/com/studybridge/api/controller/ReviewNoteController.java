package com.studybridge.api.controller;

import com.studybridge.api.dto.ReviewNoteDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.ReviewNoteService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 오답노트 API.
 *  - POST /api/review-notes/from-quiz/{quizSessionId} : 퀴즈 오답으로 오답노트 생성
 *  - GET  /api/review-notes                            : 목록
 *  - GET  /api/review-notes/{id}/download              : PDF presigned URL
 *  - GET  /api/review-notes/{id}/retry                 : 다시 풀기용 문제
 *  - PATCH /api/review-notes/{id}/memo                 : 메모 저장
 *  - DELETE /api/review-notes/{id}                      : 오답노트 삭제(+연동 Material/S3 정리)
 */
@RestController
@RequestMapping("/api/review-notes")
@RequiredArgsConstructor
public class ReviewNoteController {

    private final ReviewNoteService reviewNoteService;

    @GetMapping
    public ResponseEntity<List<ReviewNoteDTO>> list(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(reviewNoteService.list(userDetails.getId()));
    }

    @GetMapping("/{id}")
    public ResponseEntity<ReviewNoteDTO> get(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(reviewNoteService.get(userDetails.getId(), id));
    }

    // {quizSessionId} = MaterialQuiz.quizId. 본문은 사용자가 푼 답안 { answers: { "0":2, "1":0 } }
    @PostMapping("/from-quiz/{quizSessionId}")
    public ResponseEntity<ReviewNoteDTO> createFromQuiz(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long quizSessionId,
            @RequestBody(required = false) Map<String, Object> body) {
        Map<String, Object> answers = extractAnswers(body);
        return ResponseEntity.ok(reviewNoteService.createFromQuiz(userDetails.getId(), quizSessionId, answers));
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        reviewNoteService.delete(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/{id}/download")
    public ResponseEntity<Map<String, Object>> download(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(reviewNoteService.getDownloadUrl(userDetails.getId(), id));
    }

    @GetMapping("/{id}/retry")
    public ResponseEntity<Map<String, Object>> retry(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(reviewNoteService.getRetry(userDetails.getId(), id));
    }

    @PatchMapping("/{id}/memo")
    public ResponseEntity<ReviewNoteDTO> updateMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @RequestBody(required = false) Map<String, Object> body) {
        String memo = body != null && body.get("memo") != null ? body.get("memo").toString() : "";
        return ResponseEntity.ok(reviewNoteService.updateMemo(userDetails.getId(), id, memo));
    }

    // 복습 필요 분석: 오답노트 데이터 기반 AI 생성("OOO에 대한 개념이 부족하여 복습이 필요합니다. ...", 500자 내외)
    //   본인 오답노트만 접근(없으면 404, 타인 403). AI 실패 시 데이터 기반 폴백 문장 반환.
    @PostMapping("/{id}/review-needed")
    public ResponseEntity<Map<String, Object>> reviewNeeded(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(reviewNoteService.generateReviewNeeded(userDetails.getId(), id));
    }

    // 유사문제: ai07 변형(없으면 원본 오답 재출제 폴백). body { wrongQuestionId, difficulty: easy|normal|hard, count }
    @PostMapping("/{id}/variant-question")
    public ResponseEntity<Map<String, Object>> variantQuestion(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @RequestBody(required = false) Map<String, Object> body) {
        return ResponseEntity.ok(reviewNoteService.variantQuestion(userDetails.getId(), id, body));
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> extractAnswers(Map<String, Object> body) {
        if (body == null) return Map.of();
        if (body.get("answers") instanceof Map) return (Map<String, Object>) body.get("answers");
        return body;
    }
}
