package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerPdfDto;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;
import java.util.regex.Pattern;

@Service @RequiredArgsConstructor @Slf4j
@Transactional(readOnly = true)
public class PlannerPdfMapper {
    private final PlannerRepository planners;
    private final RoadmapRepository roadmaps;
    private final RoadmapTaskRepository roadmapTasks;
    private final PlannerAiResultRepository aiResults;
    private final ObjectMapper json;

    public PlannerPdfDto load(Long userId, Long plannerId) {
        Planner p = planners.findById(plannerId).orElseThrow(() -> new NoSuchElementException("플래너가 없습니다."));
        if (!userId.equals(p.getUserId())) throw new SecurityException("플래너 조회 권한이 없습니다.");
        Integer week = p.getRoadmapWeek(), day = p.getRoadmapDay();
        var match = Pattern.compile("\\[로드맵\\s+(\\d+)주차\\s+(\\d+)일\\]").matcher(or(p.getTitle(), ""));
        if (match.find()) {
            if (week == null) week = Integer.valueOf(match.group(1));
            if (day == null) day = Integer.valueOf(match.group(2));
        }
        Roadmap roadmap = null;
        if (p.getSourceRoadmapId() != null) roadmap = roadmaps.findById(p.getSourceRoadmapId()).orElse(null);
        else if ("ROADMAP_AUTO".equals(p.getSourceType()) && p.getSourceMaterialId() != null)
            roadmap = roadmaps.findByMaterial_MaterialId(p.getSourceMaterialId()).orElse(null);
        if (roadmap != null && !userId.equals(roadmap.getUserId())) throw new SecurityException("로드맵 조회 권한이 없습니다.");
        JsonNode root = roadmap == null ? null : parse(roadmap.getRoadmapJson());
        if (root != null && root.has("roadmap")) root = root.get("roadmap");
        if (root != null && root.has("roadmapData")) root = root.get("roadmapData");
        JsonNode daily = findDay(root, week, day, p);
        List<String> tasks = new ArrayList<>();
        List<String> reviews = new ArrayList<>();
        String objective = null, deliverable = null;
        int rawTasks = 0, rawDetails = 0;
        if (daily != null) {
            rawTasks = count(daily.get("tasks"));
            rawDetails = count(daily.get("detailTasks")) + count(daily.get("detail_tasks"));
            tasks.addAll(strings(daily.get("tasks")));
            tasks.addAll(strings(daily.get("detailTasks")));
            tasks.addAll(strings(daily.get("detail_tasks")));
            objective = text(daily, "objective", "learningGoal", "learning_goal", "goal");
            reviews.addAll(strings(field(daily, "review_questions", "reviewQuestions")));
            deliverable = text(daily, "deliverable", "output");
        }
        // Legacy relational steps are weeks; select the matching day task, never another week's tasks.
        if (tasks.isEmpty() && roadmap != null && root == null && week != null && day != null) {
            for (RoadmapTask t : roadmapTasks.findByStep_Roadmap_RoadmapIdAndStep_StepOrderAndTaskOrderOrderByTaskId(
                    roadmap.getRoadmapId(), week, day)) {
                if (t.getContent() != null && !t.getContent().isBlank()) tasks.add(t.getContent());
            }
        }
        PlannerAiResult ai = aiResults.findByPlannerId(plannerId).orElse(null);
        if (tasks.isEmpty() && ai != null) {
            tasks.addAll(strings(parse(ai.getTaskBreakdown())));
            if (tasks.isEmpty()) tasks.addAll(strings(parse(ai.getExpandedTodo())));
        }
        if (tasks.isEmpty()) tasks.addAll(plannerTasks(p.getContent()));
        if (tasks.isEmpty() && p.getTmi() != null && !p.getTmi().isBlank()) tasks.add(p.getTmi());
        objective = first(objective, ai == null ? null : ai.getRefinedGoal(),
                ai == null ? null : ai.getExpandedGoal(), plannerObjective(p.getContent()));
        if (reviews.isEmpty() && ai != null) reviews.addAll(strings(parse(ai.getAiQuestions())));
        tasks = new ArrayList<>(new LinkedHashSet<>(tasks));
        String reason = daily != null ? "roadmap_day" : roadmap != null ? "day_not_found_or_legacy" : "no_source_roadmap";
        log.info("[planner:pdf:mapping] plannerId={} roadmapId={} week={} day={} dayFound={} tasks={} detailTasks={} mappedTasks={} reason={} objectivePresent={}",
                plannerId, roadmap == null ? null : roadmap.getRoadmapId(), week, day, daily != null,
                rawTasks, rawDetails, tasks.size(), reason, objective != null && !objective.isBlank());
        if ((objective == null || objective.isBlank()) && tasks.isEmpty()) {
            throw new IllegalArgumentException("플래너에 학습 목표와 할 일이 없습니다. 실제 플래너를 선택하거나 내용을 입력해주세요.");
        }
        String goalTime = p.getGoalTime();
        if ((goalTime == null || goalTime.isBlank()) && daily != null) {
            int minutes = 0;
            for (JsonNode t : array(daily.get("tasks"))) minutes += intValue(t, "estimated_minutes", "estimatedMinutes", 0);
            if (minutes > 0) goalTime = minutes + "분";
        }
        var date = p.getPlannerDate();
        return PlannerPdfDto.builder().plannerId(plannerId).title(first(p.getTitle(), text(daily,"title")))
                .year(date != null ? Integer.valueOf(date.getYear()) : p.getYear()).month(date != null ? Integer.valueOf(date.getMonthValue()) : p.getMonth())
                .day(date != null ? Integer.valueOf(date.getDayOfMonth()) : p.getDay()).dayOfWeek(p.getDayOfWeek())
                .roadmapWeek(week).roadmapDay(day).term(p.getTerm()).studyType(first(p.getStudyType(), text(daily,"studyType","study_type"))).priority(first(p.getPriority(), text(daily,"priority")))
                .goalTime(first(goalTime, ai == null ? null : ai.getEstimatedTime())).dDay(first(p.getDDay(),text(daily,"dDay","deadline","exam_date")))
                .subject(first(p.getSubject(), text(root,"subject"))).objective(objective).tasks(tasks)
                .reviewQuestions(reviews).deliverable(deliverable).memo(p.getTmi()).timeTableJson(p.getTimeTableJson()).build();
    }

