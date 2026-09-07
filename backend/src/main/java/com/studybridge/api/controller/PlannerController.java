package com.studybridge.api.controller;

import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.dto.PlannerSemanticDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.PlanAnalysisException;
import com.studybridge.api.service.PlannerScheduleService;
import com.studybridge.api.service.PlannerSemanticAnalyzer;
import com.studybridge.api.service.PlannerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;

@Slf4j
@RestController
@RequestMapping("/api/planners")
@RequiredArgsConstructor
public class PlannerController {

    private final PlannerService plannerService;
    private final com.studybridge.api.service.PlannerAiService plannerAiService;
    private final PlannerSemanticAnalyzer plannerSemanticAnalyzer;
    private final PlannerScheduleService plannerScheduleService;

    @PostMapping
    public ResponseEntity<PlannerDTO.Response> create(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody PlannerDTO.Request request) {
        return ResponseEntity.ok(plannerService.create(userDetails.getId(), request));
    }

    /**
     * 내 플래너 목록. ?type=ROADMAP / ?type=USER 로 원천 필터링(미지정 시 전체).
     * 알 수 없는 type 값은 전체 조회로 폴백한다(기존 프론트 호출 호환).
     */
    @GetMapping
    public ResponseEntity<List<PlannerDTO.Response>> list(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam(required = false) String type) {
        com.studybridge.api.entity.PlannerType pt = null;
        if (type != null && !type.isBlank()) {
            try { pt = com.studybridge.api.entity.PlannerType.valueOf(type.trim().toUpperCase()); }
            catch (IllegalArgumentException ignored) { /* 알 수 없는 값 → 전체 */ }
        }
        return ResponseEntity.ok(plannerService.getMyPlanners(userDetails.getId(), pt));
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

    /** "PDF 저장": 다운로드용 PDF 생성(presigned URL 반환) + 자료보관함은 구조화 PLANNER 로 보관 */
    @PostMapping("/{plannerId}/pdf")
    public ResponseEntity<PlannerDTO.Response> generatePdf(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerService.generatePdfDownload(userDetails.getId(), plannerId));
    }

