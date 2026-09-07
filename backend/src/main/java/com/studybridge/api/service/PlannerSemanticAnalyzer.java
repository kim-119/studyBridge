package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerSemanticDTO;
import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.PlannerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.*;

/**
 * 플래너 "AI 계획 분석" 시맨틱 분석기.
 *  - 실제 플래너/로드맵 DB 데이터를 {@link PlannerAnalysisContext} 로 구조화해 AI07(/api/ai/planner/analyze-semantic)에 전달.
 *  - AI 응답을 검증하고, task 별 권장시간은 AI를 그대로 신뢰하지 않고 {@link PlannerTimeAllocator} 로 targetMinutes 에 맞춰 결정적 정규화.
 *  - AI07 장애/오형식 시에도 실제 데이터 기반 결정적 폴백으로 동일 구조를 반환(플래너 열람은 절대 막지 않는다).
 *  - 결과는 planner.planAnalysisJson 에 캐시되어 시간표/PDF 생성 시 재사용된다(시간 변경 시 AI 재호출 없음).
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerSemanticAnalyzer {

    private static final String SEMANTIC_PATH = "/api/ai/planner/analyze-semantic";

    private final PlannerAnalysisContext context;
    private final PlannerTimeAllocator allocator;
    private final PlannerRepository planners;
    private final WebClient fastApiWebClient;
    private final ObjectMapper json;

    @Value("${ai.server.fastapi.planner-expand-timeout-seconds:120}")
    private long timeoutSeconds;

    // 타입별 기본 학습시간 가중치(AI 제안 시간이 없을 때 사용). 실습/분석에 더 큰 비중.
    private static final Map<TaskType, Integer> TYPE_WEIGHT = Map.of(
            TaskType.CONCEPT, 10, TaskType.PRACTICE, 15, TaskType.ANALYSIS, 13,
            TaskType.COMPARISON, 11, TaskType.REVIEW, 8, TaskType.OUTPUT, 13);
    private static final Map<TaskType, String> TYPE_LABEL = Map.of(
            TaskType.CONCEPT, "개념", TaskType.PRACTICE, "실습", TaskType.ANALYSIS, "분석",
            TaskType.COMPARISON, "비교", TaskType.REVIEW, "복습", TaskType.OUTPUT, "산출물");

    // ---------------- public API ----------------

    /** 분석 생성/재생성. 소유권 검증 → 구조화 → AI07 → 검증/정규화 → 캐시. */
    @Transactional
    public AnalysisResponse analyze(Long userId, Long plannerId) {
        Planner planner = context.owned(userId, plannerId);
        Request req = context.build(planner);                 // 비어 있으면 PlanAnalysisException 발생
        String fingerprint = context.fingerprint(req);

        JsonNode ai = callAi(req);
        boolean fromAi = ai != null && !ai.path("tasks").isMissingNode();

        List<Task> tasks = buildTasks(req, ai);
        Integer target = req.getTargetMinutes();
        boolean estimated = target == null;
        List<Integer> minutes = allocator.normalize(weights(tasks, ai), target);
        int total = 0;
        for (int i = 0; i < tasks.size(); i++) { tasks.get(i).setRecommendedMinutes(minutes.get(i)); total += minutes.get(i); }

        AnalysisResponse resp = AnalysisResponse.builder()
                .plannerId(planner.getId())
                .title(req.getTitle())
                .subject(blankToNull(req.getSubject()))
                .sourceType(req.getSourceType())
                .learningGoal(blankToNull(req.getLearningGoal()))
                .targetMinutes(estimated ? total : target)
                .targetMinutesEstimated(estimated)
                .totalRecommendedMinutes(total)
                .summary(summary(req, ai, total))
                .goalAlignment(goalAlignment(req, ai))
                .prerequisites(prerequisites(req, ai))
                .tasks(tasks)
                .flow(flow(tasks))
                .checklistProgress(progress(req))
                .warnings(strings(ai == null ? null : ai.get("warnings")))
                .sourceFingerprint(fingerprint)
                .stale(false)
                .empty(false)
                .aiSource(fromAi ? "AI07" : "FALLBACK")
                .build();

        try { planner.setPlanAnalysisJson(json.writeValueAsString(resp)); planners.save(planner); }
        catch (Exception e) { log.warn("[planner:semantic] 캐시 저장 실패 plannerId={}: {}", plannerId, e.getMessage()); }

        log.info("[planner:semantic] plannerId={} sourceType={} tasks={} target={} total={} aiSource={}",
                plannerId, req.getSourceType(), tasks.size(), target, total, resp.getAiSource());
        return resp;
    }

    /** 캐시된 분석 조회(없으면 empty). 플래너 의미가 바뀌면 stale=true 로 재분석을 안내. */
    public AnalysisResponse get(Long userId, Long plannerId) {
        Planner planner = context.owned(userId, plannerId);
        AnalysisResponse cached = read(planner.getPlanAnalysisJson());
        if (cached == null) {
            return AnalysisResponse.builder().plannerId(plannerId).title(planner.getTitle()).empty(true).build();
        }
        try { cached.setStale(!Objects.equals(cached.getSourceFingerprint(), context.fingerprint(context.build(planner)))); }
        catch (Exception ignored) { /* build 실패(빈 플래너 등)여도 캐시는 그대로 반환 */ }
        return cached;
    }

    /** 시간표/PDF 생성이 사용할 최신 분석. 캐시가 없으면 즉시 1회 분석해 생성한다. */
    @Transactional
    public AnalysisResponse ensure(Long userId, Long plannerId) {
        Planner planner = context.owned(userId, plannerId);
        AnalysisResponse cached = read(planner.getPlanAnalysisJson());
        if (cached != null && cached.getTasks() != null && !cached.getTasks().isEmpty()) return cached;
        return analyze(userId, plannerId);
    }

    // ---------------- AI07 호출 ----------------

    private JsonNode callAi(Request req) {
        try {
            Object body = json.convertValue(req, Object.class);
            String raw = fastApiWebClient.post().uri(SEMANTIC_PATH)
                    .bodyValue(body)
                    .retrieve()
                    .bodyToMono(String.class)
                    .timeout(Duration.ofSeconds(Math.max(15, timeoutSeconds)))
                    .block();
            if (raw == null || raw.isBlank()) return null;
            JsonNode node = json.readTree(raw);
            if (node.path("success").asBoolean(true)) return node;
            return null;
        } catch (Exception e) {
            log.warn("[planner:semantic] AI07 호출 실패 → 결정적 폴백: {}", e.getMessage());
            return null;
        }
    }

    // ---------------- task 조립(순서/식별자는 실제 플래너가 authoritative, prose 는 AI 우선) ----------------

    private List<Task> buildTasks(Request req, JsonNode ai) {
        Map<String, JsonNode> byId = new HashMap<>();
        List<JsonNode> aiTasks = new ArrayList<>();
        if (ai != null && ai.get("tasks") != null && ai.get("tasks").isArray()) {
            ai.get("tasks").forEach(aiTasks::add);
            for (JsonNode t : aiTasks) if (t.hasNonNull("id")) byId.put(t.get("id").asText(), t);
        }
        List<InputItem> inputs = req.getDetailTasks() == null ? List.of() : req.getDetailTasks();
        List<Task> out = new ArrayList<>();
        for (int i = 0; i < inputs.size(); i++) {
            InputItem in = inputs.get(i);
            JsonNode a = byId.getOrDefault(in.getId(), i < aiTasks.size() ? aiTasks.get(i) : null);
            TaskType type = a != null && a.hasNonNull("type") ? parseType(a.get("type").asText(), in.getTitle())
                    : classify(in.getTitle());
            Task t = new Task();
            t.setId(in.getId());
            t.setOrder(i);
            t.setTitle(in.getTitle());
            t.setDescription(blankToNull(in.getDescription()));
            t.setType(type);
            t.setGoalAlignment(taskAlignment(a, in.getTitle(), type, req.getLearningGoal()));
            t.setWhyImportant(text(a, "whyImportant", whyImportant(type, in.getTitle())));
            t.setPrerequisites(taskPrereqs(a, req, type));
            t.setLearningSequence(sequence(a, type));
            out.add(t);
        }
        return out;
    }

    /** 정규화 입력 가중치: AI 제안 분(있고 유효)>0 우선, 없으면 타입 가중치. */
    private List<Integer> weights(List<Task> tasks, JsonNode ai) {
        Map<String, Integer> aiMin = new HashMap<>();
        if (ai != null && ai.get("tasks") != null && ai.get("tasks").isArray()) {
            for (JsonNode t : ai.get("tasks")) {
                int m = t.path("recommendedMinutes").asInt(0);
                if (t.hasNonNull("id") && m > 0) aiMin.put(t.get("id").asText(), m);
            }
        }
        List<Integer> w = new ArrayList<>();
        for (Task t : tasks) {
            Integer m = aiMin.get(t.getId());
            w.add(m != null && m > 0 ? m : TYPE_WEIGHT.getOrDefault(t.getType(), 10));
        }
        return w;
    }

    // ---------------- 시맨틱 필드(AI 우선, 실데이터 기반 결정적 폴백) ----------------

    private String summary(Request req, JsonNode ai, int total) {
        String s = text(ai, "summary", null);
        if (s != null) return s;
        int n = req.getDetailTasks() == null ? 0 : req.getDetailTasks().size();
        String goal = shortGoal(req.getLearningGoal(), req.getTitle());
        return String.format("‘%s’ 학습은 %d개의 활동으로 구성되어 있으며, 총 %d분을 목표로 %s에 초점을 둡니다.",
                req.getTitle(), n, total, goal);
    }

    private PlanGoalAlignment goalAlignment(Request req, JsonNode ai) {
        PlanGoalAlignment g = new PlanGoalAlignment();
        JsonNode a = ai == null ? null : ai.get("goalAlignment");
        g.setLevel(a != null && a.hasNonNull("level") ? parseLevel(a.get("level").asText()) : Level.MEDIUM);
        String goal = shortGoal(req.getLearningGoal(), req.getTitle());
        g.setSummary(text(a, "summary", "현재 학습 활동 대부분이 " + goal + " 이해와 연결되어 있습니다."));
        g.setReason(text(a, "reason",
                "구성된 활동이 오늘의 학습 목표를 향해 순차적으로 배치되어 있어 전반적인 정합성은 양호합니다."));
        g.setIssues(strings(a == null ? null : a.get("issues")));
        return g;
    }

    private GoalAlignment taskAlignment(JsonNode a, String title, TaskType type, String goal) {
        GoalAlignment g = new GoalAlignment();
        JsonNode ga = a == null ? null : a.get("goalAlignment");
        g.setLevel(ga != null && ga.hasNonNull("level") ? parseLevel(ga.get("level").asText()) : defaultLevel(type));
        g.setReason(text(ga, "reason",
                "현재 목표(" + shortGoal(goal, title) + ")와 직접적으로 연결되는 활동입니다."));
        return g;
    }

    private List<Prerequisite> prerequisites(Request req, JsonNode ai) {
        List<Prerequisite> fromAi = prereqNodes(ai == null ? null : ai.get("prerequisites"));
        if (!fromAi.isEmpty()) return fromAi;
        List<Prerequisite> out = new ArrayList<>();
        for (String c : safe(req.getCoreConcepts())) {
            out.add(new Prerequisite(c, "학습 전 미리 확인하면 오늘 내용을 이해하기 쉽습니다.", false));
        }
        return out;
    }

    private List<Prerequisite> taskPrereqs(JsonNode a, Request req, TaskType type) {
        List<Prerequisite> fromAi = prereqNodes(a == null ? null : a.get("prerequisites"));
        if (!fromAi.isEmpty()) return fromAi;
        // 실데이터가 없으면 추측하지 않는다(로드맵 핵심개념은 상위 prerequisites 에만 노출).
        return List.of();
    }

    private List<Prerequisite> prereqNodes(JsonNode node) {
        List<Prerequisite> out = new ArrayList<>();
        if (node != null && node.isArray()) {
            for (JsonNode p : node) {
                String name = p.isTextual() ? p.asText() : text(p, "name", null);
                if (name == null || name.isBlank()) continue;
                out.add(new Prerequisite(name, text(p, "reason", "먼저 알아두면 좋은 개념입니다."), false));
            }
        }
        return out;
    }

    private List<String> sequence(JsonNode a, TaskType type) {
        List<String> fromAi = strings(a == null ? null : a.get("learningSequence"));
        if (!fromAi.isEmpty()) return fromAi;
        return switch (type) {
            case PRACTICE -> List.of("입력 데이터 확인", "핵심 코드·절차 따라하기", "직접 실행", "결과 확인", "막힌 부분 정리");
            case ANALYSIS -> List.of("결과·데이터 확인", "분석 기준 세우기", "분석 수행", "의미 해석", "요약 정리");
            case COMPARISON -> List.of("비교 대상 정리", "비교 기준 세우기", "항목별 비교", "차이 정리");
            case OUTPUT -> List.of("필요 내용 정리", "초안 작성", "검토·보완", "마무리");
            default -> List.of();
        };
    }

    private String whyImportant(TaskType type, String title) {
        return switch (type) {
            case PRACTICE -> "개념을 직접 손으로 확인하며 실제 적용 감각을 익히는 핵심 활동입니다.";
            case ANALYSIS -> "결과를 해석하는 힘을 길러 학습 내용을 실전에 연결하는 단계입니다.";
            case COMPARISON -> "유사 개념의 차이를 명확히 구분해 혼동을 줄입니다.";
            case REVIEW -> "배운 내용을 정리·복습해 장기 기억으로 굳히는 단계입니다.";
            case OUTPUT -> "학습 결과를 산출물로 정리해 이해도를 스스로 검증합니다.";
            default -> "이후 활동의 토대가 되는 기본 개념을 다지는 단계입니다.";
        };
    }

    private List<FlowNode> flow(List<Task> tasks) {
        List<FlowNode> out = new ArrayList<>();
        for (Task t : tasks) out.add(FlowNode.builder()
                .taskId(t.getId()).title(t.getTitle()).type(t.getType())
                .recommendedMinutes(t.getRecommendedMinutes()).build());
        return out;
    }

    private ChecklistProgress progress(Request req) {
        List<InputItem> cl = req.getChecklist() == null ? List.of() : req.getChecklist();
        int total = cl.size();
        int done = (int) cl.stream().filter(i -> Boolean.TRUE.equals(i.getCompleted())).count();
        int pct = total == 0 ? 0 : (int) Math.round(done * 100.0 / total);
        return ChecklistProgress.builder().total(total).completed(done).percent(pct).build();
    }

    // ---------------- helpers ----------------

    static String typeLabel(TaskType type) { return TYPE_LABEL.getOrDefault(type, "학습"); }

    private TaskType classify(String title) { return parseType(null, title); }

    private TaskType parseType(String aiType, String title) {
        if (aiType != null) {
            try { return TaskType.valueOf(aiType.trim().toUpperCase()); } catch (Exception ignored) {}
        }
        String t = title == null ? "" : title;
        if (containsAny(t, "실습", "코드", "구현", "실행", "작성", "풀이", "연습")) return TaskType.PRACTICE;
        if (containsAny(t, "분석", "결과", "해석", "평가")) return TaskType.ANALYSIS;
        if (containsAny(t, "비교", "대조", "차이")) return TaskType.COMPARISON;
        if (containsAny(t, "복습", "정리", "요약", "점검", "회고")) return TaskType.REVIEW;
        if (containsAny(t, "산출물", "제출", "보고서", "발표")) return TaskType.OUTPUT;
        return TaskType.CONCEPT;
    }

    private Level defaultLevel(TaskType type) {
        return switch (type) { case PRACTICE, ANALYSIS -> Level.HIGH; case REVIEW -> Level.MEDIUM; default -> Level.MEDIUM; };
    }

    private Level parseLevel(String v) {
        if (v == null) return Level.MEDIUM;
        try { return Level.valueOf(v.trim().toUpperCase()); } catch (Exception e) { return Level.MEDIUM; }
    }

    private AnalysisResponse read(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try { return json.readValue(raw, AnalysisResponse.class); }
        catch (Exception e) { log.warn("[planner:semantic] 캐시 역직렬화 실패: {}", e.getMessage()); return null; }
    }

    private boolean containsAny(String s, String... keys) { for (String k : keys) if (s.contains(k)) return true; return false; }
    private String text(JsonNode n, String key, String fallback) {
        if (n != null && n.hasNonNull(key) && n.get(key).isValueNode()) {
            String v = n.get(key).asText().trim();
            if (!v.isEmpty()) return v;
        }
        return fallback;
    }
    private List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        if (n != null && n.isArray()) for (JsonNode v : n) if (v.isTextual() && !v.asText().isBlank()) out.add(v.asText().trim());
        return out;
    }
    private <T> List<T> safe(List<T> l) { return l == null ? List.of() : l; }
    private String blankToNull(String s) { return s == null || s.isBlank() ? null : s; }
    private String shortGoal(String goal, String title) {
        String g = goal == null || goal.isBlank() ? title : goal;
        if (g == null) return "오늘의 학습 목표";
        g = g.replace("[오늘 목표]", "").trim();
        return g.length() > 40 ? g.substring(0, 40).trim() + "…" : g;
    }
}
