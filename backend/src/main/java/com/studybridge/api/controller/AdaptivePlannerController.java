package com.studybridge.api.controller;

import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.adaptive.AdaptivePlannerApplyService;
import com.studybridge.api.service.adaptive.AdaptivePlannerException;
import com.studybridge.api.service.adaptive.AdaptivePlannerService;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.RequiredArgsConstructor;
import lombok.Setter;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;

/**
 * AI 학습 내비게이터(ai07 적응형 학습 엔진 연동). 로드맵 플래너는 현재 단계 코칭(ROADMAP_COACH), 수기 플래너는 다음 학습(MANUAL_NEXT).
 *
 * <ul>
 *   <li>POST /api/planners/{plannerId}/adaptive  {availableMinutes:15|30|60, useLlm?, currentStepId?} — 추천만(저장 없음).</li>
 *   <li>POST /api/planners/{plannerId}/adaptive/apply {proposalToken, changeIds[]} — 사용자가 승인한 일정 제안만 반영.</li>
 * </ul>
 * 오류 본문 {error:{code,message,retryable,requestId?[,retryAfterSeconds][,details]}} + 429/503 은 Retry-After 헤더.
 * 기존 GET /next-learning, /recommendations 는 다른 화면 호환을 위해 그대로 둔다.
 */
@Slf4j
@RestController
@RequestMapping("/api/planners")
@RequiredArgsConstructor
public class AdaptivePlannerController {

    private final AdaptivePlannerService adaptivePlannerService;
    private final AdaptivePlannerApplyService adaptivePlannerApplyService;

    @Getter
    @Setter
    @NoArgsConstructor
    public static class RecommendRequest {
        private Integer availableMinutes;
        private Boolean useLlm;
        private Long currentStepId;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class ApplyRequest {
        private String proposalToken;
        private List<String> changeIds;
    }

    @PostMapping("/{plannerId}/adaptive")
    public ResponseEntity<?> recommend(@AuthenticationPrincipal CustomUserDetails userDetails,
                                       @PathVariable Long plannerId,
                                       @RequestBody(required = false) RecommendRequest body) {
        RecommendRequest req = body == null ? new RecommendRequest() : body;
        try {
            return ResponseEntity.ok(adaptivePlannerService.recommend(userDetails.getId(), plannerId,
                    req.getAvailableMinutes(), req.getUseLlm(), req.getCurrentStepId()));
        } catch (RuntimeException e) {
            return error(e, plannerId, "recommend");
        }
    }

    @PostMapping("/{plannerId}/adaptive/apply")
    public ResponseEntity<?> apply(@AuthenticationPrincipal CustomUserDetails userDetails,
                                   @PathVariable Long plannerId,
                                   @RequestBody(required = false) ApplyRequest body) {
        ApplyRequest req = body == null ? new ApplyRequest() : body;
        try {
            return ResponseEntity.ok(adaptivePlannerApplyService.apply(userDetails.getId(), plannerId,
                    req.getProposalToken(), req.getChangeIds()));
        } catch (RuntimeException e) {
            return error(e, plannerId, "apply");
        }
    }

    static ResponseEntity<Map<String, Object>> error(RuntimeException e, Long plannerId, String op) {
        HttpStatus status;
        String code;
        String message;
        boolean retryable = false;
        Integer retryAfter = null;
        Map<String, Object> details = null;
        if (e instanceof AdaptivePlannerException a) {
            status = a.getStatus();
            code = a.getCode();
            message = a.getMessage();
            retryable = a.isRetryable();
            retryAfter = a.getRetryAfterSeconds();
            details = a.getDetails();
        } else if (e instanceof SecurityException) {
            status = HttpStatus.FORBIDDEN;
            code = "FORBIDDEN";
            message = "본인의 플래너만 이용할 수 있습니다.";
        } else if (e instanceof NoSuchElementException) {
            status = HttpStatus.NOT_FOUND;
            code = "NOT_FOUND";
            message = "플래너를 찾을 수 없습니다.";
        } else if (e instanceof IllegalArgumentException) {
            status = HttpStatus.BAD_REQUEST;
            code = "ADAPTIVE_INVALID_REQUEST";
            message = "요청 값이 올바르지 않습니다.";
        } else {
            log.error("[ADAPTIVE] {} plannerId={} UNEXPECTED", op, plannerId, e);
            status = HttpStatus.INTERNAL_SERVER_ERROR;
            code = "ADAPTIVE_INTERNAL_ERROR";
            message = "AI 학습 내비게이터 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.";
            retryable = true;
        }
        Map<String, Object> err = new LinkedHashMap<>();
        err.put("code", code);
        err.put("message", message);
        err.put("retryable", retryable);
        if (retryAfter != null) err.put("retryAfterSeconds", retryAfter);
        if (details != null && !details.isEmpty()) err.put("details", details);
        ResponseEntity.BodyBuilder b = ResponseEntity.status(status);
        if (retryAfter != null && (status == HttpStatus.TOO_MANY_REQUESTS || status == HttpStatus.SERVICE_UNAVAILABLE)) {
            b.header(HttpHeaders.RETRY_AFTER, String.valueOf(retryAfter));
        }
        return b.body(Map.of("error", err));
    }
}
