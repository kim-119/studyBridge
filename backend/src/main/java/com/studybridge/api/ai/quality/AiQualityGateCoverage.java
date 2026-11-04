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
            new Route("POST", "/api/materials/classify-before-save", Status.BLOCKED_WHEN_GATE_ON, "/api/ai/material/classify", ""),
            new Route("POST", "/api/materials/{materialId}/quiz", Status.GATED, "/api/ai/quiz",
                    "PDF_QUIZ/quiz_json(문항·보기·정답·해설·오답해설), 자료 원문 근거, 재생성 ≤2, 승인분만 저장(quality_status), 거절 시 success=false"),
            new Route("GET", "/api/materials/{materialId}/quiz", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 퀴즈는 문항·보기·해설을 가림(qualityRedacted), id·점수 기록 유지"),
            new Route("GET", "/api/materials/{materialId}/shared-quizzes", Status.GATED, "(DB)", "위와 같은 가림"),
            new Route("POST", "/api/materials/{materialId}/quiz/{quizId}/submit", Status.GATED, "(DB)",
                    "채점은 결정적(보기 id 비교). 게이트 ON + 미승인 퀴즈면 AI 해설만 가림, 점수·답안 기록 유지"),
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
            new Route("POST", "/api/materials/{materialId}/plan-analysis", Status.GATED, "/api/ai/planner/analyze",
                    "PLANNER 자료: PLANNER_COACHING/text(근거=플래너 입력), 보일 문자열 전체 평가·재생성 ≤2, 승인분만 저장(plan_analysis.quality_status), "
                            + "거절 422/평가불가 503·기존 분석 보존. PDF 자료는 결정적 PlanTextAnalyzer(AI 없음)"),
            new Route("GET", "/api/materials/{materialId}/plan-analysis", Status.GATED, "(DB)",
                    "게이트 ON: 미승인 AI 분석(planner_analysis_json 있음)은 요약·추천·항목 문구 가림(qualityRedacted), 항목 id·완료·진행률 유지"),
            new Route("POST", "/api/materials/{materialId}/recommendations", Status.GATED, "/api/ai/recommendation/*",
                    "PLANNER_COACHING/text(근거=자료 원문, allowedMaterialIds=이 자료), 후보 문구 전체 1회 평가(결정적 후보), 승인분만 저장(quality_status). "
                            + "AI 후보 경로 ON 인데 ai07 무응답(라우트 404)이면 503 RECOMMENDATION_AI_UNAVAILABLE(규칙 폴백 성공 위장 없음)"),
            new Route("GET", "/api/materials/{materialId}/recommendations", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 추천은 제목·사유·확인 사항·근거 라벨 가림(qualityRedacted)"),
            new Route("POST", "/api/materials/{materialId}/plan-recommendation", Status.GATED, "(DB plan_analysis)",
                    "게이트 ON + 미승인 AI 분석이면 추천 미노출(qualityRedacted, 저장 변경 없음). PDF 분석은 결정적 규칙 문구"),
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
            new Route("POST", "/api/mindmap/semantic-graph", Status.GATED, "/api/ai/mindmap/semantic-graph",
                    "SEMANTIC_GRAPH/graph_json(개념·별칭·설명·관계명·출처, 근거=요청 답변 원문), 재생성 ≤2, 승인분만 응답·캐시"
                            + "(Redis q1 키 + qualityStatus 표식, 레거시 키 미사용), 거절 422/평가불가 503"),
            new Route("POST", "/api/planners/{plannerId}/ai-assist", Status.GATED, "/api/ai/planner/assist",
                    "PLANNER_COACHING/text(근거=플래너 입력), 재생성 ≤2, 승인분만 저장(planner_ai_result.quality_status), 거절/평가불가=success:false·기존 보존. "
                            + "ai07 첫 호출 실패는 결정적 기본 피드백(usedFallback=true, used_fallback 저장 — AI 로 표기 안 함)"),
            new Route("GET", "/api/planners/{plannerId}/ai-result", Status.GATED, "(DB)",
                    "usedFallback 은 used_fallback 표식(폴백을 AI 로 표기하던 결함 수정). 게이트 ON: 승인·폴백 저장본만 노출, 미검증 AI 저장본은 가림(qualityRedacted)"),
            new Route("POST", "/api/planners/{plannerId}/plan-analysis", Status.GATED, "/api/ai/planner/analyze-semantic",
                    "PLANNER_COACHING/text(서술형 — ai07 일정 JSON 검사 미적용, 근거=플래너·로드맵 day 입력), AI07·결정적 폴백 모두 평가(로드맵 task 는 AI 로드맵 원문), "
                            + "재생성 ≤2, 승인분만 캐시(planners.plan_analysis_quality_status), 거절 422/평가불가 503"),
            new Route("GET", "/api/planners/{plannerId}/plan-analysis", Status.GATED, "(DB)",
                    "게이트 ON: 승인 캐시(현재 문장 규칙)만 노출, 미검증·문장 재생성 필요 캐시는 empty+qualityRedacted"),
            new Route("GET", "/api/planners/{plannerId}/schedule", Status.GATED, "/api/ai/planner/analyze-semantic",
                    "ensure(): 게이트 ON 은 승인 캐시만 재사용, 없으면 게이트 경로로 생성 — 미승인이면 422/503(시간표 미생성). 시각 계산은 결정적"),
            new Route("POST", "/api/planners/{plannerId}/schedule/pdf", Status.GATED, "/api/ai/planner/analyze-semantic",
                    "위와 같은 ensure() — 미승인이면 PDF·S3 업로드 없음"),
            new Route("POST", "/api/planners/{plannerId}/adaptive", Status.GATED, "/api/ai/planner/adaptive",
                    "PLANNER_COACHING/text(결과 본문+반영 후보 일정, 근거=플래너 항목, 일정 구조는 Spring 결정적 검증), 재생성 ≤2, 승인분만 응답·"
                            + "승인 표식(quality=APPROVED) 든 HMAC 제안 토큰 발급, 거절 422/평가불가 503"),
            new Route("POST", "/api/planners/{plannerId}/recommendations", Status.GATED, "/api/ai/recommendation/*",
                    "PLANNER_COACHING/text(근거=플래너·관련 플래너 제목), 후보 문구 1회 평가, 승인분만 저장(quality_status). AI 후보 경로 ON + ai07 무응답이면 503"),
            new Route("GET", "/api/planners/{plannerId}/recommendations", Status.GATED, "(DB)",
                    "게이트 ON: quality_status≠APPROVED 추천은 문구 가림(qualityRedacted)"),
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
            new Route("PUT", "/api/materials/{materialId}/roadmap/days/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)", "응답 = AI 로드맵 전체"),
            new Route("PUT", "/api/materials/{materialId}/roadmap/tasks/{taskId}/toggle", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "응답 = AI 로드맵 과제"),
            new Route("PATCH", "/api/plan-analysis/items/{itemId}", Status.GATED, "(DB)",
                    "완료/숨김 변경은 사용자 기록. 응답 분석은 GET 과 같은 가림(미승인 AI 분석 문구 → qualityRedacted)"),
            new Route("GET", "/api/planners/{plannerId}/next-learning", Status.EXEMPT, "(DB)",
                    "PlannerNextLearningService 확인: 응답 = 기존 플래너 id·제목·과목·날짜(planners 행)·week/day·고정 사유 문구·체크 완료 개수뿐. "
                            + "plan_analysis_item 은 완료 개수 집계에만 쓰고 항목 문구는 응답에 없음, AI 호출 없음"),
            new Route("GET", "/api/planners/{plannerId}/diagnosis", Status.EXEMPT, "(DB)",
                    "PlanDiagnosisService 확인: A/W/D·마감 창·과부하·선수관계·일정 중복 = 결정적 계산, 문자열 = 플래너 제목·할 일(todos) 문구·고정 안내문. "
                            + "plan_analysis_item 은 완료 여부 집계에만 사용, AI 호출·AI 문구 없음"),
            new Route("POST", "/api/planners/{plannerId}/adaptive/apply", Status.GATED, "(서명 제안 토큰)",
                    "게이트 ON: 토큰 HMAC 안 승인 표식(quality=APPROVED) 없으면 409 ADAPTIVE_PROPOSAL_NOT_VERIFIED(쓰기 0). "
                            + "응답·todo 제목은 결정적('[AI 학습 N분] 플래너 제목'), 날짜·분은 승인된 제안"),
            new Route("POST", "/api/recommendations/{id}/accept", Status.GATED, "(DB)",
                    "게이트 ON: 미승인 추천 승인 거부 409 RECOMMENDATION_NOT_VERIFIED(제목·사유가 새 플래너로 복사되므로), 응답 항목은 목록과 같은 가림"),
            new Route("POST", "/api/recommendations/{id}/reject", Status.GATED, "(DB)", "상태 전이만. 응답 항목은 미승인이면 문구 가림"),
            new Route("POST", "/api/recommendations/{id}/complete", Status.GATED, "(DB)", "상태 전이만. 응답 항목은 미승인이면 문구 가림"),
            new Route("GET", "/api/materials/{materialId}/study-journals", Status.BLOCKED_WHEN_GATE_ON, "(DB)",
                    "AI 판정 라벨(validationDecision/category/relationPath) — 사용자 메모 본문과 분리 필요"),
            new Route("GET", "/api/materials/{materialId}/study-journals/{journalId}", Status.BLOCKED_WHEN_GATE_ON, "(DB/S3)", "위와 같음"),
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
