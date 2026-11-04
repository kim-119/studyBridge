package com.studybridge.api.ai.quality;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.AntPathMatcher;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * 사용자 노출 AI 경로 커버리지(ai07 Phase A ACTIVE 22 + Spring 저장/캐시 재노출 경로). 단위 = Spring 공개 엔드포인트.
 *
 *  · GATED               : 응답 전에 AiResponseQualityGate/QualityStreamGate 를 통과한 결과만 노출·저장한다.
 *  · BLOCKED_WHEN_GATE_ON: 아직 게이트가 연결되지 않음 → 게이트 ON 이면 이 인터셉터가 503 AI_QUALITY_GATE_NOT_WIRED 로 막는다
 *                          (미검증 결과를 정상 응답으로 내보내는 우회 금지). 게이트 OFF 면 기존 동작.
 *  · EXEMPT              : 생성형 텍스트가 아님(숫자 예측 등) — 사유를 남긴다.
 * 게이트 ON 운영 전환 조건 = BLOCKED_WHEN_GATE_ON 0건(인계 문서 Go/No-Go). 이 목록과 실제 컨트롤러 매핑의 일치는
 * AiQualityGateCoverageTest 가 리플렉션으로 검증한다.
 */
@Slf4j
@Component
public class AiQualityGateCoverage implements HandlerInterceptor {

    public enum Status { GATED, BLOCKED_WHEN_GATE_ON, EXEMPT }

    public record Route(String method, String pattern, Status status, String upstream, String note) { }