    private JsonNode findDay(JsonNode root, Integer week, Integer day, Planner planner) {
        if (root == null) return null;
        int wi = 0;
        for (JsonNode w : array(root.get("weeks"))) {
            wi++;
            int wn = intValue(w,"week","weekNumber",wi);
            if (week != null && wn != week) continue;
            int di = 0;
            for (JsonNode d : array(w.get("days"))) {
                di++;
                if (week != null && day != null && (intValue(d,"day_index","dayIndex",di) == day || di == day)) return d;
                if (planner.getPlannerDate() != null && planner.getPlannerDate().toString().equals(text(d,"date"))) return d;
            }
        }
        return null;
    }
    private List<String> plannerTasks(String content) {
        if (content == null || !content.contains("[할 일]")) return List.of();
        return Arrays.stream(content.substring(content.indexOf("[할 일]") + "[할 일]".length()).split("\\R"))
                .map(String::trim).filter(v -> !v.isBlank()).toList();
    }
    private String plannerObjective(String content) {
        if (content == null) return null;
        return content.split("\\[할 일\\]",2)[0].replace("[오늘 목표]", "").trim();
    }
    private JsonNode parse(String value) {
        if (value == null || value.isBlank()) return null;
        try { return json.readTree(value); }
        catch (Exception e) { log.warn("[planner:pdf:mapping] invalid stored JSON"); return null; }
    }
    private List<JsonNode> array(JsonNode n) {
        List<JsonNode> out = new ArrayList<>();
        if (n != null && n.isArray()) n.forEach(out::add);
        return out;
    }
    private List<String> strings(JsonNode n) {
        List<String> out = new ArrayList<>();
        for (JsonNode t : array(n)) {
            String value = t.isTextual() ? t.asText() : first(text(t,"content","text"),
                    String.join(": ", Arrays.stream(new String[]{text(t,"title"),text(t,"description")}).filter(Objects::nonNull).toList()));
            if (value != null && !value.isBlank()) out.add(value);
            out.addAll(strings(field(t,"detailTasks","detail_tasks")));
        }
        return out;
    }
    private JsonNode field(JsonNode n,String... keys) {
        if (n == null) return null;
        for (String k:keys) if (n.hasNonNull(k)) return n.get(k);
        return null;
    }
    private String text(JsonNode n,String... keys) { JsonNode v=field(n,keys); return v != null && v.isValueNode() ? v.asText() : null; }
    private int intValue(JsonNode n,String a,String b,int fallback) { JsonNode v=field(n,a,b); return v == null ? fallback : v.asInt(fallback); }
    private int count(JsonNode n) { return n != null && n.isArray() ? n.size() : 0; }
    private String first(String... values) { for(String v:values) if(v!=null&&!v.isBlank()) return v; return null; }
    private String or(String v,String fallback) { return v==null?fallback:v; }
}
