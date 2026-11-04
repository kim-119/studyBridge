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
 * 등록하지 않은 것(사유): POST /api/materials/upload — 응답에 AI 텍스트가 없다. 업로드 후 백그라운드로 만드는 학습노트는
 *  GET /api/materials/{materialId}/study-note(BLOCKED)로만 노출된다.
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
            new Route("POST", "/api/groups/{groupId}/materials/upload-quiz", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/quiz/generate",
                    "그룹 자료 업로드+퀴즈 생성(Phase C 추가, ai07 인계 5.4)"),
            new Route("POST", "/api/groups/{id}/screen-ai/analyze", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/vision/analyze", "VLM"),
            // 자료보관함(PDF)
            new Route("GET", "/api/materials/{materialId}/summary", Status.GATED, "/api/ai/summary",
                    "PDF_SUMMARY, 재생성 ≤2, 승인분만 저장, 미승인 캐시 미노출"),
            new Route("POST", "/api/materials/classify-before-save", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/material/classify", ""),
            new Route("POST", "/api/materials/{materialId}/quiz", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/quiz", ""),
            new Route("GET", "/api/materials/{materialId}/quiz", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "저장된 AI 퀴즈"),
            new Route("GET", "/api/materials/{materialId}/shared-quizzes", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "저장된 AI 퀴즈"),
            new Route("POST", "/api/materials/{materialId}/quiz/{quizId}/submit", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 해설 포함 채점 결과"),
            new Route("POST", "/api/materials/{materialId}/question", Status.GATED, "/api/ai/question",
                    "PDF_QA(질문 관련 자료 원문 근거), 재생성 ≤2, 승인 답변만 저장(quality_status), 라우터 LLM 문구→고정 문구, BLOCKED 파이프라인 미실행"),
            new Route("GET", "/api/materials/{materialId}/roadmap", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate", "캐시+생성"),
            new Route("POST", "/api/materials/{materialId}/roadmap/regenerate", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate", ""),
            new Route("POST", "/api/materials/{materialId}/keywords/define", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/keyword/define", ""),
            new Route("GET", "/api/materials/{materialId}/feedback", Status.GATED, "/api/ai/feedback",
                    "GENERAL_EXPLANATION(자료 원문 근거), 재생성 ≤2, 승인분만 저장(quality_status), 미승인 저장본 미노출, 거절 쿨다운 120s"),
            new Route("POST", "/api/materials/{materialId}/feedback/regenerate", Status.GATED, "/api/ai/feedback", "위와 같은 게이트"),
            new Route("GET", "/api/materials/{materialId}/study-note", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/major-analysis/note",
                    "업로드 후 자동 생성(외부 OpenAI 전송 경로 포함)"),
            new Route("POST", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze", ""),
            new Route("GET", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", ""),
            new Route("POST", "/api/materials/{materialId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/recommendation/*", ""),
            new Route("GET", "/api/materials/{materialId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "저장된 AI 추천 재노출(Phase C 추가)"),
            new Route("POST", "/api/materials/{materialId}/plan-recommendation", Status.BLOCKED_WHEN_GATE_ON, "(DB plan_analysis)",
                    "저장된 AI 계획 분석 기반 추천 재노출(Phase C 추가)"),
            new Route("POST", "/api/materials/{materialId}/study-journals", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/study-journal/validate",
                    "저장 거절 시 AI 판정 사유(reason/suggestion)를 사용자에게 보여 준다(Phase C 추가). 외부 OpenAI 전송 경로"),
            // 오답노트
            new Route("POST", "/api/review-notes/from-quiz/{quizSessionId}", Status.GATED, "/api/ai/review/wrong-note-feedback",
                    "초기 응답=AI 없는 퀴즈 기반본(가림), 백그라운드 보강 WRONG_NOTE_EXPLANATION(원본 자료 근거) 재생성 ≤2 → 승인분만 반영"),
            new Route("GET", "/api/review-notes", Status.GATED, "(DB)", "게이트 ON: quality_status≠APPROVED 면 PDF·복습 필요 분석 가림(문항·메모 유지)"),
            new Route("GET", "/api/review-notes/{id}", Status.GATED, "(DB)", "위와 같음"),
            new Route("GET", "/api/review-notes/{id}/retry", Status.GATED, "(DB)", "게이트 ON: 미승인 retryJson 의 해설·개념 제거(문항·정답·내 답·재풀이 기록 유지)"),
            new Route("POST", "/api/review-notes/{id}/review-needed", Status.GATED, "/api/ai/review-needed",
                    "WRONG_NOTE_EXPLANATION(원본 자료 근거), 재생성 ≤2, 승인분만 저장(review_needed_quality_status), 미승인 저장본 재생성"),
            new Route("POST", "/api/review-notes/{id}/variant-question", Status.GATED, "/api/ai/review/variant-question",
                    "SIMILAR_QUESTION(quiz_json, 원본 자료 근거), 재생성 ≤2, 승인 문항만 응답, 거절=success:false"),
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
            new Route("GET", "/api/planners/{plannerId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "저장된 AI 추천 재노출(Phase C 추가)"),
            // 생성형 텍스트 아님
            new Route("GET", "/api/study-time/predict", Status.EXEMPT, "/api/ai/predict-study-time",
                    "숫자 예측(로컬 폴백 있음) — response-quality.v1 프로파일 없음"),
            // ── Phase D2: 바이트코드 호출 그래프 분류기(AiRouteClassifierTest)가 찾은 AI 저장본 재노출 경로 ──
            new Route("GET", "/api/materials/{materialId}/quiz/{quizId}/score", Status.BLOCKED_WHEN_GATE_ON, "(DB/Redis)",
                    "채점 결과 results[].explanation = AI 해설"),
            new Route("GET", "/api/groups/{groupId}/quiz/session", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "현재 문항 = 저장된 AI 퀴즈 문항·보기"),
            new Route("GET", "/api/review-notes/{id}/download", Status.GATED, "(DB)", "게이트 ON: 오답노트 본문 미승인이면 PDF URL 미발급(가림 표식)"),
            new Route("PATCH", "/api/review-notes/{id}/memo", Status.GATED, "(DB)", "응답 ReviewNoteDTO 는 목록·상세와 같은 가림(메모는 사용자 데이터)"),
            new Route("POST", "/api/review-notes/{id}/retry/submit", Status.EXEMPT, "(DB)",
                    "응답 = 사용자 재풀이 기록(index/userAnswer/correct/answeredAt)·개수뿐, AI 생성 문자열 없음(정답 대조는 원래 문제의 정답)"),
            new Route("PUT", "/api/materials/{materialId}/roadmap/days/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 로드맵 전체"),
            new Route("PUT", "/api/materials/{materialId}/roadmap/tasks/{taskId}/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "응답 = AI 로드맵 과제"),
            new Route("PATCH", "/api/plan-analysis/items/{itemId}", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 계획 분석"),
            new Route("GET", "/api/planners/{plannerId}/next-learning", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "결정적 규칙이나 항목명 = AI 계획 분석 결과"),
            new Route("GET", "/api/planners/{plannerId}/diagnosis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 계획 분석 기반 진단"),
            new Route("POST", "/api/planners/{plannerId}/adaptive/apply", Status.BLOCKED_WHEN_GATE_ON, "(서명 제안 토큰)",
                    "AI 적응형 제안 적용 — 응답·생성 todo 제목이 AI 제안"),
            new Route("POST", "/api/recommendations/{id}/accept", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("POST", "/api/recommendations/{id}/reject", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("POST", "/api/recommendations/{id}/complete", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("GET", "/api/materials/{materialId}/study-journals", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "AI 판정 라벨(validationDecision/category/relationPath) — 사용자 메모 본문과 분리 필요"),
            new Route("GET", "/api/materials/{materialId}/study-journals/{journalId}", Status.BLOCKED_WHEN_GATE_ON, "(DB/S3)", "위와 같음"));

    private static final AntPathMatcher MATCHER = new AntPathMatcher();
    private final AiQualityGateSettings settings;
    private final ObjectMapper mapper = new ObjectMapper();

    private AiQualityUserRateLimiter rateLimiter;

    public AiQualityGateCoverage(AiQualityGateSettings settings) {
        this.settings = settings;
    }

    @org.springframework.beans.factory.annotation.Autowired(required = false)
    public void setRateLimiter(AiQualityUserRateLimiter rateLimiter) {
        this.rateLimiter = rateLimiter;
    }

    static String userKey(HttpServletRequest request) {
        var auth = org.springframework.security.core.context.SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.isAuthenticated() && auth.getName() != null && !"anonymousUser".equals(auth.getName())) {
            return "u:" + auth.getName();
        }
        return request.getUserPrincipal() != null ? "u:" + request.getUserPrincipal().getName() : null;
    }

    /**
     * 요청이 어떤 레지스트리 항목에 해당하는가. 우선 MVC 가 실제로 고른 핸들러 패턴(BEST_MATCHING_PATTERN — 인코딩·정규화 후)으로
     * 비교하고, 없으면 디코딩된 lookup path 로 비교한다. 원시 URI(getRequestURI) 비교는 %69 같은 인코딩으로 우회될 수 있다.
     */
    public static Route match(HttpServletRequest request) {
        Object best = request.getAttribute(org.springframework.web.servlet.HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
        if (best instanceof String pattern) {
            for (Route r : ROUTES) {
                if (r.method().equalsIgnoreCase(request.getMethod()) && r.pattern().equals(pattern)) {
                    return r;
                }
            }
            return null;
        }
        return match(request.getMethod(), LOOKUP.getLookupPathForRequest(request));
    }

    private static final org.springframework.web.util.UrlPathHelper LOOKUP = new org.springframework.web.util.UrlPathHelper();

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
        Route r = match(request);
        if (r != null && r.status() == Status.GATED && rateLimiter != null) {
            long wait = rateLimiter.tryAcquire(userKey(request));
            if (wait > 0) {
                log.warn("[QUALITY-GATE] 사용자별 평가 한도 초과 {} {} retryAfter={}s", request.getMethod(), r.pattern(), wait);
                response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
                response.setHeader("Retry-After", Long.toString(wait));
                response.setContentType(MediaType.APPLICATION_JSON_VALUE);
                response.setCharacterEncoding(StandardCharsets.UTF_8.name());
                response.getWriter().write(mapper.writeValueAsString(Map.of(
                        "success", false, "errorCode", "AI_QUALITY_RATE_LIMITED", "retryable", true, "retryAfterSeconds", wait,
                        "message", "AI 요청이 많습니다. 잠시 후 다시 시도해 주세요.")));
                return false;
            }
        }
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
