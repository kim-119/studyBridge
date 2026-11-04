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
 *  GET /api/materials/{materialId}/study-note(생성 시점 게이트 + 미승인 가림, GATED)로만 노출된다.
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
            new Route("POST", "/api/agent-rooms/{roomId}/chat", Status.GATED, "/api/ai/multi-chat",
                    "non-stream: 응답 전체를 QualityStreamGate all_complete 규칙(answers/messages 메시지 단위, 부가 필드 묶음)으로 평가 → 승인분만 응답·DB/Redis(APPROVED), 전부 미승인=AI_QUALITY_REJECTED/UNAVAILABLE"),
            new Route("POST", "/api/learning-mate/chat", Status.GATED, "/api/ai/multi-chat",
                    "STUDYMATE_*(모드)/agent_message, 평탄화 답변 전체 평가, 재생성 ≤2, 승인분만 응답(저장 없음), 거절/평가불가=success:false"),
            // 그룹스터디
            new Route("POST", "/api/groups/{groupId}/chats/stream", Status.GATED, "/api/ai/multi-chat/stream",
                    "그룹 AI 봇: QualityStreamGate(GROUP_STUDY_MESSAGE, 참여자 제약)를 누적·DB 영속화 앞에, non-stream 폴백도 게이트 경유, 승인분만 저장(quality_status)"),
            new Route("GET", "/api/groups/{groupId}/chats/history", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 인 AI 행 본문 가림(qualityRedacted), 사용자 메시지 유지. 그룹 AI 답변은 Redis 캐시 미사용"),
            new Route("POST", "/api/groups/{groupId}/materials/{materialId}/quiz", Status.GATED, "/api/ai/quiz/generate",
                    "PDF_QUIZ/quiz_json(제목·문항·보기·정답·해설), 근거=원본 파일 결정적 추출(documentId 범위), 재생성 ≤2, 승인분만 저장(quality_status), 거절 422/평가불가 503"),
            new Route("GET", "/api/groups/{groupId}/quizzes", Status.GATED, "(DB)", "게이트 ON: quality_status≠APPROVED 퀴즈는 AI 제목을 가림(qualityRedacted)"),
            new Route("POST", "/api/groups/{groupId}/materials/upload-quiz", Status.GATED, "/api/ai/quiz/generate",
                    "그룹 자료 업로드+퀴즈 생성: 위와 같은 게이트, 거절/평가불가면 자료 행 롤백+S3 삭제 후 422/503(성공 위장 없음)"),
            new Route("POST", "/api/groups/{id}/screen-ai/analyze", Status.GATED, "/api/ai/vision/analyze",
                    "VISION_CAPTION/vision_text(근거 없음 — ai07 판독 근거 미반환), 재생성 ≤2(근거 부재 거절은 재생성 안 함), 승인분만 응답, 거절 422/평가불가 503 SCREEN_AI_QUALITY_*"),
            // 자료보관함(PDF)
            new Route("GET", "/api/materials/{materialId}/summary", Status.GATED, "/api/ai/summary",
                    "PDF_SUMMARY, 재생성 ≤2, 승인분만 저장, 미승인 캐시 미노출"),
            new Route("POST", "/api/materials/classify-before-save", Status.GATED, "/api/ai/material/classify",
                    "GENERAL_EXPLANATION/text: 노출 문자열 전부(안내 문구·판단 근거 reason=LLM 자유 텍스트·선택지 라벨), 근거=분류기 입력(파일명·MIME·제목·키워드),"
                            + " 재분류 ≤2, 승인분만 응답, 거절=success:false(추천 미포함), ai07 장애=기존 Spring 고정 폴백(AI 문구 없음)"),
            new Route("POST", "/api/materials/{materialId}/quiz", Status.GATED, "/api/ai/quiz",
                    "PDF_QUIZ/quiz_json(문항·보기·정답·해설·오답해설), 자료 원문 근거, 재생성 ≤2, 승인분만 저장(quality_status), 거절 시 success=false"),
            new Route("GET", "/api/materials/{materialId}/quiz", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 퀴즈는 문항·보기·해설을 가림(qualityRedacted), id·점수 기록 유지"),
            new Route("GET", "/api/materials/{materialId}/shared-quizzes", Status.GATED, "(DB)", "위와 같은 가림"),
            new Route("POST", "/api/materials/{materialId}/quiz/{quizId}/submit", Status.GATED, "(DB)",
                    "채점은 결정적(보기 id 비교). 게이트 ON + 미승인 퀴즈면 AI 해설만 가림, 점수·답안 기록 유지"),
            new Route("POST", "/api/materials/{materialId}/question", Status.GATED, "/api/ai/question",
                    "PDF_QA(질문 관련 자료 원문 근거), 재생성 ≤2, 승인 답변만 저장(quality_status), 라우터 LLM 문구→고정 문구, BLOCKED 파이프라인 미실행"),
            new Route("GET", "/api/materials/{materialId}/roadmap", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate",
                    "캐시+생성. Spring 분할 게이트 연결 완료(PLANNER_COACHING/plan_json 주차 세그먼트, 진행 상태 제외 체크섬) — ai07 rqg-1.0.0 check_plan 이"
                            + " 세그먼트 객체를 PLAN_EMPTY(HARD)로 항상 거절해 승인 불가 → ai07 계약 변경 후 GATED"),
            new Route("POST", "/api/materials/{materialId}/roadmap/regenerate", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/roadmap/generate",
                    "위와 같음(Spring 연결 완료, ai07 계약 대기)"),
            new Route("POST", "/api/materials/{materialId}/keywords/define", Status.GATED, "/api/ai/keyword/define",
                    "GENERAL_EXPLANATION/text(정의·중요성·예시·관련 개념·출처·링크 전부), 근거=자료 원문(클라이언트 context 아님), 재생성 ≤2,"
                            + " 승인분만 응답(저장 없음), 거절=success:false+errorCode+retryable"),
            new Route("GET", "/api/materials/{materialId}/feedback", Status.GATED, "/api/ai/feedback",
                    "GENERAL_EXPLANATION(자료 원문 근거), 재생성 ≤2, 승인분만 저장(quality_status), 미승인 저장본 미노출, 거절 쿨다운 120s"),
            new Route("POST", "/api/materials/{materialId}/feedback/regenerate", Status.GATED, "/api/ai/feedback", "위와 같은 게이트"),
            new Route("GET", "/api/materials/{materialId}/study-note", Status.GATED, "/api/ai/major-analysis/note",
                    "업로드 후 백그라운드 생성 시 분할 평가(GENERAL_EXPLANATION/text, 근거=자료 원문 페이지별) 재생성 ≤2 → 승인분만 저장(quality_status)."
                            + " GET: 미승인/레거시 행은 AI 필드 가림(status UNVERIFIED, qualityRedacted)"),
            new Route("POST", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/planner/analyze", ""),
            new Route("GET", "/api/materials/{materialId}/plan-analysis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", ""),
            new Route("POST", "/api/materials/{materialId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/recommendation/*", ""),
            new Route("GET", "/api/materials/{materialId}/recommendations", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "저장된 AI 추천 재노출(Phase C 추가)"),
            new Route("POST", "/api/materials/{materialId}/plan-recommendation", Status.BLOCKED_WHEN_GATE_ON, "(DB plan_analysis)",
                    "저장된 AI 계획 분석 기반 추천 재노출(Phase C 추가)"),
            new Route("POST", "/api/materials/{materialId}/study-journals", Status.GATED, "/api/ai/study-journal/validate",
                    "판정(ACCEPT/수정요청/차단)은 저장 게이트로 유지, 노출 AI 문구(연결 경로·사유·제안)만 GENERAL_EXPLANATION 평가(근거=메모+자료 원문,"
                            + " 재생성 없음 — 재검증은 판정을 바꿈). 미승인: 경로 미저장, 거절 사유·제안은 분류별 고정 문구(qualityRedacted)"),
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
            new Route("GET", "/api/materials/{materialId}/quiz/{quizId}/score", Status.GATED, "(DB/Redis)",
                    "채점 결과 results[].explanation = AI 해설 → 게이트 ON + 미승인 퀴즈면 해설만 가림(submit 과 같은 grade)"),
            new Route("GET", "/api/groups/{groupId}/quiz/session", Status.GATED, "(DB)",
                    "현재 문항 = 저장된 AI 퀴즈 문항·보기 → 게이트 ON + 미승인 퀴즈면 제목·문항·보기 가림(REST 스냅샷만, STOMP 브로드캐스트 별도)"),
            new Route("GET", "/api/review-notes/{id}/download", Status.GATED, "(DB)", "게이트 ON: 오답노트 본문 미승인이면 PDF URL 미발급(가림 표식)"),
            new Route("PATCH", "/api/review-notes/{id}/memo", Status.GATED, "(DB)", "응답 ReviewNoteDTO 는 목록·상세와 같은 가림(메모는 사용자 데이터)"),
            new Route("POST", "/api/review-notes/{id}/retry/submit", Status.EXEMPT, "(DB)",
                    "응답 = 사용자 재풀이 기록(index/userAnswer/correct/answeredAt)·개수뿐, AI 생성 문자열 없음(정답 대조는 원래 문제의 정답)"),
            new Route("PUT", "/api/materials/{materialId}/roadmap/days/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "응답 = AI 로드맵 전체. 게이트 ON 가림(미승인·체크섬 불일치, 진행 상태 유지) 연결 완료 — 승인 로드맵이 생길 수 없는 동안 GET 과 함께 BLOCKED"),
            new Route("PUT", "/api/materials/{materialId}/roadmap/tasks/{taskId}/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "응답 = AI 로드맵 과제(레거시 steps/tasks). 게이트 ON 이면 과제 문구 가림 연결 완료 — 위와 같은 이유로 BLOCKED"),
            new Route("PATCH", "/api/plan-analysis/items/{itemId}", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 계획 분석"),
            new Route("GET", "/api/planners/{plannerId}/next-learning", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "결정적 규칙이나 항목명 = AI 계획 분석 결과"),
            new Route("GET", "/api/planners/{plannerId}/diagnosis", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "AI 계획 분석 기반 진단"),
            new Route("POST", "/api/planners/{plannerId}/adaptive/apply", Status.BLOCKED_WHEN_GATE_ON, "(서명 제안 토큰)",
                    "AI 적응형 제안 적용 — 응답·생성 todo 제목이 AI 제안"),
            new Route("POST", "/api/recommendations/{id}/accept", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("POST", "/api/recommendations/{id}/reject", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("POST", "/api/recommendations/{id}/complete", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 추천 항목"),
            new Route("GET", "/api/materials/{materialId}/study-journals", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 면 AI 연결 경로(relationPath) 가림(qualityRedacted), 판정 라벨은 허용 enum 값만. 메모 본문은 사용자 데이터"),
            new Route("GET", "/api/materials/{materialId}/study-journals/{journalId}", Status.GATED, "(DB/S3)", "위와 같음(S3 메모 본문 유지)"),
            new Route("GET", "/api/materials/{materialId}", Status.GATED, "(DB/S3)",
                    "context=review-note 로 오답노트 자료 상세를 열 때 AI 해설 PDF URL·본문 사본 노출 → 게이트 ON + 원 노트 미승인이면 가림"
                            + "(qualityRedacted). 일반 자료는 AI 필드 없음(ai07 리뷰가 찾은 우회 경로)"));

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

    /** 조회만 하는 GET(저장본 가림)은 평가를 일으키지 않는다 → 한도 대상 아님. 캐시 없으면 생성하는 GET 만 예외로 센다. */
    static final java.util.Set<String> GENERATING_GETS = java.util.Set.of(
            "/api/materials/{materialId}/summary", "/api/materials/{materialId}/feedback", "/api/materials/{materialId}/roadmap");

    static boolean consumesEvaluation(Route r) {
        return !"GET".equalsIgnoreCase(r.method()) || GENERATING_GETS.contains(r.pattern());
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
        if (r != null && r.status() == Status.GATED && rateLimiter != null && consumesEvaluation(r)) {
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
