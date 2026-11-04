package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.ai.quality.SegmentedQualityGate;
import com.studybridge.api.dto.StudyNoteAnalysisDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialStudyNoteAnalysis;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialStudyNoteAnalysisRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 자료(PDF) 전공 분야·핵심 객체 중심 학습 노트(AI 핵심 요약 노트) 생성/조회.
 *  - ai07 수정 불가 → 기존 범용 LLM 엔드포인트 /api/ai/multi-chat 재사용(엄격 JSON 프롬프트).
 *  - PDF 업로드/추출 성공 후 백그라운드로 생성. 업로드 성공과 분석 성공은 분리(분석 실패해도 자료는 유지).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StudyNoteAnalysisService {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final String MODE = "DOMAIN_OBJECT_CENTERED_STUDY_NOTE";
    private static final String DISCLAIMER =
            "이 결과는 강의자료 기반 학습 보조 설명이며, 의료 진단·법률 자문·투자 자문·전문 감정이 아닙니다.";
    private static final List<String> DEFAULT_LIMITATIONS = List.of(
            "PDF/OCR/캡션/표 텍스트 기반의 학습 보조 분석이며, 전문가 판단을 대체하지 않습니다.",
            "불명확한 이미지나 수식은 인식 결과 확인이 필요합니다.");

    // 분야 코드 → 한글 라벨 (ai07 domainLabel 이 비었을 때만 사용하는 폴백 매핑, ai07 보고 코드 기준)
    private static final Map<String, String> DOMAIN_LABELS = Map.ofEntries(
            Map.entry("MATH", "수학"),
            Map.entry("PHYSICS", "물리"),
            Map.entry("CHEMISTRY", "화학"),
            Map.entry("BIOLOGY_MICROBIOLOGY", "생명과학/미생물"),
            Map.entry("MEDICINE_NURSING", "의학/간호"),
            Map.entry("COMPUTER_SCIENCE", "컴퓨터공학"),
            Map.entry("DATA_STATISTICS", "데이터분석/통계"),
            Map.entry("ELECTRONICS", "전자공학"),
            Map.entry("MECHANICAL_ENGINEERING", "기계공학"),
            Map.entry("ARCHITECTURE_CIVIL", "건축/토목"),
            Map.entry("EARTH_GEOLOGY", "지구과학/지질"),
            Map.entry("BUSINESS_ECONOMICS", "경영/경제"),
            Map.entry("LAW_PUBLIC_ADMIN", "법학/행정"),
            Map.entry("GENERAL", "일반 전공자료"));

    private final MaterialRepository materialRepository;
    private final MaterialStudyNoteAnalysisRepository repository;
    private final WebClient fastApiWebClient;

    @Value("${ai.study-note.timeout-seconds:120}")
    private long timeoutSeconds;

    // Global Response Quality Gate(기본 OFF). 생성자 시그니처를 바꾸지 않도록 setter 주입(없으면 OFF).
    private AiResponseQualityGate qualityGate;

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    private boolean gateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    /** 세그먼트 예산(문자). ai07 본문 256KB 제한 안에 한글(UTF-8 3바이트) 세그먼트 + 근거가 들어가도록. */
    static final int NOTE_SEGMENT_BUDGET_CHARS = 20_000;
    static final int NOTE_EVIDENCE_MAX_CHARS = 16_000;
    static final String REDACTED_MESSAGE = "AI 핵심 요약 노트가 품질 검증을 통과한 기록이 없어 내용을 표시하지 않았습니다.";
    static final String GATE_REJECTED_MESSAGE = "AI 핵심 요약 노트가 품질 기준을 통과하지 못해 저장하지 않았습니다.";
    static final String GATE_UNAVAILABLE_MESSAGE = "지금은 AI 핵심 요약 노트의 품질을 확인할 수 없어 저장하지 않았습니다.";

    // 분석 대상 여부: 파일 기반(PDF)만. 오답노트/학습일지/플래너는 대상 아님.
    private boolean isAnalyzable(Material m) {
        return m != null && m.getMaterialType() == MaterialType.PDF;
    }

    /** 업로드 직후 PENDING 행 생성(이미 있으면 무시). */
    @Transactional
    public void initPending(Material material) {
        if (!isAnalyzable(material)) return;
        if (repository.findByMaterialId(material.getMaterialId()).isPresent()) return;
        repository.save(MaterialStudyNoteAnalysis.builder()
                .materialId(material.getMaterialId())
                .userId(material.getUserId())
                .status("PENDING")
                .disclaimer(DISCLAIMER)
                .build());
    }

    /** 추출 성공 콜백/지연 트리거에서 비동기로 호출. 추출 텍스트 기반으로 학습 노트를 생성한다. */
    @Async
    public void analyzeAsync(Long materialId) {
        try {
            analyze(materialId);
        } catch (Exception e) {
            log.warn("[STUDY_NOTE] analyzeAsync 실패 materialId={} err={}", materialId, e.getMessage());
        }
    }

    @Transactional
    public void analyze(Long materialId) {
        Material material = materialRepository.findById(materialId).orElse(null);
        if (material == null || !isAnalyzable(material)) return;

        MaterialStudyNoteAnalysis row = repository.findByMaterialId(materialId)
                .orElseGet(() -> MaterialStudyNoteAnalysis.builder()
                        .materialId(materialId).userId(material.getUserId())
                        .status("PENDING").disclaimer(DISCLAIMER).build());

        String text = material.getExtractedText();
        if (text == null || text.trim().length() < 30) {
            row.setStatus("FAILED");
            row.setDisclaimer(DISCLAIMER);
            row.setErrorMessage("PDF 텍스트/OCR/캡션/표 정보가 부족하여 학습 노트를 생성할 수 없습니다.");
            repository.save(row);
            log.info("[STUDY_NOTE] FAILED(no-text) materialId={}", materialId);
            return;
        }

        String prevStatus = row.getStatus();
        String prevQuality = row.getQualityStatus();
        row.setStatus("RUNNING");
        row.setDisclaimer(DISCLAIMER);
        row.setErrorMessage(null);
        repository.save(row);

        if (gateOn()) {
            try {
                analyzeGated(material, row, text, prevStatus, prevQuality);
            } catch (Exception e) {
                // 예기치 못한 오류도 초안 없이 끝낸다(RUNNING 고착 방지). 이전 승인 노트가 있으면 그대로 둔다.
                row.setStatus("APPROVED".equals(prevQuality) && "SUCCESS".equals(prevStatus) ? "SUCCESS" : "FAILED");
                row.setErrorMessage("SUCCESS".equals(row.getStatus()) ? null : "AI 핵심 요약 노트를 생성하지 못했습니다.");
                repository.save(row);
                log.warn("[STUDY_NOTE] gated FAILED materialId={} err={}", materialId, e.getClass().getSimpleName());
            }
            return;
        }

        try {
            // ai07 major-analysis/note 는 LLM/위키/타임아웃/빈 입력에도 200 + 구조화 fallback 을 반환한다.
            JsonNode json = callMajorAnalysis(material);
            if (json == null) {
                throw new IllegalStateException("AI 응답이 비어 있습니다.");
            }
            applyJson(row, json);
            // 정보 부족 fallback 판정: domain == GENERAL 이고 keywords 가 비어 있음 (통신 실패 아님 → SUCCESS 유지)
            boolean fallback = "GENERAL".equalsIgnoreCase(nz(row.getDomain())) && isEmptyJsonArray(row.getKeywordsJson());
            row.setFallback(fallback);
            row.setFallbackReason(fallback ? "INSUFFICIENT_INPUT" : null);
            row.setStatus("SUCCESS");
            row.setErrorMessage(null);
            row.setQualityStatus(null); // 게이트 OFF 생성분 = 미검증(나중에 게이트를 켜면 가림)
            repository.save(row);
            log.info("[STUDY_NOTE] SUCCESS materialId={} domain={} coreObject={} fallback={}",
                    materialId, row.getDomain(), row.getCoreObject(), fallback);
        } catch (Exception e) {
            // 통신 실패/타임아웃/파싱 실패만 FAILED. PDF 자료·업로드는 그대로 유지.
            row.setStatus("FAILED");
            row.setFallback(false);
            row.setErrorMessage("AI 핵심 요약 노트를 생성하지 못했습니다.");
            repository.save(row);
            log.warn("[STUDY_NOTE] FAILED materialId={} err={}", materialId, e.getMessage());
        }
    }

    private String nz(String s) { return s == null ? "" : s; }

    private boolean isEmptyJsonArray(String json) {
        if (json == null || json.isBlank()) return true;
        try {
            JsonNode n = MAPPER.readTree(json);
            return !n.isArray() || n.size() == 0;
        } catch (Exception e) { return true; }
    }

    // ── 조회(소유권 검증) ────────────────────────────────────────────────
    // 행이 없으면: 분석 대상이고 텍스트가 있으면 비동기 생성 트리거 후 RUNNING, 텍스트 없으면 PENDING, 대상 아니면 null.
    @Transactional
    public StudyNoteAnalysisDTO get(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 권한이 없습니다.");
        }
        if (!isAnalyzable(material)) {
            return null; // PDF 외(플래너/학습일지/오답노트)는 학습 노트 대상 아님 → 프론트는 기존 요약 표시
        }

        MaterialStudyNoteAnalysis row = repository.findByMaterialId(materialId).orElse(null);
        boolean hasText = material.getExtractedText() != null && material.getExtractedText().trim().length() >= 30;

        if (row == null) {
            // 레거시/누락분: 텍스트가 있으면 지금 생성 트리거
            initPending(material);
            if (hasText) {
                analyzeAsync(materialId);
                return placeholder(materialId, "RUNNING");
            }
            return placeholder(materialId, "PENDING");
        }

        // PENDING인데 텍스트가 준비됐으면 생성 트리거(추출 콜백 누락 대비)
        if ("PENDING".equals(row.getStatus()) && hasText) {
            analyzeAsync(materialId);
            return placeholder(materialId, "RUNNING");
        }
        return display(row);
    }

    /** 게이트 ON: 승인 기록(quality_status=APPROVED)이 없는 행은 AI 필드를 가린다(식별자·상태·고정 고지만). OFF 는 기존 그대로. */
    private StudyNoteAnalysisDTO display(MaterialStudyNoteAnalysis r) {
        if (!gateOn()) {
            return toDTO(r);
        }
        if ("APPROVED".equals(r.getQualityStatus())) {
            return toDTOBuilder(r).qualityStatus("APPROVED").build();
        }
        boolean success = "SUCCESS".equals(r.getStatus());
        return StudyNoteAnalysisDTO.builder()
                .materialId(r.getMaterialId())
                // 미검증 SUCCESS 는 SUCCESS 로 내보내지 않는다(화면이 SUCCESS 일 때만 노트를 렌더) — 기존 요약 폴백이 보이게.
                .status(success ? "UNVERIFIED" : r.getStatus())
                .mode(MODE)
                .disclaimer(DISCLAIMER)
                .fallback(false)
                .keywords(List.of()).coreContents(List.of()).detailedCoreContents(List.of())
                .pageSummaries(List.of())
                .studyPoints(List.of()).aiStudyQuestions(List.of()).wikiSummaries(List.of())
                .limitations(List.of())
                .errorMessage(success ? REDACTED_MESSAGE : r.getErrorMessage())
                .qualityStatus(r.getQualityStatus())
                .qualityRedacted(hasAiContent(r) ? Boolean.TRUE : null)
                .build();
    }

    private static boolean hasAiContent(MaterialStudyNoteAnalysis r) {
        return r.getDomain() != null || r.getCoreObject() != null || r.getDocumentOverview() != null
                || nonEmptyJson(r.getKeywordsJson()) || nonEmptyJson(r.getCoreContentsJson()) || nonEmptyJson(r.getDetailedCoreContentsJson())
                || nonEmptyJson(r.getPageSummariesJson()) || nonEmptyJson(r.getStudyPointsJson()) || nonEmptyJson(r.getAiStudyQuestionsJson())
                || nonEmptyJson(r.getWikiSummariesJson());
    }

    private static boolean nonEmptyJson(String json) {
        return json != null && !json.isBlank() && !"[]".equals(json.trim());
    }

    // ── 품질 게이트 생성 경로(Phase D) ─────────────────────────────────────────

    /**
     * 생성 → 사용자에게 보일 노트 전체(toDTO 로 표시되는 AI 필드 전부)를 분할 평가(GENERAL_EXPLANATION/text, 근거 = 자료 원문 페이지별 —
     * ai07 는 페이지 근거를 주지 않는다) → 거절 시 재생성 ≤2 → 전 세그먼트 승인분만 행에 반영(quality_status=APPROVED).
     * 거절/평가 불가면 초안을 저장하지 않는다: 이전에 승인된 노트가 있으면 그대로 두고(SUCCESS 복원), 없으면 FAILED + 고정 사유.
     */
    private void analyzeGated(Material material, MaterialStudyNoteAnalysis row, String text, String prevStatus, String prevQuality) {
        Long materialId = material.getMaterialId();
        String rid = "note-" + materialId + "-" + java.util.UUID.randomUUID().toString().substring(0, 8);
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.GENERAL_EXPLANATION,
                ResponseQualityV1.OutputKind.TEXT,
                "학습 자료 '" + nz(material.getTitle()) + "' 의 핵심 내용을 전공 분야·핵심 객체 중심 학습 노트(개요·핵심 내용·페이지별 요약·"
                        + "학습 포인트·예상 질문)로 시험 대비용으로 정리해 주세요.",
                pageEvidence(materialId, text, NOTE_EVIDENCE_MAX_CHARS),
                new ResponseQualityV1.Constraints(List.of(materialId), null, null, null, null, null, null, false, false, null, null, null, null,
                        null, null), null);
        SegmentedQualityGate.Outcome<MaterialStudyNoteAnalysis> outcome = new SegmentedQualityGate(qualityGate).generateApproved(spec,
                (attempt, previous) -> {
                    JsonNode json;
                    try {
                        json = callMajorAnalysis(material);
                    } catch (Exception e) {
                        log.warn("[STUDY_NOTE] gated 생성 실패 materialId={} attempt={} err={}", materialId, attempt, e.getClass().getSimpleName());
                        throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
                    }
                    if (json == null) {
                        throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
                    }
                    MaterialStudyNoteAnalysis cand = MaterialStudyNoteAnalysis.builder()
                            .materialId(materialId).userId(material.getUserId()).status("SUCCESS").disclaimer(DISCLAIMER).build();
                    applyJson(cand, json);
                    boolean fallback = "GENERAL".equalsIgnoreCase(nz(cand.getDomain())) && isEmptyJsonArray(cand.getKeywordsJson());
                    cand.setFallback(fallback);
                    cand.setFallbackReason(fallback ? "INSUFFICIENT_INPUT" : null);
                    return cand;
                }, cand -> visibleJson(toDTO(cand)), noteSegmenter(NOTE_SEGMENT_BUDGET_CHARS), null);
        if (outcome.approved()) {
            MaterialStudyNoteAnalysis c = outcome.value();
            copyNote(c, row);
            row.setStatus("SUCCESS");
            row.setErrorMessage(null);
            row.setQualityStatus("APPROVED");
            repository.save(row);
            log.info("[STUDY_NOTE] SUCCESS(gated) materialId={} rid={} segments={} score={} attempts={}", materialId, rid,
                    outcome.result().manifest().segments().size(), outcome.result().decision().score(), outcome.result().decision().attempts());
            return;
        }
        GateDecision d = outcome.result() != null ? outcome.result().decision() : null;
        String code = d != null ? d.errorCode() : GateDecision.REJECTED;
        if ("APPROVED".equals(prevQuality) && "SUCCESS".equals(prevStatus)) {
            row.setStatus("SUCCESS"); // 이전 승인 노트 유지(덮어쓰지 않음)
            row.setErrorMessage(null);
        } else {
            row.setStatus("FAILED");
            row.setErrorMessage(GateDecision.UNAVAILABLE.equals(code) ? GATE_UNAVAILABLE_MESSAGE : GATE_REJECTED_MESSAGE);
        }
        repository.save(row);
        log.warn("[STUDY_NOTE] gated 미승인 materialId={} rid={} code={} reasons={} violations={} → 초안 미저장", materialId, rid, code,
                d != null ? d.reasonCodes() : null, outcome.result() != null ? outcome.result().violations() : null);
    }

    private static void copyNote(MaterialStudyNoteAnalysis from, MaterialStudyNoteAnalysis to) {
        to.setFallback(from.getFallback());
        to.setFallbackReason(from.getFallbackReason());
        to.setDomain(from.getDomain());
        to.setDomainLabel(from.getDomainLabel());
        to.setCoreObject(from.getCoreObject());
        to.setCoreObjectLabel(from.getCoreObjectLabel());
        to.setDisclaimer(from.getDisclaimer());
        to.setDocumentOverview(from.getDocumentOverview());
        to.setKeywordsJson(from.getKeywordsJson());
        to.setCoreContentsJson(from.getCoreContentsJson());
        to.setDetailedCoreContentsJson(from.getDetailedCoreContentsJson());
        to.setPageSummariesJson(from.getPageSummariesJson());
        to.setStudyPointsJson(from.getStudyPointsJson());
        to.setAiStudyQuestionsJson(from.getAiStudyQuestionsJson());
        to.setWikiSummariesJson(from.getWikiSummariesJson());
        to.setLimitationsJson(from.getLimitationsJson());
    }

    /** 평가 대상 = 화면에 나가는 AI 필드 전부(표시 변환 toDTO 를 거친 값 그대로). 상태·모드 같은 서버 메타는 제외. */
    static JsonNode visibleJson(StudyNoteAnalysisDTO dto) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("domain", dto.getDomain());
        m.put("domainLabel", dto.getDomainLabel());
        m.put("coreObject", dto.getCoreObject());
        m.put("coreObjectLabel", dto.getCoreObjectLabel());
        m.put("disclaimer", dto.getDisclaimer());
        m.put("documentOverview", dto.getDocumentOverview());
        m.put("keywords", dto.getKeywords());
        m.put("coreContents", dto.getCoreContents());
        m.put("detailedCoreContents", dto.getDetailedCoreContents());
        m.put("pageSummaries", dto.getPageSummaries());
        m.put("studyPoints", dto.getStudyPoints());
        m.put("aiStudyQuestions", dto.getAiStudyQuestions());
        m.put("wikiSummaries", dto.getWikiSummaries());
        m.put("limitations", dto.getLimitations());
        return MAPPER.valueToTree(m);
    }

    /** 최상위 스칼라 필드와 배열 원소를 순서대로 예산 이하 세그먼트로 묶는다(JSON Pointer, 결정적). */
    static SegmentedQualityGate.Segmenter noteSegmenter(int budget) {
        return full -> {
            List<String> units = new ArrayList<>();
            List<Integer> sizes = new ArrayList<>();
            for (java.util.Iterator<Map.Entry<String, JsonNode>> it = full.fields(); it.hasNext(); ) {
                Map.Entry<String, JsonNode> e = it.next();
                String p = "/" + e.getKey().replace("~", "~0").replace("/", "~1");
                JsonNode v = e.getValue();
                if (v.isArray() && v.size() > 0) {
                    for (int i = 0; i < v.size(); i++) {
                        units.add(p + "/" + i);
                        sizes.add(v.get(i).toString().length() + p.length() + 8);
                    }
                } else {
                    units.add(p);
                    sizes.add(v.toString().length() + p.length() + 4);
                }
            }
            List<SegmentedQualityGate.SegmentPlan> out = new ArrayList<>();
            List<String> cur = new ArrayList<>();
            int size = 0;
            for (int u = 0; u < units.size(); u++) {
                if (!cur.isEmpty() && size + sizes.get(u) > budget) {
                    out.add(new SegmentedQualityGate.SegmentPlan("n" + out.size(), List.copyOf(cur)));
                    cur.clear();
                    size = 0;
                }
                cur.add(units.get(u));
                size += sizes.get(u);
            }
            if (!cur.isEmpty()) {
                out.add(new SegmentedQualityGate.SegmentPlan("n" + out.size(), List.copyOf(cur)));
            }
            return out;
        };
    }

    /**
     * 자료 원문 근거(PDF_ORIGINAL, 이 자료만). 추출기가 넣은 form-feed(\f) 페이지 경계가 있으면 ai07 에 보낸 pageTexts 와 같은 번호로
     * 페이지 근거를 만든다(페이지당 균등 예산, 최대 32개). 경계가 없으면 앞에서부터 청크. 원문을 넘는 부분은 근거 없음(보수적 판정).
     */
    static List<ResponseQualityV1.GroundingEvidence> pageEvidence(Long materialId, String text, int maxTotal) {
        if (text == null || text.isBlank()) {
            return List.of();
        }
        String[] parts = text.split("\f");
        if (parts.length <= 1) {
            return AiResponseQualityGate.pdfEvidence(materialId, text, 4000, maxTotal);
        }
        List<int[]> pages = new ArrayList<>(); // [pageNo, partIndex]
        for (int i = 0, page = 1; i < parts.length; i++, page++) {
            if (parts[i] != null && !parts[i].isBlank()) {
                pages.add(new int[]{page, i});
            }
        }
        int n = Math.min(pages.size(), ResponseQualityV1.MAX_EVIDENCE_ITEMS);
        if (n == 0) {
            return List.of();
        }
        int per = Math.max(200, Math.min(ResponseQualityV1.MAX_EVIDENCE_CHARS, maxTotal / n));
        List<ResponseQualityV1.GroundingEvidence> out = new ArrayList<>();
        int total = 0;
        for (int k = 0; k < n && total < maxTotal; k++) {
            String body = parts[pages.get(k)[1]].strip();
            String chunk = body.length() > per ? body.substring(0, per) : body;
            out.add(new ResponseQualityV1.GroundingEvidence(null, "PDF_ORIGINAL", materialId, null, null, pages.get(k)[0],
                    "m" + materialId + "-p" + pages.get(k)[0], chunk));
            total += chunk.length();
        }
        return out;
    }

    private StudyNoteAnalysisDTO placeholder(Long materialId, String status) {
        return StudyNoteAnalysisDTO.builder()
                .materialId(materialId).status(status).mode(MODE).disclaimer(DISCLAIMER)
                .fallback(false)
                .keywords(List.of()).coreContents(List.of()).detailedCoreContents(List.of())
                .pageSummaries(List.of())
                .studyPoints(List.of()).aiStudyQuestions(List.of()).wikiSummaries(List.of())
                .limitations(List.of())
                .build();
    }

    // ── AI 호출: ai07 /api/ai/major-analysis/note (React→Spring→ai07) ─────
    @SuppressWarnings({"rawtypes", "unchecked"})
    private JsonNode callMajorAnalysis(Material material) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("materialId", material.getMaterialId());
        body.put("materialTitle", material.getTitle() == null ? "" : material.getTitle());
        body.put("subject", material.getKeywords() == null ? "" : material.getKeywords());
        body.put("inputType", "PDF");
        // PDF 원본 S3 key 를 함께 전달한다(additive). ai07 가 s3Key 로 원본 PDF 를 S3 에서 직접 로드하여
        // 페이지별 텍스트 추출 + 이미지 렌더링 + OCR + 페이지별 요약(이미지 전용/이미지 포함 PDF)을 수행할 수 있게 한다.
        // 값이 없으면(빈 문자열) ai07 는 기존 pageTexts 기반 텍스트 분석으로 폴백한다.
        String s3Key = resolveMaterialS3Key(material);
        body.put("s3Key", s3Key);
        log.info("Major analysis request includes s3Key: {}", s3Key != null && !s3Key.isBlank());
        // 페이지 구분(form-feed)이 있으면 페이지별 {page,text}로 분리해 전달(ai07 페이지별 분리/정렬 정확도↑)
        body.put("pageTexts", buildPageTexts(material.getExtractedText()));
        // 전체 페이지 수(총 페이지 수)를 함께 전달한다. pageTexts 는 텍스트가 있는 페이지만 포함될 수 있어
        // 마지막/후반 페이지가 이미지·빈 텍스트면 ai07 가 최대 page marker 만으로 총 페이지 수를 과소 추정할 수 있다.
        // → 추출기가 페이지 경계마다 삽입한 form-feed(\f)를 기준으로 총 페이지 수를 보존해 보낸다(텍스트 유무 무관).
        Integer pageCount = resolvePageCount(material.getExtractedText());
        if (pageCount != null && pageCount > 0) {
            body.put("pageCount", pageCount);
        }
        // OCR 파이프라인 미구현 → ocrTexts 등은 빈 배열(이미지 전용 페이지는 ai07에서 INSUFFICIENT 로 정상 처리).
        body.put("captions", List.of());
        body.put("ocrTexts", List.of());
        body.put("tables", List.of());
        body.put("imageDescriptions", List.of());
        body.put("userQuestion", "이 PDF의 핵심 내용을 시험 대비용으로 정리해줘.");
        body.put("maxWikiResults", 5);

        Map resp = fastApiWebClient.post().uri("/api/ai/major-analysis/note")
                .bodyValue(body).retrieve().bodyToMono(Map.class)
                .block(Duration.ofSeconds(timeoutSeconds));
        return resp == null ? null : MAPPER.valueToTree(resp);
    }

    // 자료의 PDF 원본 S3 key 를 도출한다(하드코딩 금지, 실제 저장 필드 기준).
    //  - 업로드 시 Material.s3FileUrl 에는 "전체 URL" 이 아니라 S3 object key 가 저장된다
    //    (MaterialService: .s3FileUrl(s3Key); presigned URL 생성도 이 값을 key 로 사용).
    //  - 혹시 전체 URL(https://...amazonaws.com/<key>) 형태가 들어와도 안전하게 path key 만 추출한다.
    //  - 값이 없으면 빈 문자열을 반환한다(ai07 가 pageTexts 기반으로 폴백, 전체 실패 방지).
    private String resolveMaterialS3Key(Material material) {
        if (material == null) return "";
        String raw = material.getS3FileUrl();
        if (raw == null || raw.isBlank()) {
            raw = material.getStoredFileName();
        }
        if (raw == null || raw.isBlank()) return "";
        String value = raw.trim();
        int schemeIdx = value.indexOf("://");
        if (schemeIdx >= 0) {
            // 전체 URL → host 이후의 path 만 key 로 사용
            int pathStart = value.indexOf('/', schemeIdx + 3);
            value = pathStart >= 0 ? value.substring(pathStart + 1) : "";
            int queryIdx = value.indexOf('?');
            if (queryIdx >= 0) value = value.substring(0, queryIdx); // presigned 쿼리 제거
        }
        return value;
    }

    // 추출 텍스트의 form-feed(\f) 페이지 경계로 총 페이지 수를 도출한다.
    //  - 빈/이미지 전용 페이지의 경계도 그대로 보존되므로, "텍스트가 있는 페이지 수(pageTexts.size)" 와 달리
    //    마지막 페이지가 비어 있어도 총 페이지 수를 과소 추정하지 않는다.
    //  - 경계(\f)가 전혀 없으면(단일 blob/Vision OCR 결과 등) 총 페이지 수를 신뢰할 수 없으므로 null 을 반환해
    //    body 에 pageCount 를 넣지 않는다(가짜 값 생성 금지).
    //  - 전체 extractedText 기준(payload 상한 truncation 전)으로 센다.
    private Integer resolvePageCount(String text) {
        if (text == null || text.isBlank()) return null;
        int formFeeds = 0;
        for (int i = 0; i < text.length(); i++) {
            if (text.charAt(i) == '\f') formFeeds++;
        }
        if (formFeeds == 0) return null; // 페이지 경계 정보 없음 → 총 페이지 수 미상
        int count = formFeeds + 1;       // 경계 N개 → 페이지 N+1개
        return count > 0 ? count : null;
    }

    // 추출 텍스트를 페이지별 {page,text} 배열로. form-feed(\f) 구분이 있으면 페이지로 분리, 없으면 단일 페이지.
    private List<Map<String, Object>> buildPageTexts(String text) {
        List<Map<String, Object>> pages = new ArrayList<>();
        if (text == null || text.isBlank()) return pages;
        String t = text.length() > 60000 ? text.substring(0, 60000) : text; // 전체 상한
        String[] parts = t.split("\f");
        if (parts.length <= 1) {
            String body = t.length() > 15000 ? t.substring(0, 15000) : t;
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("page", 1); p.put("text", body);
            pages.add(p);
            return pages;
        }
        int page = 1;
        for (String part : parts) {
            if (pages.size() >= 60) break; // 페이지 수 상한(페이로드 방어)
            String body = part == null ? "" : part.trim();
            if (body.isEmpty()) { page++; continue; }
            if (body.length() > 8000) body = body.substring(0, 8000);
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("page", page++); p.put("text", body);
            pages.add(p);
        }
        if (pages.isEmpty()) {
            Map<String, Object> p = new LinkedHashMap<>();
            p.put("page", 1); p.put("text", t.length() > 15000 ? t.substring(0, 15000) : t);
            pages.add(p);
        }
        return pages;
    }

    private void applyJson(MaterialStudyNoteAnalysis row, JsonNode j) {
        String domain = textOf(j, "domain");
        row.setDomain(domain);
        // ai07 domainLabel 우선, 비었으면 코드 매핑 폴백
        String label = textOf(j, "domainLabel");
        row.setDomainLabel((label != null && !label.isBlank()) ? label
                : DOMAIN_LABELS.getOrDefault(domain == null ? "" : domain.trim().toUpperCase(), "일반 전공자료"));
        row.setCoreObject(textOf(j, "coreObject"));
        row.setCoreObjectLabel(textOf(j, "coreObjectLabel"));
        // ai07 disclaimer 우선, 비었으면 서버 기본 고지
        String disc = textOf(j, "disclaimer");
        row.setDisclaimer((disc != null && !disc.isBlank()) ? disc : DISCLAIMER);
        row.setDocumentOverview(textOf(j, "documentOverview"));
        row.setKeywordsJson(arrayJson(j.get("keywords")));
        row.setCoreContentsJson(arrayJson(j.get("coreContents")));
        row.setDetailedCoreContentsJson(nodeJson(j.get("detailedCoreContents")));
        row.setPageSummariesJson(nodeJson(j.get("pageSummaries")));
        row.setStudyPointsJson(arrayJson(j.get("studyPoints")));
        row.setAiStudyQuestionsJson(arrayJson(j.get("aiStudyQuestions")));
        row.setWikiSummariesJson(nodeJson(j.get("wikiSummaries")));
        String lim = nodeJson(j.get("limitations"));
        row.setLimitationsJson((lim == null || "[]".equals(lim)) ? writeJson(DEFAULT_LIMITATIONS) : lim);
    }

    private String textOf(JsonNode j, String key) {
        JsonNode n = j.get(key);
        return (n == null || n.isNull()) ? null : n.asText();
    }

    private String arrayJson(JsonNode n) {
        if (n == null || n.isNull()) return "[]";
        if (n.isArray()) return n.toString();
        // 문자열 하나로 오면 1요소 배열로
        return writeJson(List.of(n.asText()));
    }

    private String nodeJson(JsonNode n) {
        return (n == null || n.isNull()) ? "[]" : n.toString();
    }

    private String writeJson(Object o) {
        try { return MAPPER.writeValueAsString(o); } catch (Exception e) { return "[]"; }
    }

    // ── DTO 변환(JSON → 파싱된 리스트/객체) ──────────────────────────────
    @SuppressWarnings({"rawtypes", "unchecked"})
    private StudyNoteAnalysisDTO toDTO(MaterialStudyNoteAnalysis r) {
        return toDTOBuilder(r).build();
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private StudyNoteAnalysisDTO.StudyNoteAnalysisDTOBuilder toDTOBuilder(MaterialStudyNoteAnalysis r) {
        return StudyNoteAnalysisDTO.builder()
                .materialId(r.getMaterialId())
                .status(r.getStatus())
                .fallback(Boolean.TRUE.equals(r.getFallback()))
                .fallbackReason(r.getFallbackReason())
                .mode(MODE)
                .domain(r.getDomain())
                .domainLabel(r.getDomainLabel())
                .coreObject(r.getCoreObject())
                .coreObjectLabel(r.getCoreObjectLabel())
                .disclaimer(r.getDisclaimer() == null ? DISCLAIMER : r.getDisclaimer())
                .documentOverview(r.getDocumentOverview())
                .keywords(strList(r.getKeywordsJson()))
                .coreContents(strList(r.getCoreContentsJson()))
                .detailedCoreContents(mapList(r.getDetailedCoreContentsJson()))
                .pageSummaries(sortByPage(mapList(r.getPageSummariesJson())))
                .studyPoints(strList(r.getStudyPointsJson()))
                .aiStudyQuestions(strList(r.getAiStudyQuestionsJson()))
                .wikiSummaries(mapList(r.getWikiSummariesJson()))
                .limitations(strList(r.getLimitationsJson()))
                .errorMessage(r.getErrorMessage());
    }

    private List<String> strList(String json) {
        List<String> out = new ArrayList<>();
        if (json == null || json.isBlank()) return out;
        try {
            JsonNode arr = MAPPER.readTree(json);
            if (arr.isArray()) for (JsonNode n : arr) {
                if (n.isTextual()) { if (!n.asText().isBlank()) out.add(n.asText()); }
                else if (n.isObject()) {
                    String v = n.has("content") ? n.get("content").asText()
                            : n.has("text") ? n.get("text").asText() : n.toString();
                    if (v != null && !v.isBlank()) out.add(v);
                } else if (!n.isNull()) out.add(n.asText());
            }
        } catch (Exception ignore) {}
        return out;
    }

    // pageSummaries 를 page 번호 오름차순 정렬
    private List<Map<String, Object>> sortByPage(List<Map<String, Object>> list) {
        if (list == null) return new ArrayList<>();
        list.sort((a, b) -> {
            int pa = a.get("page") instanceof Number ? ((Number) a.get("page")).intValue() : 0;
            int pb = b.get("page") instanceof Number ? ((Number) b.get("page")).intValue() : 0;
            return Integer.compare(pa, pb);
        });
        return list;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> mapList(String json) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (json == null || json.isBlank()) return out;
        try {
            JsonNode arr = MAPPER.readTree(json);
            if (arr.isArray()) for (JsonNode n : arr) {
                if (n.isObject()) out.add(MAPPER.convertValue(n, Map.class));
                else if (n.isTextual() && !n.asText().isBlank()) {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("title", "");
                    m.put("content", n.asText());
                    out.add(m);
                }
            }
        } catch (Exception ignore) {}
        return out;
    }

}
