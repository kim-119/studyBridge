package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerSemanticDTO;
import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.util.LearningConceptValidator;
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
 *
 * <p>prerequisites / tasks / flow 는 논리적으로 독립이다.
 *  - prerequisites: "오늘 내용을 이해하기 위해 미리 알아두면 좋은 기초 개념". AI 응답이든 폴백이든
 *    {@link LearningConceptValidator}로 개념명 형태를 검증하고, task 문장·플래너 원문·제외 조각과 사실상 같은 항목은 버린다.
 *    폴백은 오늘의 개념을 복사하지 않고 로드맵에서 <b>앞서 다룬</b> 개념 중 주제와 연관된 것만 고른다(없으면 빈 목록).
 *    선행 개념 시간은 targetMinutes 에 절대 포함되지 않는다(includedInPlanTime=false).
 *  - tasks: 실제 플래너/로드맵 day 의 학습 활동(순서·식별자 authoritative).
 *  - flow: tasks 의 학습 활동 순서(권장시간 합 = targetMinutes). prerequisites 를 복사하거나 섞지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerSemanticAnalyzer {

    private static final String SEMANTIC_PATH = "/api/ai/planner/analyze-semantic";
    /** 사용자 노출 문장 규칙 버전. 올리면 기존 캐시는 다음 조회 때 AI 재호출 없이 문장만 다시 생성된다. */
    static final int NARRATIVE_VERSION = 2;

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
                .learningGoal(blankToNull(PlannerGoalNarrator.clean(req.getLearningGoal())))
                .targetMinutes(estimated ? total : target)
                .targetMinutesEstimated(estimated)
                .totalRecommendedMinutes(total)
                .summary(summary(req, ai, tasks, total))
                .goalAlignment(goalAlignment(req, ai, tasks))
                .prerequisites(prerequisites(req, ai))
                .tasks(tasks)
                .flow(flow(tasks))
                .checklistProgress(progress(req))
                .warnings(warnings(req, ai))
                .sourceFingerprint(fingerprint)
                .stale(false)
                .empty(false)
                .aiSource(fromAi ? "AI07" : "FALLBACK")
                .narrativeVersion(NARRATIVE_VERSION)
                .build();

        try { planner.setPlanAnalysisJson(json.writeValueAsString(resp)); planners.save(planner); }
        catch (Exception e) { log.warn("[planner:semantic] 캐시 저장 실패 plannerId={}: {}", plannerId, e.getMessage()); }

        log.info("[planner:semantic] plannerId={} sourceType={} tasks={} target={} total={} aiSource={}",
                plannerId, req.getSourceType(), tasks.size(), target, total, resp.getAiSource());
        return resp;
    }

    /**
     * 캐시된 분석 조회(없으면 empty). 플래너 의미가 바뀌면 stale=true 로 재분석을 안내.
     * 문장 규칙이 바뀐 구버전 캐시는 여기서 문장만 재생성해 저장한다(쓰기 필요).
     */
    @Transactional
    public AnalysisResponse get(Long userId, Long plannerId) {
        Planner planner = context.owned(userId, plannerId);
        AnalysisResponse cached = renarrateIfOutdated(planner, read(planner.getPlanAnalysisJson()));
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
        AnalysisResponse cached = renarrateIfOutdated(planner, read(planner.getPlanAnalysisJson()));
        if (cached != null && cached.getTasks() != null && !cached.getTasks().isEmpty()) return cached;
        return analyze(userId, plannerId);
    }

    // ---------------- 구버전 캐시 문장 재생성 ----------------

    /**
     * 캐시의 narrativeVersion 이 현재와 다르면 summary / goalAlignment / task reason·whyImportant·learningSequence 를
     * 현재 규칙({@link PlannerGoalNarrator})으로 다시 만든다. 구조(tasks/flow/prerequisites/시간)는 그대로, AI 재호출 없음.
     * 재생성본은 캐시에 다시 저장한다(저장 실패는 조회를 막지 않는다).
     */
    AnalysisResponse renarrateIfOutdated(Planner planner, AnalysisResponse cached) {
        if (cached == null || Objects.equals(cached.getNarrativeVersion(), NARRATIVE_VERSION)) return cached;
        Request req;
        try { req = context.build(planner); }
        catch (Exception e) {
            // 빈 플래너 등으로 구조화가 안 되면 캐시가 가진 정보만으로 최소 요청을 만든다.
            req = new Request();
            req.setPlannerId(planner.getId()); req.setTitle(planner.getTitle()); req.setSubject(planner.getSubject());
            req.setTopic(LearningConceptValidator.topicOf(planner.getTitle()));
            req.setLearningGoal(cached.getLearningGoal());
        }
        List<Task> tasks = cached.getTasks() == null ? List.of() : cached.getTasks();
        int total = cached.getTotalRecommendedMinutes() != null ? cached.getTotalRecommendedMinutes()
                : tasks.stream().mapToInt(t -> t.getRecommendedMinutes() == null ? 0 : t.getRecommendedMinutes()).sum();

        String goal = cached.getLearningGoal() != null ? cached.getLearningGoal() : req.getLearningGoal();
        cached.setLearningGoal(blankToNull(PlannerGoalNarrator.clean(goal)));
        String summary = narrate(req, cached.getSummary());
        cached.setSummary(summary != null ? summary : PlannerGoalNarrator.planSummary(req, tasks, total));

        PlanGoalAlignment g = cached.getGoalAlignment() == null ? new PlanGoalAlignment() : cached.getGoalAlignment();
        Level level = g.getLevel() == null ? Level.MEDIUM : g.getLevel();
        g.setLevel(level);
        String gs = narrate(req, g.getSummary());
        g.setSummary(gs != null ? gs : PlannerGoalNarrator.alignmentSummary(req, tasks, level));
        String gr = narrate(req, g.getReason());
        g.setReason(gr != null ? gr
                : "구성된 활동이 오늘의 학습 목표를 향해 순차적으로 배치되어 있어 전반적인 정합성은 양호합니다.");
        List<String> issues = new ArrayList<>();
        for (String i : g.getIssues() == null ? List.<String>of() : g.getIssues()) {
            String c = narrate(req, i);
            if (c != null) issues.add(c);
        }
        g.setIssues(issues);
        cached.setGoalAlignment(g);

        for (Task t : tasks) {
            TaskType type = t.getType() == null ? TaskType.CONCEPT : t.getType();
            GoalAlignment ga = t.getGoalAlignment() == null ? new GoalAlignment() : t.getGoalAlignment();
            Level lv = ga.getLevel() == null ? defaultLevel(type) : ga.getLevel();
            ga.setLevel(lv);
            String reason = narrate(req, ga.getReason());
            ga.setReason(reason != null ? reason : PlannerGoalNarrator.taskAlignmentReason(req, type, lv));
            t.setGoalAlignment(ga);
            String why = narrate(req, t.getWhyImportant());
            t.setWhyImportant(why != null ? why : whyImportant(type, t.getTitle()));
            List<String> seq = new ArrayList<>();
            for (String step : t.getLearningSequence() == null ? List.<String>of() : t.getLearningSequence()) {
                String c = prose(req, PlannerGoalNarrator.clean(step));
                if (c != null && !c.isBlank()) seq.add(c);
            }
            t.setLearningSequence(seq);
        }
        cached.setNarrativeVersion(NARRATIVE_VERSION);

        try { planner.setPlanAnalysisJson(json.writeValueAsString(cached)); planners.save(planner); }
        catch (Exception e) { log.warn("[planner:semantic] 구버전 캐시 문장 재생성 저장 실패 plannerId={}: {}", planner.getId(), e.getMessage()); }
        log.info("[planner:semantic] 구버전 캐시 문장 재생성 plannerId={} tasks={}", planner.getId(), tasks.size());
        return cached;
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
            t.setGoalAlignment(taskAlignment(a, req, type));
            String why = narrate(req, text(a, "whyImportant", null));
            t.setWhyImportant(why != null ? why : whyImportant(type, in.getTitle()));
            t.setPrerequisites(taskPrereqs(a, req, type));
            List<String> seq = new ArrayList<>();
            for (String step : sequence(a, type)) seq.add(prose(req, PlannerGoalNarrator.clean(step)));
            t.setLearningSequence(seq);
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

    /** 계획 summary: AI 산문이 검사를 통과하면 사용, 아니면 실제 활동 구성으로 완결 문장을 생성한다. */
    private String summary(Request req, JsonNode ai, List<Task> tasks, int total) {
        String s = narrate(req, text(ai, "summary", null));
        return s != null ? s : PlannerGoalNarrator.planSummary(req, tasks, total);
    }

    /**
     * 목표 정합성: summary/reason 은 학습 목표 원문을 결합하지 않고, 목표의 학습 방식·활동 유형·정합성 수준으로
     * 완결된 한국어 문장을 만든다({@link PlannerGoalNarrator}). AI 산문도 같은 검사를 통과해야만 그대로 쓴다.
     */
    private PlanGoalAlignment goalAlignment(Request req, JsonNode ai, List<Task> tasks) {
        PlanGoalAlignment g = new PlanGoalAlignment();
        JsonNode a = ai == null ? null : ai.get("goalAlignment");
        Level level = a != null && a.hasNonNull("level") ? parseLevel(a.get("level").asText()) : Level.MEDIUM;
        g.setLevel(level);
        String summary = narrate(req, text(a, "summary", null));
        g.setSummary(summary != null ? summary : PlannerGoalNarrator.alignmentSummary(req, tasks, level));
        String reason = narrate(req, text(a, "reason", null));
        g.setReason(reason != null ? reason
                : "구성된 활동이 오늘의 학습 목표를 향해 순차적으로 배치되어 있어 전반적인 정합성은 양호합니다.");
        List<String> issues = new ArrayList<>();
        for (String i : strings(a == null ? null : a.get("issues"))) {
            String c = narrate(req, i);
            if (c != null) issues.add(c);
        }
        g.setIssues(issues);
        return g;
    }

    private GoalAlignment taskAlignment(JsonNode a, Request req, TaskType type) {
        GoalAlignment g = new GoalAlignment();
        JsonNode ga = a == null ? null : a.get("goalAlignment");
        Level level = ga != null && ga.hasNonNull("level") ? parseLevel(ga.get("level").asText()) : defaultLevel(type);
        g.setLevel(level);
        String reason = narrate(req, text(ga, "reason", null));
        g.setReason(reason != null ? reason : PlannerGoalNarrator.taskAlignmentReason(req, type, level));
        return g;
    }

    static final String PREREQ_REASON_DEFAULT = "익숙하지 않다면 학습 전에 한 번 확인해 두는 것을 권장합니다.";
    static final String PREREQ_REASON_PRIOR = "앞선 로드맵 학습에서 다룬 개념입니다. 익숙하지 않다면 학습 전에 확인을 권장합니다.";
    private static final int MAX_FALLBACK_PREREQS = 5;

    /**
     * 선행 개념: AI 응답을 검증해 통과한 것만 쓰고, 하나도 없으면 로드맵에서 앞서 다룬 연관 개념으로 폴백한다.
     * 오늘의 core concepts 는 "오늘 배울 내용"이므로 선행 개념으로 복사하지 않는다. 폴백도 비면 정직하게 빈 목록.
     */
    private List<Prerequisite> prerequisites(Request req, JsonNode ai) {
        List<Prerequisite> fromAi = validatePrerequisites(prereqNodes(ai == null ? null : ai.get("prerequisites")), req);
        if (!fromAi.isEmpty()) return fromAi;
        return fallbackPrerequisites(req);
    }

    private List<Prerequisite> taskPrereqs(JsonNode a, Request req, TaskType type) {
        // 실데이터가 없으면 추측하지 않는다(로드맵 핵심개념은 task 선행개념으로 쓰지 않는다).
        return validatePrerequisites(prereqNodes(a == null ? null : a.get("prerequisites")), req);
    }

    /**
     * 선행 개념 검증(도메인 문자열 하드코딩 없음):
     *  - 개념명 형태(짧은 명사구)여야 한다 — 문장/설명문/예제 문장/코드 조각/"~이다·~하는 것" 서술은 거부
     *  - task 제목·설명, 학습 목표, 플래너 원문 줄과 사실상 동일하면 거부(task 를 선행 개념으로 재포장 금지)
     *  - 로드맵에서 이미 제외한 문장형 조각과 사실상 동일하면 거부
     *  - 중복 제거, includedInPlanTime 은 항상 false(선행 개념 시간은 목표 학습시간에 포함하지 않는다)
     */
    List<Prerequisite> validatePrerequisites(List<Prerequisite> candidates, Request req) {
        List<String> forbidden = new ArrayList<>();
        for (InputItem t : safe(req.getDetailTasks())) { forbidden.add(t.getTitle()); forbidden.add(t.getDescription()); }
        for (InputItem t : safe(req.getChecklist())) forbidden.add(t.getTitle());
        forbidden.add(req.getLearningGoal());
        for (String line : (req.getContent() == null ? "" : req.getContent()).split("\\R"))
            forbidden.add(line.replaceFirst("^\\s*\\d+[.)]\\s*", "").replace("[오늘 목표]", "").trim());
        forbidden.addAll(safe(req.getExcludedFragments()));
        forbidden.removeIf(f -> f == null || f.isBlank());

        List<Prerequisite> out = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (Prerequisite c : candidates) {
            String name = c.getName() == null ? "" : c.getName().trim();
            if (!LearningConceptValidator.isConceptLike(name)) continue;
            if (LearningConceptValidator.duplicatesAny(name, forbidden)) continue;
            if (!seen.add(LearningConceptValidator.normalize(name))) continue;
            String reason = c.getReason() == null || c.getReason().isBlank() ? PREREQ_REASON_DEFAULT : prose(req, c.getReason());
            out.add(new Prerequisite(name, reason, false));
        }
        return out;
    }

    /** 폴백: 로드맵에서 오늘보다 앞서 다룬 개념형 개념 중 주제어/과목/오늘 개념과 어휘적으로 연관된 것(최대 5개). */
    private List<Prerequisite> fallbackPrerequisites(Request req) {
        List<String> anchors = new ArrayList<>();
        if (req.getTopic() != null) anchors.add(req.getTopic());
        if (req.getSubject() != null && !req.getSubject().isBlank()) anchors.add(req.getSubject());
        anchors.addAll(safe(req.getCoreConcepts()));
        List<Prerequisite> candidates = new ArrayList<>();
        for (String c : safe(req.getPriorConcepts()))
            if (LearningConceptValidator.isRelated(c, anchors)) candidates.add(new Prerequisite(c, PREREQ_REASON_PRIOR, false));
        List<Prerequisite> valid = validatePrerequisites(candidates, req);
        return valid.size() > MAX_FALLBACK_PREREQS ? new ArrayList<>(valid.subList(0, MAX_FALLBACK_PREREQS)) : valid;
    }

    private List<Prerequisite> prereqNodes(JsonNode node) {
        List<Prerequisite> out = new ArrayList<>();
        if (node != null && node.isArray()) {
            for (JsonNode p : node) {
                String name = p.isTextual() ? p.asText() : text(p, "name", null);
                if (name == null || name.isBlank()) continue;
                out.add(new Prerequisite(name, text(p, "reason", null), false));
            }
        }
        return out;
    }

    /** AI 산문에 로드맵 제외 조각이 다시 섞여 오면 주제어로 치환한다(AI 응답을 무조건 신뢰하지 않는다). */
    private String prose(Request req, String s) {
        if (s == null) return null;
        return LearningConceptValidator.scrub(s, req.getExcludedFragments(), req.getTopic());
    }

    /**
     * 사용자 노출 산문(AI 응답): 조사 보정 표기·메타 괄호 정리 → 목표 원문 결합/말줄임/미완결 문장이면 null(폴백 생성) →
     * 제외 조각 치환. null 이면 호출자가 결정적 문장을 생성한다.
     */
    private String narrate(Request req, String s) {
        String c = PlannerGoalNarrator.sanitizeAiProse(s, req.getLearningGoal());
        return c == null ? null : prose(req, c);
    }

    private List<String> warnings(Request req, JsonNode ai) {
        List<String> out = new ArrayList<>();
        for (String w : strings(ai == null ? null : ai.get("warnings"))) out.add(prose(req, w));
        int excluded = safe(req.getExcludedFragments()).size();
        if (excluded > 0) out.add("로드맵 원문에서 개념명이 아닌 문장형 항목 " + excluded + "개를 제외하고 분석했습니다.");
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

    /** 학습 Data Flow = 실제 학습 활동(tasks)의 순서. 선행 개념과 독립이며 합계는 targetMinutes 와 같다. */
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
}
