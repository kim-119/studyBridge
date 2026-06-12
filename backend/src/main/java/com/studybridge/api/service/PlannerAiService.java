package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerAiDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.PlannerAiResultRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.RoadmapRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.*;

/**
 * 공부 플래너 전용 AI 서비스.
 *  - 자료보관함(AiIntegrationService)과 분리. "학습 실행 관리" + 12주 로드맵 담당.
 *  - 브라우저 → Spring → FastAPI(/api/ai/planner/*) 프록시. 직접 호출 금지.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerAiService {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final PlannerRepository plannerRepository;
    private final PlannerAiResultRepository plannerAiResultRepository;
    private final RoadmapRepository roadmapRepository;
    private final WebClient fastApiWebClient;

    @Value("${ai.server.fastapi.planner-expand-timeout-seconds:120}")
    private long expandTimeoutSeconds;

    @Value("${ai.server.fastapi.roadmap-timeout-seconds:180}")
    private long roadmapTimeoutSeconds;

    // ---------- 공통 ----------

    private Planner getOwnedPlanner(Long userId, Long plannerId) {
        Planner planner = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다."));
        if (!planner.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        return planner;
    }

    private Map<String, Object> plannerInfoBody(Planner p) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("plannerId", p.getId());
        body.put("title", p.getTitle());
        body.put("subject", p.getSubject());
        body.put("content", p.getContent());
        body.put("goalTime", p.getGoalTime());
        body.put("netStudyTime", p.getNetStudyTime());
        body.put("dDay", p.getDDay());
        return body;
    }

    private String toJson(List<String> list) {
        if (list == null) return null;
        try { return MAPPER.writeValueAsString(list); } catch (Exception e) { return null; }
    }

    private List<String> fromJson(String raw) {
        if (raw == null || raw.isBlank()) return Collections.emptyList();
        try { return MAPPER.readValue(raw, new TypeReference<List<String>>() {}); }
        catch (Exception e) { return Collections.emptyList(); }
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
        return v != null ? v.toString() : null;
    }

    private boolean isFailure(Map response) {
        return response == null || Boolean.FALSE.equals(response.get("success"));
    }

    // ---------- E. 플래너 AI 확장 ----------

    @Transactional
    public PlannerAiDTO.ExpandResponse expand(Long userId, Long plannerId) {
        Planner planner = getOwnedPlanner(userId, plannerId);

        Map response;
        try {
            response = fastApiWebClient.post().uri("/api/ai/planner/expand")
                    .bodyValue(plannerInfoBody(planner)).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(expandTimeoutSeconds));
        } catch (Exception e) {
            log.error("[planner:expand:fail] plannerId={} msg={}", plannerId, e.getMessage());
            throw new RuntimeException("플래너 AI 확장 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
        }
        if (isFailure(response)) {
            return PlannerAiDTO.ExpandResponse.builder()
                    .success(false).plannerId(plannerId)
                    .errorCode(str(response, "errorCode"))
                    .message(str(response, "message") != null ? str(response, "message") : "플래너 확장에 실패했습니다.")
                    .build();
        }

        List<String> todos = strList(response, "expandedTodos");
        List<String> order = strList(response, "studyOrder");
        List<String> risks = strList(response, "riskPoints");
        List<String> checkpoints = strList(response, "todayCheckpoints");
        List<String> questions = strList(response, "aiQuestions");
        List<String> reflections = strList(response, "reflectionPrompts");
        String goal = str(response, "expandedGoal");
        String estimated = str(response, "estimatedTime");

        PlannerAiResult result = plannerAiResultRepository.findByPlannerId(plannerId)
                .orElseGet(() -> PlannerAiResult.builder().plannerId(plannerId).build());
        result.setExpandedGoal(goal);
        result.setExpandedTodo(toJson(todos));
        result.setEstimatedTime(estimated);
        result.setStudyStrategy(toJson(order));
        result.setRiskPoints(toJson(risks));
        result.setTodayCheckpoints(toJson(checkpoints));
        result.setAiQuestions(toJson(questions));
        result.setReflectionPrompts(toJson(reflections));
        plannerAiResultRepository.save(result);

        return PlannerAiDTO.ExpandResponse.builder()
                .success(true).plannerId(plannerId)
                .expandedGoal(goal)
                .expandedTodos(todos)
                .estimatedTime(estimated)
                .studyOrder(order)
                .riskPoints(risks)
                .todayCheckpoints(checkpoints)
                .aiQuestions(questions)
                .reflectionPrompts(reflections)
                .build();
    }

    public PlannerAiDTO.ExpandResponse getAiResult(Long userId, Long plannerId) {
        getOwnedPlanner(userId, plannerId);
        return plannerAiResultRepository.findByPlannerId(plannerId)
                .map(r -> PlannerAiDTO.ExpandResponse.builder()
                        .success(true).plannerId(plannerId)
                        .expandedGoal(r.getExpandedGoal())
                        .expandedTodos(fromJson(r.getExpandedTodo()))
                        .estimatedTime(r.getEstimatedTime())
                        .studyOrder(fromJson(r.getStudyStrategy()))
                        .riskPoints(fromJson(r.getRiskPoints()))
                        .todayCheckpoints(fromJson(r.getTodayCheckpoints()))
                        .aiQuestions(fromJson(r.getAiQuestions()))
                        .reflectionPrompts(fromJson(r.getReflectionPrompts()))
                        .build())
                .orElse(PlannerAiDTO.ExpandResponse.builder().success(null).plannerId(plannerId).build());
    }

    // ---------- F. 플래너 기반 12주 로드맵 ----------

    @Transactional
    public PlannerAiDTO.RoadmapResponse generateRoadmap(Long userId, Long plannerId) {
        Planner planner = getOwnedPlanner(userId, plannerId);

        Map response;
        try {
            response = fastApiWebClient.post().uri("/api/ai/planner/roadmap")
                    .bodyValue(plannerInfoBody(planner)).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(roadmapTimeoutSeconds));
        } catch (Exception e) {
            log.error("[planner:roadmap:fail] plannerId={} msg={}", plannerId, e.getMessage());
            throw new RuntimeException("플래너 로드맵 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
        }
        if (isFailure(response)) {
            return PlannerAiDTO.RoadmapResponse.builder()
                    .success(false).plannerId(plannerId)
                    .errorCode(str(response, "errorCode"))
                    .message(str(response, "message") != null ? str(response, "message") : "로드맵 생성에 실패했습니다.")
                    .build();
        }

        List<PlannerAiDTO.Week> weeks = parseWeeks(response.get("weeks"));
        String title = str(response, "title") != null ? str(response, "title")
                : ((planner.getSubject() != null ? planner.getSubject() : "학습") + " 12주 로드맵");

        // 기존 플래너 로드맵이 있으면 교체 (orphanRemoval로 step/task 정리)
        Roadmap roadmap = roadmapRepository.findFirstByPlannerIdOrderByRoadmapIdDesc(plannerId)
                .orElseGet(() -> Roadmap.builder().userId(userId).sourceType("PLANNER").plannerId(plannerId).build());
        roadmap.setUserId(userId);
        roadmap.setSourceType("PLANNER");
        roadmap.setPlannerId(plannerId);
        roadmap.setMaterial(null);
        roadmap.setTitle(title);
        roadmap.setGoal(planner.getSubject());
        roadmap.getSteps().clear();

        int stepOrder = 1;
        for (PlannerAiDTO.Week w : weeks) {
            RoadmapStep step = RoadmapStep.builder()
                    .roadmap(roadmap)
                    .stepOrder(stepOrder++)
                    .title(w.getTitle() != null ? w.getTitle() : (w.getWeek() + "주차"))
                    .description(w.getGoal())
                    .build();
            int taskOrder = 1;
            for (String t : (w.getTasks() != null ? w.getTasks() : Collections.<String>emptyList())) {
                step.getTasks().add(RoadmapTask.builder()
                        .step(step).taskOrder(taskOrder++)
                        .content(t.length() > 1000 ? t.substring(0, 1000) : t)
                        .isCompleted(false).build());
            }
            roadmap.getSteps().add(step);
        }
        roadmap = roadmapRepository.save(roadmap);

        return PlannerAiDTO.RoadmapResponse.builder()
                .success(true).plannerId(plannerId).roadmapId(roadmap.getRoadmapId())
                .title(title).weeks(weeks).build();
    }

    public PlannerAiDTO.RoadmapResponse getRoadmap(Long userId, Long plannerId) {
        getOwnedPlanner(userId, plannerId);
        return roadmapRepository.findFirstByPlannerIdOrderByRoadmapIdDesc(plannerId)
                .map(roadmap -> {
                    List<PlannerAiDTO.Week> weeks = new ArrayList<>();
                    roadmap.getSteps().stream()
                            .sorted(Comparator.comparing(RoadmapStep::getStepOrder))
                            .forEach(step -> {
                                List<String> tasks = new ArrayList<>();
                                step.getTasks().forEach(t -> tasks.add(t.getContent()));
                                weeks.add(PlannerAiDTO.Week.builder()
                                        .week(step.getStepOrder())
                                        .title(step.getTitle())
                                        .goal(step.getDescription())
                                        .tasks(tasks).build());
                            });
                    return PlannerAiDTO.RoadmapResponse.builder()
                            .success(true).plannerId(plannerId).roadmapId(roadmap.getRoadmapId())
                            .title(roadmap.getTitle()).weeks(weeks).build();
                })
                .orElse(PlannerAiDTO.RoadmapResponse.builder().success(null).plannerId(plannerId).build());
    }

    @SuppressWarnings("unchecked")
    private List<PlannerAiDTO.Week> parseWeeks(Object weeksRaw) {
        List<PlannerAiDTO.Week> out = new ArrayList<>();
        if (!(weeksRaw instanceof List)) return out;
        int idx = 1;
        for (Object o : (List<Object>) weeksRaw) {
            if (!(o instanceof Map)) continue;
            Map<String, Object> w = (Map<String, Object>) o;
            List<String> tasks = new ArrayList<>();
            if (w.get("tasks") instanceof List) {
                for (Object t : (List<?>) w.get("tasks")) if (t != null && !t.toString().isBlank()) tasks.add(t.toString());
            }
            out.add(PlannerAiDTO.Week.builder()
                    .week(w.get("week") instanceof Number ? ((Number) w.get("week")).intValue() : idx)
                    .title(w.get("title") != null ? w.get("title").toString() : idx + "주차")
                    .goal(w.get("goal") != null ? w.get("goal").toString() : "")
                    .tasks(tasks).build());
            idx++;
        }
        return out;
    }
}