    /** 자료보관함에 저장: 플래너를 PDF 가 아닌 구조화(PLANNER) 자료로 보관 */
    @PostMapping("/{plannerId}/archive")
    public ResponseEntity<PlannerDTO.Response> archive(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        return ResponseEntity.ok(plannerService.archivePlanner(userDetails.getId(), plannerId));
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

    /**
     * 자료 기반(ROADMAP_AUTO) 플래너 전체삭제.
     * 현재 화면에 표시 중인 plannerIds 만 삭제하며, 수동 플래너/주간일정/다른 유저 데이터는 절대 삭제하지 않는다.
     */
    @DeleteMapping("/bulk")
    public ResponseEntity<PlannerDTO.BulkDeleteResponse> bulkDelete(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody PlannerDTO.BulkDeleteRequest request) {
        PlannerDTO.BulkDeleteResponse res = plannerService.bulkDelete(userDetails.getId(), request);
        return res.isSuccess()
                ? ResponseEntity.ok(res)
                : ResponseEntity.badRequest().body(res);
    }

    /**
     * 체크박스 선택 삭제. body { plannerIds: [1,2,3] }
     * 선택한 본인 소유 플래너만 삭제, 주간일정/다른 유저 데이터는 건드리지 않는다.
     */
    @DeleteMapping("/bulk-selected")
    @SuppressWarnings("unchecked")
    public ResponseEntity<PlannerDTO.BulkDeleteResponse> bulkDeleteSelected(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody Map<String, Object> body) {
        List<Long> ids = new java.util.ArrayList<>();
        Object raw = body != null ? body.get("plannerIds") : null;
        if (raw instanceof List) {
            for (Object o : (List<Object>) raw) {
                if (o instanceof Number) ids.add(((Number) o).longValue());
                else if (o != null) { try { ids.add(Long.parseLong(o.toString())); } catch (NumberFormatException ignored) {} }
            }
        }
        PlannerDTO.BulkDeleteResponse res = plannerService.bulkDeleteSelected(userDetails.getId(), ids);
        return res.isSuccess()
                ? ResponseEntity.ok(res)
                : ResponseEntity.badRequest().body(res);
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

    // ---------- AI 계획 분석(구조화 시맨틱) + 동적 하루 학습 시간표 ----------

    /** AI 계획 분석 생성/재생성(플래너 실데이터 → AI07 → 검증/정규화). 실패해도 플래너 열람은 막지 않는다. */
    @PostMapping("/{plannerId}/plan-analysis")
    public ResponseEntity<PlannerSemanticDTO.AnalysisResponse> analyzePlan(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        try {
            return ResponseEntity.ok(plannerSemanticAnalyzer.analyze(userDetails.getId(), plannerId));
        } catch (PlanAnalysisException e) {
            log.warn("[planner:plan-analysis] plannerId={} errorCode={} msg={}", plannerId, e.getErrorCode(), e.getMessage());
            return ResponseEntity.status(HttpStatus.UNPROCESSABLE_ENTITY).body(errorAnalysis(plannerId, e.getErrorCode(), e.getMessage()));
        } catch (SecurityException e) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body(errorAnalysis(plannerId, "FORBIDDEN", e.getMessage()));
        } catch (NoSuchElementException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(errorAnalysis(plannerId, "NOT_FOUND", e.getMessage()));
        } catch (Exception e) {
            log.error("[planner:plan-analysis] plannerId={} UNEXPECTED", plannerId, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(errorAnalysis(plannerId, "PLAN_ANALYSIS_FAILED", "AI 계획 분석에 실패했습니다. 잠시 후 다시 시도해 주세요."));
        }
    }

    /** 저장된 AI 계획 분석 조회(없으면 empty=true). */
    @GetMapping("/{plannerId}/plan-analysis")
    public ResponseEntity<PlannerSemanticDTO.AnalysisResponse> getPlanAnalysis(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId) {
        try {
            return ResponseEntity.ok(plannerSemanticAnalyzer.get(userDetails.getId(), plannerId));
        } catch (SecurityException e) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body(errorAnalysis(plannerId, "FORBIDDEN", e.getMessage()));
        } catch (NoSuchElementException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).body(errorAnalysis(plannerId, "NOT_FOUND", e.getMessage()));
        }
    }

    /** 시작시간 기준 결정적 시간표 미리보기(AI 재호출 없음). */
    @GetMapping("/{plannerId}/schedule")
    public ResponseEntity<?> schedule(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId,
            @RequestParam(defaultValue = "09:00") String startTime) {
        try {
            return ResponseEntity.ok(plannerScheduleService.schedule(userDetails.getId(), plannerId, startTime));
        } catch (SecurityException e) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body(Map.of("message", e.getMessage()));
        } catch (IllegalArgumentException | IllegalStateException e) {
            return ResponseEntity.badRequest().body(Map.of("message", e.getMessage()));
        }
    }

    /** 시간표 PDF 생성 → S3 저장 → presigned 다운로드 URL 반환. */
    @PostMapping("/{plannerId}/schedule/pdf")
    public ResponseEntity<?> schedulePdf(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long plannerId,
            @RequestBody(required = false) PlannerSemanticDTO.ScheduleRequest req) {
        String startTime = req != null && req.getStartTime() != null ? req.getStartTime() : "09:00";
        try {
            return ResponseEntity.ok(plannerScheduleService.generatePdf(userDetails.getId(), plannerId, startTime));
        } catch (SecurityException e) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body(Map.of("message", e.getMessage()));
        } catch (IllegalArgumentException | IllegalStateException e) {
            return ResponseEntity.badRequest().body(Map.of("message", e.getMessage()));
        } catch (Exception e) {
            log.error("[planner:schedule-pdf] plannerId={} UNEXPECTED", plannerId, e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("message", "시간표 PDF 생성에 실패했습니다. 잠시 후 다시 시도해 주세요."));
        }
    }

    private PlannerSemanticDTO.AnalysisResponse errorAnalysis(Long plannerId, String code, String message) {
        return PlannerSemanticDTO.AnalysisResponse.builder()
                .plannerId(plannerId).empty(true).errorCode(code).summary(message).build();
    }
}
