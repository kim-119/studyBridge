package com.studybridge.api.service;

import com.fasterxml.jackson.databind.*;
import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import com.studybridge.api.util.LearningConceptValidator;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;
import java.util.regex.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * 플래너 "AI 계획 분석" 입력(Request) 조립.
 *
 * <p>ROADMAP_AUTO 플래너의 신뢰 우선순위:
 * <ol>
 *   <li>플래너 title(주제어)·subject
 *   <li>sourceRoadmapId 로드맵의 <b>정확히 그 week/day</b>의 objective
 *   <li>그 day 의 core_concepts(개념형만)·tasks
 *   <li>Planner.content / tmi — 로드맵 day 를 찾지 못했을 때의 폴백 + 보조 메모
 * </ol>
 * 로드맵 원문에 섞인 문장형/예제형 조각(개념명이 아닌 것)은 {@link LearningConceptValidator}로 걸러내고,
 * task 제목·objective 안에 끼워진 동일 조각은 주제어로 치환한다. 제외된 조각은 {@code excludedFragments}에
 * 남겨 분석기가 선행 개념 검증/경고에 쓰되 AI07 로는 보내지 않는다.
 */
@Service @RequiredArgsConstructor @Transactional(readOnly=true)
public class PlannerAnalysisContext {
    private final PlannerRepository planners;
    private final RoadmapRepository roadmaps;
    private final RoadmapTaskRepository roadmapTasks;
    private final PlanAnalysisRepository analyses;
    private final PlanAnalysisItemRepository items;
    private final ObjectMapper json;
    private final PlannerTimeAllocator allocator;

    private static final Pattern TITLE_WEEK_DAY = Pattern.compile("\\[로드맵\\s+(\\d+)주차\\s+(\\d+)일\\]");
    private static final int MAX_PRIOR_CONCEPTS = 40;

    /** 로드맵 day 하나를 정규화한 결과. concepts=개념형만, rejected=문장/예제 조각, tasks=[title, description]. */
    record NormalizedDay(String title, String objective, List<String> concepts, List<String> rejected,
                         List<String[]> tasks, List<String> reviewQuestions, String deliverable) {}

    public Planner owned(Long userId, Long plannerId) {
        Planner p=planners.findById(plannerId).orElseThrow(()->new NoSuchElementException("플래너를 찾을 수 없습니다."));
        if(!Objects.equals(userId,p.getUserId()))throw new SecurityException("플래너 조회 권한이 없습니다.");
        return p;
    }