    public static final List<Route> ROUTES = List.of(
            // 학습메이트(개인) — multi-chat SSE
            new Route("POST", "/api/agent-rooms/{roomId}/chat/stream", Status.GATED, "/api/ai/multi-chat/stream",
                    "QualityStreamGate: 메시지 단위 평가, all_complete 재구성, 승인분만 DB/Redis 영속"),
            new Route("GET", "/api/agent-rooms/{roomId}/history", Status.GATED, "(DB/Redis 저장 답변)",
                    "게이트 ON: qualityStatus=APPROVED 아닌 AI 행은 본문을 가린다"),
            new Route("POST", "/api/agent-rooms/{roomId}/chat", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/multi-chat", "non-stream"),
            new Route("POST", "/api/learning-mate/chat", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/multi-chat", ""),
            // 그룹스터디
            new Route("POST", "/api/groups/{groupId}/chats/stream", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/multi-chat/stream", "그룹 AI 봇"),
            new Route("GET", "/api/groups/{groupId}/chats/history", Status.BLOCKED_WHEN_GATE_ON, "(DB/Redis)", "그룹 AI 답변 이력"),
            new Route("POST", "/api/groups/{groupId}/materials/{materialId}/quiz", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/quiz/generate", ""),
            new Route("GET", "/api/groups/{groupId}/quizzes", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "저장된 AI 퀴즈"),
            new Route("POST", "/api/groups/{id}/screen-ai/analyze", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/vision/analyze", "VLM"),
            // 자료보관함(PDF)
            new Route("GET", "/api/materials/{materialId}/summary", Status.GATED, "/api/ai/summary",
                    "PDF_SUMMARY, 재생성 ≤2, 승인분만 저장, 미승인 캐시 미노출"),
            new Route("POST", "/api/materials/classify-before-save", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/material/classify", ""),
            new Route("POST", "/api/materials/{materialId}/quiz", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/quiz", ""),
            new Route("GET", "/api/materials/{materialId}/quiz", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "저장된 AI 퀴즈"),
            new Route("GET", "/api/materials/{materialId}/shared-quizzes", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "저장된 AI 퀴즈"),
            new Route("POST", "/api/materials/{materialId}/quiz/{quizId}/submit", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 해설 포함 채점 결과"),
            new Route("POST", "/api/materials/{materialId}/question", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/question", ""),
            new Route("GET", "/api/materials/{materialId}/roadmap", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate", "캐시+생성"),
            new Route("POST", "/api/materials/{materialId}/roadmap/regenerate", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate", ""),
            new Route("POST", "/api/materials/{materialId}/keywords/define", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/keyword/define", ""),
            new Route("GET", "/api/materials/{materialId}/feedback", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/feedback", "캐시+생성"),
            new Route("POST", "/api/materials/{materialId}/feedback/regenerate", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/feedback", ""),
            new Route("GET", "/api/materials/{materialId}/study-note", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/major-analysis/note",
                    "업로드 후 자동 생성(외부 OpenAI 전송 경로 포함)"),
            new Route("POST", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze", ""),
            new Route("GET", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", ""),
            new Route("POST", "/api/materials/{materialId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/recommendation/*", ""),
            // 오답노트
            new Route("POST", "/api/review-notes/from-quiz/{quizSessionId}", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/review/wrong-note-feedback", ""),
            new Route("GET", "/api/review-notes", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 해설 저장본"),
            new Route("GET", "/api/review-notes/{id}", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 해설 저장본"),
            new Route("GET", "/api/review-notes/{id}/retry", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 보강 retryJson"),
            new Route("POST", "/api/review-notes/{id}/review-needed", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/review-needed", ""),
            new Route("POST", "/api/review-notes/{id}/variant-question", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/review/variant-question", ""),
            // 마인드맵/플래너
            new Route("POST", "/api/mindmap/semantic-graph", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/mindmap/semantic-graph", "Redis 168h 캐시"),
            new Route("POST", "/api/planners/{plannerId}/ai-assist", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/assist", ""),
            new Route("GET", "/api/planners/{plannerId}/ai-result", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "폴백도 AI 로 표기되는 기존 결함"),
            new Route("POST", "/api/planners/{plannerId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze-semantic", ""),
            new Route("GET", "/api/planners/{plannerId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", ""),
            new Route("GET", "/api/planners/{plannerId}/schedule", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze-semantic", "ensure()"),
            new Route("POST", "/api/planners/{plannerId}/schedule/pdf", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze-semantic", "ensure()"),
            new Route("POST", "/api/planners/{plannerId}/adaptive", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/adaptive", ""),
            new Route("POST", "/api/planners/{plannerId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/recommendation/*", ""),
            // 생성형 텍스트 아님
            new Route("GET", "/api/study-time/predict", Status.EXEMPT, "/api/ai/predict-study-time",
                    "숫자 예측(로컬 폴백 있음) — response-quality.v1 프로파일 없음"));

    private static final AntPathMatcher MATCHER = new AntPathMatcher();
    private final AiQualityGateSettings settings;
    private final ObjectMapper mapper = new ObjectMapper();

    public AiQualityGateCoverage(AiQualityGateSettings settings) {
        this.settings = settings;
    }

    public static Route match(String method, String path) {
        for (Route r : ROUTES) {
            if (r.method().equalsIgnoreCase(method) && MATCHER.match(r.pattern(), path)) {
                return r;
            }
        }
        return null;
    }

    public static long count(Status s) {
        return ROUTES.stream().filter(r -> r.status() == s).count();
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        if (!settings.enabled()) {
            return true;
        }
        Route r = match(request.getMethod(), request.getRequestURI());
        if (r == null || r.status() != Status.BLOCKED_WHEN_GATE_ON) {
            return true;
        }
        log.warn("[QUALITY-GATE] 미연결 AI 경로 차단 {} {} (pattern={})", request.getMethod(), r.pattern(), r.pattern());
        response.setStatus(HttpStatus.SERVICE_UNAVAILABLE.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write(mapper.writeValueAsString(Map.of(
                "success", false, "errorCode", GateDecision.NOT_WIRED, "qualityStatus", "VALIDATION_ERROR", "verified", false,
                "retryable", false, "message", GateDecision.userMessage(GateDecision.NOT_WIRED))));
        return false;
    }
}
