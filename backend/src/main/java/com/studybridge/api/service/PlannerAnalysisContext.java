package com.studybridge.api.service;

import com.fasterxml.jackson.databind.*;
import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.*;
import java.util.regex.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

@Service @RequiredArgsConstructor @Transactional(readOnly=true)
public class PlannerAnalysisContext {
    private final PlannerRepository planners;
    private final RoadmapRepository roadmaps;
    private final RoadmapTaskRepository roadmapTasks;
    private final PlanAnalysisRepository analyses;
    private final PlanAnalysisItemRepository items;
    private final ObjectMapper json;
    private final PlannerTimeAllocator allocator;

    public Planner owned(Long userId, Long plannerId) {
        Planner p=planners.findById(plannerId).orElseThrow(()->new NoSuchElementException("플래너를 찾을 수 없습니다."));
        if(!Objects.equals(userId,p.getUserId()))throw new SecurityException("플래너 조회 권한이 없습니다.");
        return p;
    }
    public Request build(Planner p) {
        boolean roadmap=p.getSourceRoadmapId()!=null || "ROADMAP_AUTO".equals(p.getSourceType()) || p.getPlannerType()==PlannerType.ROADMAP;
        Request req=new Request();req.setPlannerId(p.getId());req.setTitle(p.getTitle());req.setSubject(or(p.getSubject(),""));
        req.setLearningType(or(p.getStudyType(),""));req.setPriority(or(p.getPriority(),""));req.setMemo(or(p.getTmi(),""));
        req.setTargetMinutes(allocator.target(p.getGoalTime(),p.getEstimatedMinutes()));req.setSourceType(roadmap?"ROADMAP":"MANUAL");
        req.setContent(or(p.getContent(),""));req.setLearningGoal(objective(p.getContent()));
        req.setCoreConcepts(List.of());req.setReviewQuestions(List.of());req.setOutputs(List.of());
        List<InputItem> tasks=new ArrayList<>();
        if(roadmap) {
            Roadmap r=p.getSourceRoadmapId()==null?null:roadmaps.findById(p.getSourceRoadmapId()).orElse(null);
            if(r==null && p.getSourceMaterialId()!=null)r=roadmaps.findByMaterial_MaterialId(p.getSourceMaterialId()).orElse(null);
            if(r!=null && !Objects.equals(r.getUserId(),p.getUserId()))throw new SecurityException("로드맵 조회 권한이 없습니다.");
            Integer week=p.getRoadmapWeek(),day=p.getRoadmapDay();
            Matcher m=Pattern.compile("\\[로드맵\\s+(\\d+)주차\\s+(\\d+)일\\]").matcher(or(p.getTitle(),""));
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
                    JsonNode d=days.get(selected);String goal=text(d,"objective","learningGoal","goal");
                    if(goal!=null){req.setLearningGoal(goal);ctx.setLearningGoal(goal);}
                    req.setCoreConcepts(strings(d.path("core_concepts")));req.setReviewQuestions(strings(d.path("review_questions")));
                    String output=text(d,"deliverable","output");if(output!=null)req.setOutputs(List.of(output));
                    if(selected>0)ctx.setPreviousLearning(dayDescription(days.get(selected-1)));
                    if(selected+1<days.size())ctx.setNextLearning(dayDescription(days.get(selected+1)));
                    for(JsonNode t:d.path("tasks"))addTask(tasks,p.getId(),t.isTextual()?t.asText():text(t,"title","content","text"),text(t,"description"));
                    for(String key:List.of("detailTasks","detail_tasks"))for(JsonNode t:d.path(key))addTask(tasks,p.getId(),t.isTextual()?t.asText():text(t,"title","content","text"),text(t,"description"));
                } else if(r.getRoadmapJson()==null && week!=null && day!=null) {
                    for(RoadmapTask t:roadmapTasks.findByStep_Roadmap_RoadmapIdAndStep_StepOrderAndTaskOrderOrderByTaskId(r.getRoadmapId(),week,day))
                        tasks.add(new InputItem("roadmap-"+t.getTaskId(),t.getContent(),"",t.getIsCompleted()));
                    ctx.setLearningGoal(r.getGoal());
                }
            }
        }
        if(tasks.isEmpty()) {
            String content=or(p.getContent(),"");int start=content.indexOf("[할 일]");
            String todo=start>=0?content.substring(start+5):content;
            for(String line:todo.split("\\R")){
                String title=line.replaceFirst("^\\s*\\d+[.)]\\s*","").trim();
                if(!title.isBlank() && !title.startsWith("["))addTask(tasks,p.getId(),title,"");
            }
        }
        if(tasks.isEmpty())throw new PlanAnalysisException("PLAN_ANALYSIS_EMPTY","분석할 플래너 Task가 없습니다. 플래너 내용을 확인해 주세요.");
        req.setDetailTasks(tasks);
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
    private void addTask(List<InputItem> out,Long pid,String title,String description){
        if(title==null||title.isBlank())return;
        String id=UUID.nameUUIDFromBytes((pid+":"+out.size()+":"+title).getBytes(StandardCharsets.UTF_8)).toString();
        out.add(new InputItem(id,title,or(description,""),null));
    }
    private String objective(String content){return or(content,"").split("\\[할 일\\]",2)[0].replace("[오늘 목표]","").trim();}
    private JsonNode parse(String s){try{return s==null?json.createObjectNode():json.readTree(s);}catch(Exception e){throw new IllegalArgumentException("저장된 로드맵 형식이 올바르지 않습니다.");}}
    private String text(JsonNode n,String... keys){for(String k:keys)if(n.hasNonNull(k)&&n.get(k).isValueNode())return n.get(k).asText();return null;}
    private List<String> strings(JsonNode n){List<String> out=new ArrayList<>();if(n.isArray())for(JsonNode v:n)if(v.isTextual()&&!v.asText().isBlank())out.add(v.asText());return out;}
    private List<String> dayDescription(JsonNode d){List<String> out=new ArrayList<>();for(String k:List.of("title","objective"))if(d.hasNonNull(k))out.add(d.get(k).asText());return out;}
    private String or(String s,String fallback){return s==null?fallback:s;}
}