    public Request build(Planner p) {
        boolean roadmap=p.getSourceRoadmapId()!=null || "ROADMAP_AUTO".equals(p.getSourceType()) || p.getPlannerType()==PlannerType.ROADMAP;
        String topic=LearningConceptValidator.topicOf(p.getTitle());
        if(topic.isBlank())topic=or(p.getTitle(),"");
        Request req=new Request();req.setPlannerId(p.getId());req.setTitle(p.getTitle());req.setTopic(topic);req.setSubject(or(p.getSubject(),""));
        req.setLearningType(or(p.getStudyType(),""));req.setPriority(or(p.getPriority(),""));
        req.setTargetMinutes(allocator.target(p.getGoalTime(),p.getEstimatedMinutes()));req.setSourceType(roadmap?"ROADMAP":"MANUAL");
        req.setCoreConcepts(List.of());req.setPriorConcepts(List.of());req.setReviewQuestions(List.of());req.setOutputs(List.of());
        List<String> excluded=new ArrayList<>();
        List<InputItem> tasks=new ArrayList<>();
        String learningGoal=null;
        if(roadmap) {
            Roadmap r=p.getSourceRoadmapId()==null?null:roadmaps.findById(p.getSourceRoadmapId()).orElse(null);
            if(r==null && p.getSourceMaterialId()!=null)r=roadmaps.findByMaterial_MaterialId(p.getSourceMaterialId()).orElse(null);
            if(r!=null && !Objects.equals(r.getUserId(),p.getUserId()))throw new SecurityException("로드맵 조회 권한이 없습니다.");
            Integer week=p.getRoadmapWeek(),day=p.getRoadmapDay();
            Matcher m=TITLE_WEEK_DAY.matcher(or(p.getTitle(),""));
            if(m.find()){if(week==null)week=Integer.valueOf(m.group(1));if(day==null)day=Integer.valueOf(m.group(2));}
            RoadmapContext ctx=new RoadmapContext(week,day,p.getTerm(),null,List.of(),List.of());
            req.setRoadmapContext(ctx);
            if(r!=null) {
                JsonNode root=parse(r.getRoadmapJson());
                if(root.has("roadmap"))root=root.path("roadmap");if(root.has("roadmapData"))root=root.path("roadmapData");
                List<JsonNode> days=new ArrayList<>();int selected=-1,wi=0;
                for(JsonNode w:root.path("weeks")) {wi++;int di=0;
                    for(JsonNode d:w.path("days")){di++;
                        if(week!=null && day!=null && w.path("week").asInt(wi)==week && d.path("day_index").asInt(di)==day)selected=days.size();
                        days.add(d);
                    }
                }
                if(selected>=0) {
                    NormalizedDay today=normalizeDay(days.get(selected),topic);
                    excluded.addAll(today.rejected());
                    if(today.objective()!=null && !today.objective().isBlank()){learningGoal=today.objective();ctx.setLearningGoal(learningGoal);}
                    req.setCoreConcepts(today.concepts());
                    req.setReviewQuestions(today.reviewQuestions());
                    if(today.deliverable()!=null && !today.deliverable().isBlank())req.setOutputs(List.of(today.deliverable()));
                    if(selected>0)ctx.setPreviousLearning(dayDescription(days.get(selected-1)));
                    if(selected+1<days.size())ctx.setNextLearning(dayDescription(days.get(selected+1)));
                    for(String[] t:today.tasks())addTask(tasks,p.getId(),t[0],t[1]);
                    req.setPriorConcepts(priorConcepts(days,selected,today.concepts()));
                } else if(r.getRoadmapJson()==null && week!=null) {
                    // 레거시 관계형 로드맵: step=주차, task=그 주차의 항목(일차 구분 없음) → 주차 task 전체
                    for(RoadmapTask t:roadmapTasks.findByStep_Roadmap_RoadmapIdAndStep_StepOrderOrderByTaskOrderAscTaskIdAsc(r.getRoadmapId(),week))
                        tasks.add(new InputItem("roadmap-"+t.getTaskId(),t.getContent(),"",t.getIsCompleted()));
                    ctx.setLearningGoal(r.getGoal());
                }
            }
        }
        // content/tmi 는 보조 컨텍스트: 로드맵에서 제외한 조각이 그대로 들어 있으므로 같은 규칙으로 치환해 전달한다.
        String content=LearningConceptValidator.scrub(or(p.getContent(),""),excluded,topic);
        req.setContent(content);req.setMemo(LearningConceptValidator.scrub(or(p.getTmi(),""),excluded,topic));
        req.setLearningGoal(learningGoal!=null?learningGoal:objective(content));
        if(tasks.isEmpty()) {
            int start=content.indexOf("[할 일]");
            String todo=start>=0?content.substring(start+5):content;
            for(String line:todo.split("\\R")){
                String title=line.replaceFirst("^\\s*\\d+[.)]\\s*","").trim();
                if(!title.isBlank() && !title.startsWith("["))addTask(tasks,p.getId(),title,"");
            }
        }
        if(tasks.isEmpty())throw new PlanAnalysisException("PLAN_ANALYSIS_EMPTY","분석할 플래너 Task가 없습니다. 플래너 내용을 확인해 주세요.");
        req.setDetailTasks(tasks);
        req.setExcludedFragments(excluded);
        // Existing persisted checklist is carried by identity. Completion is never an AI decision.
        List<InputItem> checklist=new ArrayList<>();
        if(p.getMaterialId()!=null)analyses.findTopByUserIdAndMaterialIdOrderByIdDesc(p.getUserId(),p.getMaterialId()).ifPresent(a->{
            for(PlanAnalysisItem i:items.findByAnalysisIdOrderByOrderIndexAsc(a.getId()))if(!i.isDeleted())
                checklist.add(new InputItem(String.valueOf(i.getId()),i.getText(),or(i.getSourceText(),""),i.isCompleted()));
        });
        req.setChecklist(checklist);return req;
    }

