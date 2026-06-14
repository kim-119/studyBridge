package com.studybridge.api.service;

import com.studybridge.api.dto.PlanAnalysisDTO;
import com.studybridge.api.entity.Material;
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

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * AI 계획 분석 — PDF/플래너 텍스트를 문장/행동 단위로 분해하여 체크리스트로 저장/조회/갱신한다.
 *
 * 분석은 원격 FastAPI(블랙박스, 수정 불가)에 의존하지 않고 Spring 내부의 결정적 분석기
 * {@link PlanTextAnalyzer} 를 사용한다. 입력은 반드시 PDF/저장 플래너 텍스트 기반이며,
 * 일반 지식으로 항목을 생성하지 않는다(요구사항 [7]/[9] 의 deterministic fallback 허용 범위).
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlanAnalysisService {

    private final PlanAnalysisRepository analysisRepository;
    private final PlanAnalysisItemRepository itemRepository;
    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final PlanTextAnalyzer analyzer;

    private static final int MAX_RECOMMENDATIONS = 5;

    // ---------------- 분석 생성/재생성 ----------------
    @Transactional
    public PlanAnalysisDTO.Response analyze(Long userId, Long materialId) {
        long started = System.nanoTime();
        String requestId = UUID.randomUUID().toString().substring(0, 8);

        Material material = materialRepository.findById(materialId)
                .filter(m -> m.getUserId().equals(userId))
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "자료를 찾을 수 없습니다."));

        // 1) 연결된 플래너 텍스트 수집 (materialId 직접 연결 + sourceMaterialId 로드맵 연결)
        Map<Long, Planner> plannerMap = new LinkedHashMap<>();
        for (Planner p : plannerRepository.findByUserIdAndMaterialId(userId, materialId)) plannerMap.put(p.getId(), p);
        for (Planner p : plannerRepository.findByUserIdAndSourceMaterialId(userId, materialId)) plannerMap.put(p.getId(), p);
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
            log.warn("[plan-analysis] reqId={} materialId={} EMPTY — 분석할 텍스트 없음 (plannerCount={})", requestId, materialId, planners.size());
            throw new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "분석할 PDF/플래너 텍스트가 없습니다.");
        }

        // 2) 결정적 분석
        PlanTextAnalyzer.Result result = analyzer.extract(sources);
        if (result.getItems().isEmpty()) {
            log.warn("[plan-analysis] reqId={} materialId={} CONTRACT_VIOLATION — 추출 항목 0개", requestId, materialId);
            throw new PlanAnalysisException("PLAN_ANALYSIS_CONTRACT_VIOLATION", "분석 결과 형식이 올바르지 않습니다.");
        }

        // 3) 기존 분석 제거 후 재저장
        analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, materialId)
                .ifPresent(prev -> {
                    itemRepository.deleteByAnalysisId(prev.getId());
                    analysisRepository.delete(prev);
                });

        String sourceType = resolveSourceType(sources);
        Long plannerId = planners.isEmpty() ? null : planners.get(0).getId();

        PlanAnalysis analysis = analysisRepository.save(PlanAnalysis.builder()
                .userId(userId)
                .materialId(materialId)
                .plannerId(plannerId)
                .sourceType(sourceType)
                .summary(buildSummary(material, result, sources.size()))
                .build());

        List<PlanAnalysisItem> saved = new ArrayList<>();
        int idx = 0;
        for (PlanTextAnalyzer.ExtractedItem ei : result.getItems()) {
            saved.add(itemRepository.save(PlanAnalysisItem.builder()
                    .analysisId(analysis.getId())
                    .orderIndex(idx++)
                    .type(ei.getType())
                    .text(ei.getText())
                    .sourceText(ei.getSourceText())
                    .sourceType(ei.getSourceType())
                    .pageNumber(ei.getPageNumber())
                    .chunkIndex(ei.getChunkIndex())
                    .completed(false).hidden(false).deleted(false)
                    .build()));
        }

        List<String> recs = buildRecommendations(saved);
        analysis.setRecommendation(String.join("\n", recs));
        analysisRepository.save(analysis);

        long elapsedMs = (System.nanoTime() - started) / 1_000_000;
        log.info("[plan-analysis] reqId={} materialId={} plannerCount={} pdfTextLength={} sourceTextCount={} chunkCount={} sentenceCount={} itemCount={} elapsedMs={} errorCode=null",
                requestId, materialId, planners.size(), pdfLen, sources.size(),
                result.getChunkCount(), result.getSentenceCount(), saved.size(), elapsedMs);

        PlanAnalysisDTO.Response resp = buildResponse(analysis, saved, recs);
        resp.setMeta(PlanAnalysisDTO.Meta.builder()
                .plannerCount(planners.size()).pdfTextLength(pdfLen).sourceTextCount(sources.size())
                .chunkCount(result.getChunkCount()).sentenceCount(result.getSentenceCount())
                .itemCount(saved.size()).elapsedMs(elapsedMs).requestId(requestId).build());
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

    // ---------------- 다음 학습 추천 (미완료 항목 기반) ----------------
    @Transactional
    public PlanAnalysisDTO.RecommendationResponse recommend(Long userId, Long materialId) {
        PlanAnalysis analysis = analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, materialId)
                .orElseThrow(() -> new PlanAnalysisException("PLAN_ANALYSIS_TEXT_EMPTY", "먼저 AI 계획 분석을 실행해 주세요."));
        List<PlanAnalysisItem> items = itemRepository.findByAnalysisIdOrderByOrderIndexAsc(analysis.getId());
        List<String> recs = buildRecommendations(items);
        analysis.setRecommendation(String.join("\n", recs));
        analysisRepository.save(analysis);
        return PlanAnalysisDTO.RecommendationResponse.builder().analysisId(analysis.getId()).recommendations(recs).build();
    }

    // ---------------- helpers ----------------
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

    /** 미완료(미완료 & 미숨김 & 미삭제) 항목을 청크 순서대로 최대 5개 추천. */
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
        // 삭제되지 않은 모든 항목을 반환(숨김 포함, hidden 플래그로 구분).
        // → 체크리스트는 프론트에서 !hidden 필터, 진행률 탭은 전체 기준 chunk/page 집계에 사용.
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

    /**
     * 진행률 계산.
     *  - totalCount   = deleted=false 항목 수
     *  - completedCount = completed=true (hidden 이어도 포함 → "지우면 퍼센트 채움" 요구 충족)
     *  - percent = round(completedCount / totalCount * 100)
     */
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

    private int nz(Integer v) { return v == null ? 0 : v; }
}
