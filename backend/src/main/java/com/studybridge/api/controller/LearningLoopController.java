package com.studybridge.api.controller;

import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.LearningLoopService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.List;
import java.util.Map;

/**
 * 학습 왕복 루프 API. React → Spring 만 호출(FastAPI 직접 호출 금지).
 *  - GET  /api/learning-loop/events             : 이벤트 이력 조회(materialId/documentId/source 필터)
 *  - POST /api/learning-loop/events             : 이벤트 직접 기록
 *  - GET  /api/learning-loop/context            : 다음 AI 호출용 learningLoopContext 패키지
 *  - POST /api/learning-loop/review-recommendation : 복습 추천일 계산
 *  - POST /api/learning-loop/review-schedule    : 복습 일정을 플래너(주간일정)에 등록
 *  - POST /api/learning-loop/study-log          : 학습 이벤트를 학습일지 기록으로 연결
 */
@Slf4j
@RestController
@RequestMapping("/api/learning-loop")
@RequiredArgsConstructor
public class LearningLoopController {

    private final LearningLoopService learningLoopService;

    @GetMapping("/events")
    public ResponseEntity<List<Map<String, Object>>> events(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam(required = false) Long materialId,
            @RequestParam(required = false) Long documentId,
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) Long sourceId,
            @RequestParam(required = false, defaultValue = "30") int limit) {
        LearningSourceType st = parseSource(sourceType);
        return ResponseEntity.ok(
                learningLoopService.queryEvents(userDetails.getId(), materialId, documentId, st, sourceId, limit));
    }

    @PostMapping("/events")
    public ResponseEntity<Map<String, Object>> record(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody Map<String, Object> body) {
        LearningEventType type = parseEventType(str(body, "eventType"));
        if (type == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "eventType is required/invalid"));
        }
        LearningLoopEvent event = LearningLoopEvent.builder()
                .userId(userDetails.getId())
                .eventType(type)
                .sourceType(parseSource(str(body, "sourceType")))
                .sourceId(lng(body, "sourceId"))
                .materialId(lng(body, "materialId"))
                .documentId(lng(body, "documentId"))
                .roomId(lng(body, "roomId"))
                .plannerId(lng(body, "plannerId"))
                .wrongNoteId(lng(body, "wrongNoteId"))
                .quizId(lng(body, "quizId"))
                .questionId(lng(body, "questionId"))
                .inputText(str(body, "inputText"))
                .aiOutputSummary(str(body, "aiOutputSummary"))
                .aiOutputJson(str(body, "aiOutputJson"))
                .userAction(str(body, "userAction"))
                .userMemo(str(body, "userMemo"))
                .difficulty(str(body, "difficulty"))
                .build();
        Long id = learningLoopService.recordSafe(event);
        return ResponseEntity.ok(Map.of("id", id == null ? -1 : id, "saved", id != null));
    }

    @GetMapping("/context")
    public ResponseEntity<Map<String, Object>> context(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam(required = false) Long materialId,
            @RequestParam(required = false) Long documentId) {
        return ResponseEntity.ok(learningLoopService.assembleContext(userDetails.getId(), materialId, documentId));
    }

    @PostMapping("/review-recommendation")
    public ResponseEntity<Map<String, Object>> recommend(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody(required = false) Map<String, Object> body) {
        return ResponseEntity.ok(learningLoopService.recommendReview(
                userDetails.getId(), lng(body, "materialId"), lng(body, "wrongNoteId"),
                str(body, "difficulty"), intOrNull(body, "wrongCount")));
    }

    @PostMapping("/review-schedule")
    public ResponseEntity<Map<String, Object>> reviewSchedule(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody(required = false) Map<String, Object> body) {
        LocalDate date = parseDate(str(body, "scheduledDate"));
        return ResponseEntity.ok(learningLoopService.registerReviewSchedule(
                userDetails.getId(), lng(body, "materialId"), lng(body, "wrongNoteId"),
                str(body, "title"), date, str(body, "reason")));
    }

    @PostMapping("/study-log")
    public ResponseEntity<Map<String, Object>> studyLog(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody(required = false) Map<String, Object> body) {
        LearningLoopEvent event = LearningLoopEvent.builder()
                .userId(userDetails.getId())
                .eventType(LearningEventType.STUDY_LOG_CREATED)
                .sourceType(LearningSourceType.STUDY_LOG)
                .sourceId(lng(body, "eventId"))
                .materialId(lng(body, "materialId"))
                .aiOutputSummary(str(body, "title"))
                .userMemo(str(body, "content"))
                .userAction("STUDY_LOG_LINKED")
                .build();
        Long id = learningLoopService.recordSafe(event);
        return ResponseEntity.ok(Map.of("id", id == null ? -1 : id, "saved", id != null));
    }

    // ---------------- 파싱 헬퍼 ----------------
    private LearningEventType parseEventType(String v) {
        if (v == null || v.isBlank()) return null;
        try { return LearningEventType.valueOf(v.trim().toUpperCase()); }
        catch (Exception e) { return null; }
    }

    private LearningSourceType parseSource(String v) {
        if (v == null || v.isBlank()) return null;
        try { return LearningSourceType.valueOf(v.trim().toUpperCase()); }
        catch (Exception e) { return null; }
    }

    private LocalDate parseDate(String v) {
        if (v == null || v.isBlank()) return null;
        try { return LocalDate.parse(v.trim().substring(0, 10)); }
        catch (Exception e) { return null; }
    }

    private String str(Map<String, Object> m, String k) {
        if (m == null || m.get(k) == null) return null;
        String s = m.get(k).toString();
        return s.isBlank() ? null : s;
    }

    private Long lng(Map<String, Object> m, String k) {
        if (m == null || m.get(k) == null) return null;
        Object v = m.get(k);
        if (v instanceof Number) return ((Number) v).longValue();
        try { return Long.parseLong(v.toString().trim()); } catch (Exception e) { return null; }
    }

    private Integer intOrNull(Map<String, Object> m, String k) {
        Long v = lng(m, k);
        return v == null ? null : v.intValue();
    }
}