    public String fingerprint(Request req) {
        try {
            // Checklist completion, display state and wall-clock inputs do not change plan meaning.
            JsonNode node=json.valueToTree(req);((com.fasterxml.jackson.databind.node.ObjectNode)node).remove("checklist");
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsBytes(node)));
        }catch(Exception e){throw new IllegalStateException("플래너 변경 여부를 확인하지 못했습니다.");}
    }

    /**
     * 로드맵 day 정규화: core_concepts 를 개념형/문장형으로 분리하고, 문장형 조각이 끼워진
     * objective·task·review_question·deliverable 은 그 조각을 day 주제어로 치환한다.
     * 주제어는 플래너 제목 주제어를 우선하고, 없으면 day title 에서 뽑는다.
     */
    NormalizedDay normalizeDay(JsonNode d,String plannerTopic) {
        String dayTitle=LearningConceptValidator.topicOf(text(d,"title"));
        String topic=plannerTopic!=null && !plannerTopic.isBlank()?plannerTopic:dayTitle;
        LearningConceptValidator.Split split=LearningConceptValidator.split(strings(d.path("core_concepts")));
        List<String> rejected=split.rejected();
        String objective=LearningConceptValidator.scrub(text(d,"objective","learningGoal","goal"),rejected,topic);
        List<String[]> tasks=new ArrayList<>();
        for(String key:List.of("tasks","detailTasks","detail_tasks"))for(JsonNode t:d.path(key)){
            String title=t.isTextual()?t.asText():text(t,"title","content","text");
            if(title==null||title.isBlank())continue;
            tasks.add(new String[]{LearningConceptValidator.scrub(title,rejected,topic),
                    LearningConceptValidator.scrub(or(t.isTextual()?null:text(t,"description"),""),rejected,topic)});
        }
        List<String> questions=new ArrayList<>();
        for(String q:strings(d.path("review_questions")))questions.add(LearningConceptValidator.scrub(q,rejected,topic));
        String deliverable=LearningConceptValidator.scrub(text(d,"deliverable","output"),rejected,topic);
        return new NormalizedDay(dayTitle,objective,split.accepted(),rejected,tasks,questions,deliverable);
    }

    /** 오늘보다 앞선 day 들의 개념형 core_concepts(로드맵 순서, 중복·오늘 개념 제외). 선행 개념 후보로만 쓴다. */
    private List<String> priorConcepts(List<JsonNode> days,int selected,List<String> todayConcepts) {
        Set<String> seen=new HashSet<>();
        for(String c:todayConcepts)seen.add(LearningConceptValidator.normalize(c));
        List<String> out=new ArrayList<>();
        for(int i=0;i<selected && out.size()<MAX_PRIOR_CONCEPTS;i++)
            for(String c:LearningConceptValidator.split(strings(days.get(i).path("core_concepts"))).accepted())
                if(seen.add(LearningConceptValidator.normalize(c)) && out.size()<MAX_PRIOR_CONCEPTS)out.add(c);
        return out;
    }

    private void addTask(List<InputItem> out,Long pid,String title,String description){
        if(title==null||title.isBlank())return;
        String id=UUID.nameUUIDFromBytes((pid+":"+out.size()+":"+title).getBytes(StandardCharsets.UTF_8)).toString();
        out.add(new InputItem(id,title,or(description,""),null));
    }
    private String objective(String content){return or(content,"").split("\\[할 일\\]",2)[0].replace("[오늘 목표]","").trim();}
    private JsonNode parse(String s){try{return s==null?json.createObjectNode():json.readTree(s);}catch(Exception e){throw new IllegalArgumentException("저장된 로드맵 형식이 올바르지 않습니다.");}}
    private String text(JsonNode n,String... keys){if(n==null)return null;for(String k:keys)if(n.hasNonNull(k)&&n.get(k).isValueNode())return n.get(k).asText();return null;}
    private List<String> strings(JsonNode n){List<String> out=new ArrayList<>();if(n.isArray())for(JsonNode v:n)if(v.isTextual()&&!v.asText().isBlank())out.add(v.asText());return out;}
    /** 이웃 day 설명(title/objective). 그 day 의 문장형 조각은 그 day 의 주제어로 치환한다. */
    private List<String> dayDescription(JsonNode d){
        NormalizedDay n=normalizeDay(d,null);
        List<String> out=new ArrayList<>();
        if(n.title()!=null && !n.title().isBlank())out.add(n.title());
        if(n.objective()!=null && !n.objective().isBlank())out.add(n.objective());
        return out;
    }
    private String or(String s,String fallback){return s==null?fallback:s;}
}
