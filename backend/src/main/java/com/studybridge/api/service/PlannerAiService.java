package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerAiDTO;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerAiResult;
import com.studybridge.api.repository.PlannerAiResultRepository;
import com.studybridge.api.repository.PlannerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.*;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 공부 플래너 전용 AI 서비스 — "학습 실행 관리"만 담당한다.
 *  - 자료보관함(AiIntegrationService)과 완전히 분리. 로드맵/퀴즈/문서질문/요약 없음.
 *  - 브라우저 → Spring(/api/planners/{id}/ai-assist) → FastAPI(/api/ai/planner/assist).
 *  - ai07 미배포/오류 시에도 죽지 않고 로컬 기본 피드백(graceful fallback)을 생성한다.
 *  - 사용자 원본 메모(planner.tmi)는 절대 덮어쓰지 않는다. AI 결과만 PlannerAiResult에 보관한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerAiService {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final PlannerRepository plannerRepository;
    private final PlannerAiResultRepository plannerAiResultRepository;
    private final WebClient fastApiWebClient;

    @Value("${ai.server.fastapi.planner-expand-timeout-seconds:120}")
    private long assistTimeoutSeconds;

    // ---------- 공통 ----------

    private Planner getOwnedPlanner(Long userId, Long plannerId) {
        Planner planner = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다."));
        if (!planner.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        return planner;
    }

    private String toJson(Object value) {
        if (value == null) return null;
        try { return MAPPER.writeValueAsString(value); } catch (Exception e) { return null; }
    }

    private List<String> listFromJson(String raw) {
        if (raw == null || raw.isBlank()) return Collections.emptyList();
        try { return MAPPER.readValue(raw, new TypeReference<List<String>>() {}); }
        catch (Exception e) { return Collections.emptyList(); }
    }

    @SuppressWarnings("unchecked")
    private List<String> listFromJsonKey(String raw, String key) {
        if (raw == null || raw.isBlank()) return Collections.emptyList();
        try {
            Map<String, Object> m = MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {});
            Object v = m.get(key);
            if (v instanceof List) {
                List<String> out = new ArrayList<>();
                for (Object o : (List<?>) v) if (o != null && !o.toString().isBlank()) out.add(o.toString());
                return out;
            }
        } catch (Exception ignored) { }
        return Collections.emptyList();
    }

    @SuppressWarnings("unchecked")
    private List<String> strList(Map response, String key) {
        if (response != null && response.get(key) instanceof List) {
            List<String> out = new ArrayList<>();
            for (Object o : (List<?>) response.get(key)) if (o != null && !o.toString().isBlank()) out.add(o.toString());
            return out;
        }
        return Collections.emptyList();
    }

    private String str(Map response, String key) {
        Object v = response != null ? response.get(key) : null;
        return v != null && !v.toString().isBlank() ? v.toString() : null;
    }

    private boolean isFailure(Map response) {
        return response == null || Boolean.FALSE.equals(response.get("success"));
    }

    /** ai07 FastAPI 라우트 미배포(404)/연결 불가 판별 — graceful fallback 분기용. */
    private boolean isAiRouteUnavailable(Exception e) {
        if (e instanceof org.springframework.web.reactive.function.client.WebClientResponseException) {
            return ((org.springframework.web.reactive.function.client.WebClientResponseException) e)
                    .getStatusCode().value() == 404;
        }
        String m = (e.getMessage() == null ? "" : e.getMessage()).toLowerCase();
        return m.contains("404") || m.contains("not found")
                || m.contains("connection refused") || (e.getCause() instanceof java.net.ConnectException);
    }

    // ---------- 시간 진행 상태 계산 (부족/적정/초과) ----------

    private static final Pattern NUM = Pattern.compile("(\\d+(?:\\.\\d+)?)");

    /** "3시간 30분", "90분", "1.5", "2" 등을 분 단위로 추정. 파싱 실패 시 null. */
    private Integer parseMinutes(String raw) {
        if (raw == null || raw.isBlank()) return null;
        String s = raw.trim();
        try {
            int total = 0;
            boolean matched = false;
            Matcher hm = Pattern.compile("(\\d+(?:\\.\\d+)?)\\s*(?:시간|h|hr)").matcher(s);
            if (hm.find()) { total += Math.round(Float.parseFloat(hm.group(1)) * 60); matched = true; }
            Matcher mm = Pattern.compile("(\\d+)\\s*(?:분|m|min)").matcher(s);
            if (mm.find()) { total += Integer.parseInt(mm.group(1)); matched = true; }
            if (matched) return total;
            Matcher nm = NUM.matcher(s);
            if (nm.find()) {
                float n = Float.parseFloat(nm.group(1));
                // 키워드 없는 숫자: 12 이하는 시간, 초과는 분으로 간주
                return n <= 12 ? Math.round(n * 60) : Math.round(n);
            }
        } catch (Exception ignored) { }
        return null;
    }

    private String buildTimeFeedback(Planner p) {
        Integer goal = parseMinutes(p.getGoalTime());
        Integer actual = parseMinutes(p.getNetStudyTime());
        if (goal == null && actual == null) {
            return "목표 시간과 실제 학습 시간을 입력하면 진행 상태를 확인할 수 있어요.";
        }
        if (goal == null) {
            return "실제 학습 시간은 기록됐지만 목표 시간이 없어요. 목표를 정해 비교해 보세요.";
        }
        if (actual == null) {
            return "목표 " + p.getGoalTime() + " 대비 실제 학습 시간이 아직 기록되지 않았어요.";
        }
        double ratio = goal == 0 ? 1.0 : (double) actual / goal;
        String status = ratio < 0.8 ? "부족" : (ratio > 1.2 ? "초과" : "적정");
        int pct = (int) Math.round(ratio * 100);
        String tail = ratio < 0.8 ? " 목표까지 조금 더 집중해 보세요."
                : (ratio > 1.2 ? " 충분히 학습했어요. 휴식과 복습의 균형을 맞춰보세요."
                : " 계획대로 잘 진행되고 있어요.");
        return "시간 진행 상태: " + status + " (목표 대비 " + pct + "%)." + tail;
    }

    // ---------- ai07 요청 본문 ----------

    private Map<String, Object> assistBody(Planner p) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("planner_id", p.getId());
        body.put("title", nz(p.getTitle()));
        body.put("date", buildDate(p));
        body.put("subject", nz(p.getSubject()));
        body.put("study_type", nz(p.getStudyType()));
        body.put("priority", nz(p.getPriority()));
        body.put("target_time", nz(p.getGoalTime()));
        body.put("actual_time", nz(p.getNetStudyTime()));
        body.put("deadline", nz(p.getDDay()));
        body.put("goal", nz(p.getContent()));     // 학습 목표
        body.put("todo", nz(p.getTmi()));          // 세부 할 일
        body.put("memo", nz(p.getTmi()));          // 사용자 메모 (참고만, 보존)
        body.put("completed_tasks", Collections.emptyList());
        body.put("incomplete_tasks", Collections.emptyList());
        return body;
    }

    private String nz(String s) { return s == null ? "" : s; }

    private String buildDate(Planner p) {
        if (p.getPlannerDate() != null) return p.getPlannerDate().toString();
        if (p.getYear() != null && p.getMonth() != null && p.getDay() != null) {
            return String.format("%04d-%02d-%02d", p.getYear(), p.getMonth(), p.getDay());
        }
        return "";
    }

    // ---------- 학습 실행 관리 AI 피드백 ----------

    @Transactional
    public PlannerAiDTO.AssistResponse assist(Long userId, Long plannerId) {
        Planner planner = getOwnedPlanner(userId, plannerId);

        Map response = null;
        boolean unavailable = false;
        try {
            response = fastApiWebClient.post().uri("/api/ai/planner/assist")
                    .bodyValue(assistBody(planner)).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(assistTimeoutSeconds));
        } catch (Exception e) {
            log.warn("[planner:assist:fail] plannerId={} msg={}", plannerId, e.getMessage());
            unavailable = true;
        }

        PlannerAiDTO.AssistResponse result;
        if (response == null || unavailable || isFailure(response)) {
            // graceful fallback — ai07 미배포/오류여도 로컬 기본 피드백을 만든다.
            result = buildFallback(planner);
        } else {
            result = PlannerAiDTO.AssistResponse.builder()
                    .success(true).plannerId(plannerId)
                    .aiSummary(str(response, "aiSummary"))
                    .refinedGoal(str(response, "refinedGoal"))
                    .taskBreakdown(strList(response, "taskBreakdown"))
                    .timeFeedback(str(response, "timeFeedback") != null
                            ? str(response, "timeFeedback") : buildTimeFeedback(planner))
                    .strengths(strList(response, "strengths"))
                    .concerns(strList(response, "concerns"))
                    .recommendations(strList(response, "recommendations"))
                    .nextActions(strList(response, "nextActions"))
                    .usedFallback(false)
                    .build();
        }

        save(plannerId, result);
        return result;
    }

    private void save(Long plannerId, PlannerAiDTO.AssistResponse r) {
        PlannerAiResult entity = plannerAiResultRepository.findByPlannerId(plannerId)
                .orElseGet(() -> PlannerAiResult.builder().plannerId(plannerId).build());
        entity.setAiSummary(r.getAiSummary());
        entity.setRefinedGoal(r.getRefinedGoal());
        entity.setTaskBreakdown(toJson(r.getTaskBreakdown()));
        entity.setTimeFeedback(r.getTimeFeedback());
        Map<String, Object> feedback = new LinkedHashMap<>();
        feedback.put("strengths", r.getStrengths());
        feedback.put("concerns", r.getConcerns());
        feedback.put("recommendations", r.getRecommendations());
        entity.setAiFeedback(toJson(feedback));
        entity.setNextActions(toJson(r.getNextActions()));
        plannerAiResultRepository.save(entity);
    }

    /** ai07 없이 플래너 입력값만으로 만드는 기본 피드백. */
    private PlannerAiDTO.AssistResponse buildFallback(Planner p) {
        String subject = p.getSubject() != null && !p.getSubject().isBlank() ? p.getSubject() : "학습";
        String title = p.getTitle() != null && !p.getTitle().isBlank() ? p.getTitle() : "오늘의 플래너";

        List<String> tasks = new ArrayList<>();
        if (p.getTmi() != null && !p.getTmi().isBlank()) {
            for (String t : p.getTmi().split("[\\n,]")) {
                String s = t.trim();
                if (!s.isEmpty()) tasks.add(s);
            }
        }
        if (tasks.isEmpty()) tasks.add("학습 목표를 3~5개의 작은 할 일로 나눠보세요.");

        List<String> strengths = new ArrayList<>();
        if (p.getPriority() != null && !p.getPriority().isBlank()) strengths.add("우선순위(" + p.getPriority() + ")를 정해 집중할 대상을 명확히 했어요.");
        if (p.getContent() != null && !p.getContent().isBlank()) strengths.add("학습 목표를 구체적으로 적어 방향이 분명해요.");
        if (strengths.isEmpty()) strengths.add("플래너를 작성해 학습을 계획한 점이 좋아요.");

        List<String> concerns = new ArrayList<>();
        if (p.getContent() == null || p.getContent().isBlank()) concerns.add("학습 목표가 비어 있어요. 무엇을 끝낼지 한 문장으로 적어보세요.");
        if (parseMinutes(p.getGoalTime()) == null) concerns.add("목표 학습 시간이 없어 진행 상태를 측정하기 어려워요.");
        if (concerns.isEmpty()) concerns.add("계획이 막연하면 실행이 어려워질 수 있어요. 시간 단위로 쪼개보세요.");

        List<String> recommendations = List.of(
                "가장 중요한 할 일 한 가지부터 시작하세요.",
                "25분 집중 + 5분 휴식(뽀모도로)으로 학습 시간을 관리해 보세요.",
                subject + " 학습 후 핵심 개념을 한 줄로 요약해 메모로 남기세요.");

        List<String> nextActions = List.of(
                "오늘 못 끝낸 할 일을 내일 플래너 맨 위로 옮기세요.",
                "다음 학습 전 오늘 메모를 1분간 다시 읽어보세요.");

        return PlannerAiDTO.AssistResponse.builder()
                .success(true).plannerId(p.getId())
                .aiSummary("'" + title + "' 플래너를 정리했어요. 과목은 " + subject + "이고, "
                        + "목표를 작은 할 일로 나눠 시간 안에 실행하는 데 집중하면 좋겠어요.")
                .refinedGoal(p.getContent() != null && !p.getContent().isBlank()
                        ? p.getContent() : (subject + " 핵심 내용을 이해하고 정리하기"))
                .taskBreakdown(tasks)
                .timeFeedback(buildTimeFeedback(p))
                .strengths(strengths)
                .concerns(concerns)
                .recommendations(recommendations)
                .nextActions(nextActions)
                .usedFallback(true)
                .build();
    }

    /** 저장된 AI 피드백 조회. 없으면 success=null. */
    public PlannerAiDTO.AssistResponse getAiResult(Long userId, Long plannerId) {
        getOwnedPlanner(userId, plannerId);
        return plannerAiResultRepository.findByPlannerId(plannerId)
                .filter(r -> r.getAiSummary() != null || r.getRefinedGoal() != null || r.getTaskBreakdown() != null)
                .map(r -> PlannerAiDTO.AssistResponse.builder()
                        .success(true).plannerId(plannerId)
                        .aiSummary(r.getAiSummary())
                        .refinedGoal(r.getRefinedGoal())
                        .taskBreakdown(listFromJson(r.getTaskBreakdown()))
                        .timeFeedback(r.getTimeFeedback())
                        .strengths(listFromJsonKey(r.getAiFeedback(), "strengths"))
                        .concerns(listFromJsonKey(r.getAiFeedback(), "concerns"))
                        .recommendations(listFromJsonKey(r.getAiFeedback(), "recommendations"))
                        .nextActions(listFromJson(r.getNextActions()))
                        .usedFallback(false)
                        .build())
                .orElse(PlannerAiDTO.AssistResponse.builder().success(null).plannerId(plannerId).build());
    }
}
