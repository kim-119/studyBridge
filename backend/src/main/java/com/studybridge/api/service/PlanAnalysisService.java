package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlanAnalysisDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * AI 계획 분석.
 *  - PDF 자료: 기존 deterministic 분석기(PlanTextAnalyzer) 유지
 *  - PLANNER 자료: Planner DB 구조화 데이터를 FastAPI /api/ai/planner/analyze 로 전송
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlanAnalysisService {

    private static final int MAX_RECOMMENDATIONS = 5;
    private static final String PLANNER_ANALYZE_PATH = "/api/ai/planner/analyze";

    private final PlanAnalysisRepository analysisRepository;
    private final PlanAnalysisItemRepository itemRepository;
    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final PlanTextAnalyzer analyzer;
    private final WebClient fastApiWebClient;
    private final ObjectMapper objectMapper;

    // ---------------- 분석 생성/재생성 ----------------
    @Transactional
    public PlanAnalysisDTO.Response analyze(Long userId, Long materialId) {
        long started = System.nanoTime();
        String requestId = UUID.randomUUID().toString().substring(0, 8);

        Material material = materialRepository.findById(materialId)
                .filter(m -> m.getUserId().equals(userId))
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "자료를 찾을 수 없습니다."));

        if (material.getMaterialType() == MaterialType.PLANNER) {
            return analyzePlanner(userId, material, requestId, started);
        }
        return analyzePdf(userId, material, requestId, started);
    }

    private PlanAnalysisDTO.Response analyzePdf(Long userId, Material material, String requestId, long started) {
        Map<Long, Planner> plannerMap = new LinkedHashMap<>();
        for (Planner p : plannerRepository.findByUserIdAndMaterialId(userId, material.getMaterialId())) plannerMap.put(p.getId(), p);
        for (Planner p : plannerRepository.findByUserIdAndSourceMaterialId(userId, material.getMaterialId())) plannerMap.put(p.getId(), p);
        List<Planner> planners = new ArrayList<>(plannerMap.values());

        List<PlanTextAnalyzer.SourceText> sources = new ArrayList<>();
        for (Planner p : planners) {
            String text = joinPlannerText(p);
            if (!text.isBlank()) sources.add(new PlanTextAnalyzer.SourceText("PLANNER", null, text));
        }

        int pdfLen = 0;
        if (material.getExtractedText() != null && !material.getExtractedText().isBlank()) {
            pdfLen = material.getExtractedText().length();
            sources.add(new PlanTextAnalyzer.SourceText("PDF", null, material.getExtractedText()));
        }
        if (material.getLearningContent() != null && !material.getLearningContent().isBlank()) {
            sources.add(new PlanTextAnalyzer.SourceText("PDF", null, material.getLearningContent()));
        }

        if (sources.isEmpty()) {
            log.warn("[plan-analysis] reqId={} materialId={} materialType={} EMPTY — 분석할 텍스트 없음 (plannerCount={})",
                    requestId, material.getMaterialId(), material.getMaterialType(), planners.size());
            throw new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "분석할 PDF/플래너 텍스트가 없습니다.");
        }

        PlanTextAnalyzer.Result result = analyzer.extract(sources);
        if (result.getItems().isEmpty()) {
            log.warn("[plan-analysis] reqId={} materialId={} materialType={} CONTRACT_VIOLATION — 추출 항목 0개",
                    requestId, material.getMaterialId(), material.getMaterialType());
            throw new PlanAnalysisException("PLAN_ANALYSIS_CONTRACT_VIOLATION", "분석 결과 형식이 올바르지 않습니다.");
        }

        clearPrevious(userId, material.getMaterialId());
        String sourceType = resolveSourceType(sources);
        Long plannerId = planners.isEmpty() ? null : planners.get(0).getId();

        PlanAnalysis analysis = analysisRepository.save(PlanAnalysis.builder()
                .userId(userId)
                .materialId(material.getMaterialId())
                .plannerId(plannerId)
                .sourceType(sourceType)
                .summary(buildSummary(material, result, sources.size()))
                .plannerAnalysisJson(null)
                .build());

        List<PlanAnalysisItem> saved = saveItems(analysis.getId(), toItemSpecs(result));
        List<String> recs = buildRecommendations(saved);
        analysis.setRecommendation(String.join("\n", recs));
        analysisRepository.save(analysis);

        long elapsedMs = elapsedMs(started);
        log.info("[plan-analysis] reqId={} materialId={} materialType={} plannerCount={} pdfTextLength={} sourceTextCount={} chunkCount={} sentenceCount={} itemCount={} elapsedMs={} errorCode=null",
                requestId, material.getMaterialId(), material.getMaterialType(), planners.size(), pdfLen, sources.size(),
                result.getChunkCount(), result.getSentenceCount(), saved.size(), elapsedMs);

        PlanAnalysisDTO.Response resp = buildResponse(analysis, saved, recs);
        resp.setMeta(PlanAnalysisDTO.Meta.builder()
                .plannerCount(planners.size())
                .pdfTextLength(pdfLen)
                .sourceTextCount(sources.size())
                .chunkCount(result.getChunkCount())
                .sentenceCount(result.getSentenceCount())
                .itemCount(saved.size())
                .elapsedMs(elapsedMs)
                .requestId(requestId)
                .build());
        return resp;
    }

    private PlanAnalysisDTO.Response analyzePlanner(Long userId, Material material, String requestId, long started) {
        PlannerAnalysisSource source = resolvePlannerSource(userId, material);
        if (source == null) {
            log.warn("[plan-analysis] reqId={} materialId={} materialType={} plannerId=null EMPTY — 연결된 플래너 없음",
                    requestId, material.getMaterialId(), material.getMaterialType());
            throw new PlanAnalysisException("PLAN_ANALYSIS_EMPTY", "분석할 플래너 일정 데이터가 없습니다.");
        }

        List<String> taskLines = extractPlannerTaskLines(source);
        List<String> scheduleLines = extractPlannerScheduleLines(source);
        if (taskLines.isEmpty() && scheduleLines.isEmpty() && isBlank(source.content())) {
            log.warn("[plan-analysis] reqId={} materialId={} materialType={} plannerId={} EMPTY — task/schedule 없음",
                    requestId, material.getMaterialId(), material.getMaterialType(), source.plannerId());
            throw new PlanAnalysisException("PLAN_ANALYSIS_EMPTY", "분석할 플래너 일정 데이터가 없습니다.");
        }

        PlanAnalysisDTO.PlannerAnalysisRequest request = buildPlannerRequest(source, taskLines, scheduleLines);
        @SuppressWarnings("unchecked")
        Map<String, Object> body = objectMapper.convertValue(request, new TypeReference<Map<String, Object>>() {});
        int contentLength = plannerRequestLength(body);

        log.info("[plan-analysis] reqId={} materialId={} materialType={} plannerId={} plannerTitle={} taskCount={} scheduleCount={} analysisContentLength={} fastApiEndpoint={}",
                requestId, material.getMaterialId(), material.getMaterialType(), source.plannerId(), source.title(),
                taskLines.size(), scheduleLines.size(), contentLength, PLANNER_ANALYZE_PATH);

        FastApiResult fastApi = callPlannerAnalyze(body);
        log.info("[plan-analysis] reqId={} materialId={} materialType={} plannerId={} fastApiEndpoint={} fastApiStatus={}",
                requestId, material.getMaterialId(), material.getMaterialType(), source.plannerId(),
                PLANNER_ANALYZE_PATH, fastApi.status());

        if (fastApi.status() >= 400 || fastApi.body() == null) {
            throw new PlanAnalysisException("PLAN_ANALYSIS_SAVE_FAILED", "플래너 AI 분석에 실패했습니다.");
        }

        PlanAnalysisDTO.PlannerAnalysisData plannerData = toPlannerAnalysisData(source, fastApi.body());
        clearPrevious(userId, material.getMaterialId());

        List<ItemSpec> specs = plannerItems(plannerData);
        PlanAnalysis analysis = analysisRepository.save(PlanAnalysis.builder()
                .userId(userId)
                .materialId(material.getMaterialId())
                .plannerId(source.plannerId())
                .sourceType("PLANNER")
                .summary(plannerData.getAiFeedback())
                .recommendation(String.join("\n", safeList(plannerData.getNextRecommendations())))
                .plannerAnalysisJson(writeJson(plannerData))
                .build());

        List<PlanAnalysisItem> saved = saveItems(analysis.getId(), specs);
        List<String> recs = safeList(plannerData.getNextRecommendations());
        long elapsedMs = elapsedMs(started);

        PlanAnalysisDTO.Response resp = buildResponse(analysis, saved, recs);
        resp.setPlannerAnalysisData(plannerData);
        resp.setMeta(PlanAnalysisDTO.Meta.builder()
                .plannerCount(1)
                .pdfTextLength(0)
                .sourceTextCount(1)
                .chunkCount(0)
                .sentenceCount(0)
                .itemCount(saved.size())
                .taskCount(taskLines.size())
                .scheduleCount(scheduleLines.size())
                .analysisContentLength(contentLength)
                .elapsedMs(elapsedMs)
                .requestId(requestId)
                .fastApiEndpoint(PLANNER_ANALYZE_PATH)
                .fastApiResponseStatus(fastApi.status())
                .build());
        return resp;
    }

    // ---------------- 분석 조회 ----------------
    public PlanAnalysisDTO.Response get(Long userId, Long materialId) {
        PlanAnalysis analysis = analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, materialId).orElse(null);
        if (analysis == null) {
            return PlanAnalysisDTO.Response.builder()
                    .materialId(materialId).empty(true)
                    .items(List.of()).recommendations(List.of())
                    .progress(PlanAnalysisDTO.Progress.builder().build())
                    .build();
        }
        List<PlanAnalysisItem> items = itemRepository.findByAnalysisIdOrderByOrderIndexAsc(analysis.getId());
        List<String> recs = splitRecommendation(analysis.getRecommendation());
        return buildResponse(analysis, items, recs);
    }

    // ---------------- 항목 상태 변경 (체크/지우기) ----------------
    @Transactional
    public PlanAnalysisDTO.Response updateItem(Long userId, Long itemId, Boolean completed, Boolean hidden) {
        PlanAnalysisItem item = itemRepository.findById(itemId)
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_SAVE_FAILED", "항목을 찾을 수 없습니다."));
        PlanAnalysis analysis = analysisRepository.findById(item.getAnalysisId())
                .filter(a -> a.getUserId().equals(userId))
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_SAVE_FAILED", "권한이 없습니다."));

        if (completed != null) {
            item.setCompleted(completed);
            item.setCompletedAt(completed ? LocalDateTime.now() : null);
        }
        if (hidden != null) {
            item.setHidden(hidden);
            item.setDeletedAt(hidden ? LocalDateTime.now() : null);
        }
        itemRepository.save(item);

        List<PlanAnalysisItem> items = itemRepository.findByAnalysisIdOrderByOrderIndexAsc(analysis.getId());
        return buildResponse(analysis, items, splitRecommendation(analysis.getRecommendation()));
    }

    // ---------------- 다음 학습 추천 ----------------
    @Transactional
    public PlanAnalysisDTO.RecommendationResponse recommend(Long userId, Long materialId) {
        PlanAnalysis analysis = analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, materialId)
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "먼저 AI 계획 분석을 실행해 주세요."));

        if ("PLANNER".equalsIgnoreCase(analysis.getSourceType())) {
            PlanAnalysisDTO.PlannerAnalysisData plannerData = readPlannerAnalysisData(analysis.getPlannerAnalysisJson());
            List<String> recs = plannerData != null ? safeList(plannerData.getNextRecommendations()) : List.of();
            return PlanAnalysisDTO.RecommendationResponse.builder()
                    .analysisId(analysis.getId())
                    .recommendations(recs)
                    .build();
        }

        List<PlanAnalysisItem> items = itemRepository.findByAnalysisIdOrderByOrderIndexAsc(analysis.getId());
        List<String> recs = buildRecommendations(items);
        analysis.setRecommendation(String.join("\n", recs));
        analysisRepository.save(analysis);
        return PlanAnalysisDTO.RecommendationResponse.builder().analysisId(analysis.getId()).recommendations(recs).build();
    }

    // ---------------- helpers ----------------
    private void clearPrevious(Long userId, Long materialId) {
        analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, materialId)
                .ifPresent(prev -> {
                    itemRepository.deleteByAnalysisId(prev.getId());
                    analysisRepository.delete(prev);
                });
    }

    private Planner resolvePlanner(Long userId, Material material) {
        if (material.getPlannerId() != null) {
            Planner planner = plannerRepository.findById(material.getPlannerId()).orElse(null);
            if (planner != null && planner.getUserId().equals(userId)) return planner;
        }
        List<Planner> linked = plannerRepository.findByUserIdAndMaterialId(userId, material.getMaterialId());
        if (!linked.isEmpty()) return linked.get(0);
        List<Planner> sourced = plannerRepository.findByUserIdAndSourceMaterialId(userId, material.getMaterialId());
        return sourced.isEmpty() ? null : sourced.get(0);
    }

    private PlannerAnalysisSource resolvePlannerSource(Long userId, Material material) {
        Planner planner = resolvePlanner(userId, material);
        if (planner != null) {
            return plannerSource(planner);
        }
        Map<String, Object> snapshot = readContentJson(material.getContentJson());
        if (snapshot.isEmpty()) {
            return null;
        }
        Long plannerId = asLong(snapshot.get("plannerId"), material.getPlannerId());
        String title = firstNonBlank(asString(snapshot.get("title"), null), material.getTitle(), "학습 플래너");
        return new PlannerAnalysisSource(
                plannerId,
                title,
                asString(snapshot.get("subject"), ""),
                asString(snapshot.get("content"), ""),
                firstNonBlank(asString(snapshot.get("tmi"), ""), asString(snapshot.get("memo"), "")),
                asString(snapshot.get("timeTableJson"), ""),
                asString(snapshot.get("goalTime"), ""),
                asString(snapshot.get("netStudyTime"), ""),
                asString(snapshot.get("dDay"), ""),
                asString(snapshot.get("studyType"), ""),
                asString(snapshot.get("priority"), ""),
                asString(snapshot.get("term"), ""),
                asString(snapshot.get("sourceType"), ""),
                asLong(snapshot.get("sourceMaterialId"), null),
                asLong(snapshot.get("sourceRoadmapId"), null),
                firstNonBlank(asString(snapshot.get("plannerDate"), ""), "")
        );
    }

    private PlannerAnalysisSource plannerSource(Planner planner) {
        String date = planner.getPlannerDate() != null
                ? planner.getPlannerDate().toString()
                : buildDateFromFields(planner);
        return new PlannerAnalysisSource(
                planner.getId(),
                planner.getTitle(),
                planner.getSubject(),
                planner.getContent(),
                planner.getTmi(),
                planner.getTimeTableJson(),
                planner.getGoalTime(),
                planner.getNetStudyTime(),
                planner.getDDay(),
                planner.getStudyType(),
                planner.getPriority(),
                planner.getTerm(),
                planner.getSourceType(),
                planner.getSourceMaterialId(),
                planner.getSourceRoadmapId(),
                date
        );
    }

    private PlanAnalysisDTO.PlannerAnalysisRequest buildPlannerRequest(PlannerAnalysisSource source, List<String> taskLines, List<String> scheduleLines) {
        List<String> checklist = new ArrayList<>();
        checklist.addAll(taskLines);
        checklist.addAll(scheduleLines);

        String content = joinNonBlank(
                source.content(),
                scheduleLines.isEmpty() ? "" : "집중 시간대:\n" + String.join("\n", scheduleLines));
        String todo = String.join("\n", taskLines);
        String memo = source.tmi();
        String goal = firstNonBlank(source.content(), source.goalTime(), source.title());

        Map<String, Object> plannerMeta = new LinkedHashMap<>();
        plannerMeta.put("term", source.term());
        plannerMeta.put("sourceType", source.sourceType());
        plannerMeta.put("sourceMaterialId", source.sourceMaterialId());
        plannerMeta.put("sourceRoadmapId", source.sourceRoadmapId());

        return PlanAnalysisDTO.PlannerAnalysisRequest.builder()
                .plannerId(source.plannerId())
                .title(source.title())
                .plannerTitle(source.title())
                .subject(source.subject())
                .category(source.subject())
                .content(content)
                .todo(todo)
                .memo(memo)
                .goal(goal)
                .goalTime(source.goalTime())
                .netStudyTime(source.netStudyTime())
                .dDay(source.dDay())
                .deadline(source.dDay())
                .date(source.date())
                .studyType(source.studyType())
                .priority(source.priority())
                .checklist(checklist)
                .completedTasks(List.of())
                .incompleteTasks(checklist)
                .progress(0)
                .plannerMeta(plannerMeta)
                .build();
    }

    private FastApiResult callPlannerAnalyze(Map<String, Object> body) {
        try {
            @SuppressWarnings("unchecked")
            Map<String, Object> payload = fastApiWebClient.post().uri(PLANNER_ANALYZE_PATH)
                    .bodyValue(body)
                    .exchangeToMono(resp -> resp.bodyToMono(Map.class)
                            .defaultIfEmpty(new LinkedHashMap<>())
                            .map(map -> Map.of("status", resp.statusCode().value(), "body", map)))
                    .block();
            if (payload == null) return new FastApiResult(500, null);
            return new FastApiResult((Integer) payload.get("status"), castMap(payload.get("body")));
        } catch (Exception e) {
            log.warn("[plan-analysis] planner analyze FastAPI 호출 실패: {}", e.getMessage());
            return new FastApiResult(500, null);
        }
    }

    private PlanAnalysisDTO.PlannerAnalysisData toPlannerAnalysisData(PlannerAnalysisSource source, Map<String, Object> body) {
        return PlanAnalysisDTO.PlannerAnalysisData.builder()
                .plannerId(source.plannerId())
                .title(asString(body.get("title"), source.title()))
                .keywords(toStringList(body.get("keywords")))
                .learningGoal(asString(body.get("learningGoal"), source.content()))
                .schedule(toStringList(body.get("schedule")))
                .checklist(toStringList(body.get("checklist")))
                .progress(asInteger(body.get("progress"), 0))
                .aiFeedback(asString(body.get("aiFeedback"), "저장된 플래너 자료를 기반으로 분석했습니다."))
                .scheduleAnalysis(toStringList(body.get("scheduleAnalysis")))
                .problemPoints(toStringList(body.get("problemPoints")))
                .balanceAssessment(asString(body.get("balanceAssessment"), "학습량과 일정 균형을 점검했습니다."))
                .improvementActions(toStringList(body.get("improvementActions")))
                .nextRecommendations(toStringList(body.get("nextRecommendations")))
                .unfinishedItems(toStringList(body.get("unfinishedItems")))
                .message(asString(body.get("message"), "저장된 플래너 자료를 기반으로 분석했습니다."))
                .build();
    }

    private List<ItemSpec> plannerItems(PlanAnalysisDTO.PlannerAnalysisData plannerData) {
        List<ItemSpec> specs = new ArrayList<>();
        int order = 0;
        for (String text : safeList(plannerData.getChecklist())) {
            specs.add(new ItemSpec(order++, "ACTION", text, text, "PLANNER", null, 0));
        }
        if (specs.isEmpty()) {
            for (String text : safeList(plannerData.getSchedule())) {
                specs.add(new ItemSpec(order++, "SENTENCE", text, text, "PLANNER", null, 0));
            }
        }
        return specs;
    }

    private List<ItemSpec> toItemSpecs(PlanTextAnalyzer.Result result) {
        List<ItemSpec> specs = new ArrayList<>();
        int idx = 0;
        for (PlanTextAnalyzer.ExtractedItem ei : result.getItems()) {
            specs.add(new ItemSpec(idx++, ei.getType(), ei.getText(), ei.getSourceText(),
                    ei.getSourceType(), ei.getPageNumber(), ei.getChunkIndex()));
        }
        return specs;
    }

    private List<PlanAnalysisItem> saveItems(Long analysisId, List<ItemSpec> specs) {
        List<PlanAnalysisItem> saved = new ArrayList<>();
        for (ItemSpec spec : specs) {
            saved.add(itemRepository.save(PlanAnalysisItem.builder()
                    .analysisId(analysisId)
                    .orderIndex(spec.orderIndex())
                    .type(spec.type())
                    .text(spec.text())
                    .sourceText(spec.sourceText())
                    .sourceType(spec.sourceType())
                    .pageNumber(spec.pageNumber())
                    .chunkIndex(spec.chunkIndex())
                    .completed(false)
                    .hidden(false)
                    .deleted(false)
                    .build()));
        }
        return saved;
    }

    private String joinPlannerText(Planner p) {
        StringBuilder sb = new StringBuilder();
        if (p.getContent() != null) sb.append(p.getContent()).append("\n\n");
        if (p.getTmi() != null) sb.append(p.getTmi()).append("\n");
        return sb.toString().trim();
    }

    private String resolveSourceType(List<PlanTextAnalyzer.SourceText> sources) {
        boolean planner = sources.stream().anyMatch(s -> "PLANNER".equals(s.getSourceType()));
        boolean pdf = sources.stream().anyMatch(s -> "PDF".equals(s.getSourceType()));
        if (planner && pdf) return "MIXED";
        if (planner) return "PLANNER";
        return "PDF";
    }

    private String buildSummary(Material material, PlanTextAnalyzer.Result result, int sourceCount) {
        String title = material.getTitle() != null ? material.getTitle() : "자료";
        return String.format("‘%s’의 PDF/플래너 텍스트에서 학습 항목 %d개를 추출했습니다 (소스 %d개 · 청크 %d개 · 문장 %d개). 위에서부터 순서대로 체크하며 학습을 진행하세요.",
                title, result.getItems().size(), sourceCount, result.getChunkCount(), result.getSentenceCount());
    }

    private List<String> buildRecommendations(List<PlanAnalysisItem> items) {
        return items.stream()
                .filter(i -> !i.isCompleted() && !i.isHidden() && !i.isDeleted())
                .sorted((a, b) -> {
                    int c = Integer.compare(nz(a.getChunkIndex()), nz(b.getChunkIndex()));
                    return c != 0 ? c : Integer.compare(nz(a.getOrderIndex()), nz(b.getOrderIndex()));
                })
                .limit(MAX_RECOMMENDATIONS)
                .map(i -> "다음에는 ‘" + i.getText() + "’ 부분을 먼저 정리하세요.")
                .collect(Collectors.toList());
    }

    private PlanAnalysisDTO.Response buildResponse(PlanAnalysis analysis, List<PlanAnalysisItem> allItems, List<String> recs) {
        List<PlanAnalysisDTO.Item> dtoItems = allItems.stream()
                .filter(i -> !i.isDeleted())
                .map(this::toItemDto)
                .collect(Collectors.toList());
        return PlanAnalysisDTO.Response.builder()
                .analysisId(analysis.getId())
                .materialId(analysis.getMaterialId())
                .sourceType(analysis.getSourceType())
                .summary(analysis.getSummary())
                .recommendation(analysis.getRecommendation())
                .empty(false)
                .items(dtoItems)
                .recommendations(recs)
                .plannerAnalysisData(readPlannerAnalysisData(analysis.getPlannerAnalysisJson()))
                .progress(calcProgress(allItems))
                .build();
    }

    private PlanAnalysisDTO.Item toItemDto(PlanAnalysisItem i) {
        return PlanAnalysisDTO.Item.builder()
                .id(i.getId()).orderIndex(i.getOrderIndex()).type(i.getType())
                .text(i.getText()).sourceText(i.getSourceText()).sourceType(i.getSourceType())
                .pageNumber(i.getPageNumber()).chunkIndex(i.getChunkIndex())
                .completed(i.isCompleted()).hidden(i.isHidden())
                .build();
    }

    private PlanAnalysisDTO.Progress calcProgress(List<PlanAnalysisItem> items) {
        int total = 0, completed = 0, hidden = 0, visible = 0;
        for (PlanAnalysisItem i : items) {
            if (i.isDeleted()) continue;
            total++;
            if (i.isCompleted()) completed++;
            if (i.isHidden()) hidden++;
            else visible++;
        }
        int percent = total == 0 ? 0 : (int) Math.round(completed * 100.0 / total);
        return PlanAnalysisDTO.Progress.builder()
                .totalCount(total).completedCount(completed).hiddenCount(hidden)
                .visibleCount(visible).percent(percent).build();
    }

    private List<String> splitRecommendation(String rec) {
        if (rec == null || rec.isBlank()) return List.of();
        List<String> out = new ArrayList<>();
        for (String line : rec.split("\n")) if (!line.isBlank()) out.add(line.trim());
        return out;
    }

    private PlanAnalysisDTO.PlannerAnalysisData readPlannerAnalysisData(String raw) {
        if (raw == null || raw.isBlank()) return null;
        try {
            return objectMapper.readValue(raw, PlanAnalysisDTO.PlannerAnalysisData.class);
        } catch (Exception e) {
            log.warn("plannerAnalysisJson 역직렬화 실패: {}", e.getMessage());
            return null;
        }
    }

    private List<String> extractPlannerTaskLines(PlannerAnalysisSource source) {
        List<String> out = new ArrayList<>();
        for (String piece : splitLines(source.tmi())) if (!piece.isBlank()) out.add(piece);
        for (String piece : splitLines(source.content())) if (!piece.isBlank() && !out.contains(piece)) out.add(piece);
        return out;
    }

    private List<String> extractPlannerScheduleLines(PlannerAnalysisSource source) {
        List<String> out = new ArrayList<>();
        String raw = source.timeTableJson();
        if (raw == null || raw.isBlank()) return out;
        try {
            Map<String, Object> tt = objectMapper.readValue(raw, new TypeReference<Map<String, Object>>() {});
            for (Map.Entry<String, Object> e : tt.entrySet()) {
                int hour = Integer.parseInt(e.getKey());
                Object value = e.getValue();
                if (value instanceof List<?> slots) {
                    for (int i = 0; i < slots.size(); i++) {
                        Object slot = slots.get(i);
                        if (Boolean.TRUE.equals(slot)) {
                            String start = String.format("%02d:%02d", hour, i * 10);
                            String end = String.format("%02d:%02d", hour + ((i * 10 + 10) / 60), (i * 10 + 10) % 60);
                            out.add(start + "-" + end + " 집중 학습");
                        } else if (slot instanceof String s && !s.isBlank()) {
                            out.add(String.format("%02d:%02d %s", hour, i * 10, s.trim()));
                        } else if (slot instanceof Map<?, ?> m) {
                            Object text = m.get("content");
                            if (text == null) text = m.get("text");
                            Object checked = m.get("checked");
                            if (Boolean.TRUE.equals(checked) || (text != null && !text.toString().isBlank())) {
                                out.add(String.format("%02d:%02d %s", hour, i * 10,
                                        text != null ? text.toString().trim() : "집중 학습"));
                            }
                        }
                    }
                }
            }
        } catch (Exception e) {
            log.warn("플래너 timeTableJson 파싱 실패 plannerId={}: {}", source.plannerId(), e.getMessage());
        }
        return out;
    }

    private List<String> splitLines(String raw) {
        if (raw == null || raw.isBlank()) return List.of();
        List<String> out = new ArrayList<>();
        for (String part : raw.split("[\\n,]")) {
            String s = part.trim();
            if (!s.isEmpty()) out.add(s);
        }
        return out;
    }

    private String buildDateFromFields(Planner planner) {
        if (planner.getYear() != null && planner.getMonth() != null && planner.getDay() != null) {
            return String.format("%04d-%02d-%02d", planner.getYear(), planner.getMonth(), planner.getDay());
        }
        return "";
    }

    private int plannerRequestLength(Map<String, Object> body) {
        int total = 0;
        for (String key : List.of("content", "todo", "memo", "goal")) {
            Object value = body.get(key);
            if (value != null) total += value.toString().length();
        }
        return total;
    }

    private long elapsedMs(long started) {
        return (System.nanoTime() - started) / 1_000_000;
    }

    private String writeJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            throw new PlanAnalysisException("PLAN_ANALYSIS_SAVE_FAILED", "분석 결과 저장에 실패했습니다.");
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> castMap(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : null;
    }

    private List<String> toStringList(Object value) {
        if (value instanceof List<?> list) {
            List<String> out = new ArrayList<>();
            for (Object item : list) {
                if (item != null && !item.toString().isBlank()) out.add(item.toString().trim());
            }
            return out;
        }
        return List.of();
    }

    private List<String> safeList(List<String> list) {
        return list == null ? List.of() : list;
    }

    private String asString(Object value, String fallback) {
        if (value == null) return fallback;
        String s = value.toString().trim();
        return s.isEmpty() ? fallback : s;
    }

    private Long asLong(Object value, Long fallback) {
        if (value == null) return fallback;
        if (value instanceof Number number) return number.longValue();
        try {
            return Long.parseLong(value.toString().trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private Integer asInteger(Object value, Integer fallback) {
        if (value == null) return fallback;
        if (value instanceof Number n) return n.intValue();
        try {
            return Integer.parseInt(value.toString().trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private Map<String, Object> readContentJson(String raw) {
        if (raw == null || raw.isBlank()) return Map.of();
        try {
            return objectMapper.readValue(raw, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            return Map.of();
        }
    }

    private record PlannerAnalysisSource(
            Long plannerId,
            String title,
            String subject,
            String content,
            String tmi,
            String timeTableJson,
            String goalTime,
            String netStudyTime,
            String dDay,
            String studyType,
            String priority,
            String term,
            String sourceType,
            Long sourceMaterialId,
            Long sourceRoadmapId,
            String date
    ) {
        private PlannerAnalysisSource {
            title = Objects.requireNonNullElse(title, "");
            subject = Objects.requireNonNullElse(subject, "");
            content = Objects.requireNonNullElse(content, "");
            tmi = Objects.requireNonNullElse(tmi, "");
            timeTableJson = Objects.requireNonNullElse(timeTableJson, "");
            goalTime = Objects.requireNonNullElse(goalTime, "");
            netStudyTime = Objects.requireNonNullElse(netStudyTime, "");
            dDay = Objects.requireNonNullElse(dDay, "");
            studyType = Objects.requireNonNullElse(studyType, "");
            priority = Objects.requireNonNullElse(priority, "");
            term = Objects.requireNonNullElse(term, "");
            sourceType = Objects.requireNonNullElse(sourceType, "");
            date = Objects.requireNonNullElse(date, "");
        }
    }

    private String joinNonBlank(String... values) {
        return java.util.Arrays.stream(values)
                .filter(v -> v != null && !v.isBlank())
                .collect(Collectors.joining("\n\n"));
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) return value;
        }
        return "";
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private int nz(Integer v) { return v == null ? 0 : v; }

    private record ItemSpec(int orderIndex, String type, String text, String sourceText,
                            String sourceType, Integer pageNumber, Integer chunkIndex) { }

    private record FastApiResult(int status, Map<String, Object> body) { }
}
