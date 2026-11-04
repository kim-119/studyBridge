package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.dto.StudyJournalDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.StudyJournal;
import com.studybridge.api.exception.StudyJournalRejectedException;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.StudyJournalRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

/**
 * 학습일지 저장/조회/삭제 오케스트레이션.
 *
 * 저장 순서: content 검증 → 소유권 확인 → ai07 FastAPI 검증 → ACCEPT만 → S3 저장(원문) → DB 메타데이터 저장.
 * DB 저장 실패 시 S3 객체 보상 삭제. 원문/비밀값은 DB·로그에 남기지 않는다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StudyJournalService {

    private static final int MAX_LEN = 5000;
    private static final int PDF_SNIPPET_LEN = 800;

    private final MaterialRepository materialRepository;
    private final StudyJournalRepository journalRepository;
    private final StudyJournalValidationClient validationClient;
    private final StudyJournalS3Service s3Service;
    private final ObjectMapper objectMapper;

    // Global Response Quality Gate(기본 OFF) — 생성자 시그니처 유지를 위해 setter 주입(없으면 OFF).
    private AiResponseQualityGate qualityGate;

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    private boolean gateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    /** ai07 판정 라벨 허용값(study_journal_routes 의 enum + Spring 폴백 전용 분류). 게이트 ON 에서 그 밖의 값(자유 텍스트)은 내보내지 않는다. */
    static final Set<String> DECISIONS = Set.of("ACCEPT", "REQUEST_REVISION", "BLOCK");
    static final Set<String> CATEGORIES = Set.of("PDF_CONCEPT_SUMMARY", "PDF_QUESTION", "LEARNING_REFLECTION", "COMMON_MISCONCEPTION",
            "OFF_TOPIC", "TOXIC_OR_ABUSIVE", "MEANINGLESS", "ADVERTISEMENT", "TOO_SHORT", "VALIDATION_UNAVAILABLE");
    static final Set<String> RELATION_TYPES = Set.of("DIRECT", "CHILD_CONCEPT", "PARENT_CONCEPT", "PREREQUISITE", "APPLICATION",
            "COMPARISON", "COMMON_MISCONCEPTION", "SAME_TERM_DIFFERENT_CONTEXT", "NONE");

    // ── 저장 ──────────────────────────────────────────────────────────────────
    @Transactional
    public StudyJournalDTO.Response create(Long userId, Long materialId, String rawContent) {
        String content = rawContent == null ? "" : rawContent.trim();
        if (content.isEmpty()) {
            throw new IllegalArgumentException("학습일지 내용을 입력해 주세요.");
        }
        if (content.length() > MAX_LEN) {
            throw new IllegalArgumentException("학습일지는 최대 " + MAX_LEN + "자까지 저장할 수 있습니다.");
        }

        Material material = getMaterialSafely(userId, materialId);

        // ai07 FastAPI 검증 (장애 시 보수적 로컬 폴백)
        StudyJournalValidationResult result = validationClient.validate(
                content,
                material.getTitle(),
                material.getKeywords(),
                snippet(material.getExtractedText()));

        if (gateOn()) {
            // 판정(ACCEPT/수정 요청/차단)은 저장 허용 여부를 정하는 게이트 판단 — 평가기로 다시 거르지 않는다.
            // 사용자에게 보일 AI 자유 텍스트(연결 경로·사유·제안)만 평가하고, 미승인이면 저장·노출하지 않는다(고정 문구로 대체).
            result = gateJudgementText(material, content, result);
        }

        if (!result.isAccepted()) {
            // REQUEST_REVISION / BLOCK → 저장 금지(원문 미저장/미로깅)
            throw new StudyJournalRejectedException(result);
        }

        // ACCEPT → S3 먼저 저장
        String uuid = UUID.randomUUID().toString();
        String key = s3Service.buildKey(userId, materialId, uuid);
        byte[] body = buildS3Body(materialId, userId, content, result);
        String hash = sha256(content);

        Map<String, String> s3Metadata = new LinkedHashMap<>();
        s3Metadata.put("materialid", String.valueOf(materialId));
        s3Metadata.put("userid", String.valueOf(userId));
        s3Metadata.put("type", "STUDY_JOURNAL");
        s3Metadata.put("validationcategory", safe(result.getCategory()));
        s3Metadata.put("relationtype", safe(result.getRelationType()));

        s3Service.putJournalJson(key, body, s3Metadata);

        // S3 저장 성공 → DB 메타데이터 저장. 실패 시 S3 보상 삭제.
        try {
            StudyJournal journal = StudyJournal.builder()
                    .materialId(materialId)
                    .userId(userId)
                    .type("STUDY_JOURNAL")
                    .s3Key(key)
                    .contentHash(hash)
                    .byteSize((long) body.length)
                    .contentType("application/json")
                    .validationDecision(result.getDecision())
                    .validationCategory(result.getCategory())
                    .relationType(result.getRelationType())
                    .relationPath(result.getRelationPath())
                    .confidence(result.getConfidence())
                    .qualityStatus("APPROVED".equals(result.getQualityStatus()) ? "APPROVED" : null)
                    .status(StudyJournal.StudyJournalStatus.ACTIVE)
                    .build();
            journal = journalRepository.saveAndFlush(journal);
            return toResponse(journal, null);
        } catch (Exception dbError) {
            try {
                s3Service.deleteJournal(key);
            } catch (Exception compensationError) {
                // 보상 삭제 실패: 원문 없이 s3Key만 남긴다(orphan 추적용).
                log.error("학습일지 DB 저장 실패 후 S3 보상 삭제 실패. s3Key={}", key);
            }
            throw dbError;
        }
    }

    // ── 목록 조회 (메타데이터만, S3 GET 안 함) ──────────────────────────────────
    @Transactional(readOnly = true)
    public List<StudyJournalDTO.Response> list(Long userId, Long materialId) {
        getMaterialSafely(userId, materialId);
        return journalRepository
                .findByMaterialIdAndStatusOrderByCreatedAtDesc(materialId, StudyJournal.StudyJournalStatus.ACTIVE)
                .stream()
                .map(j -> toResponse(j, null))
                .collect(Collectors.toList());
    }

    // ── 상세 조회 (S3에서 원문 읽기) ────────────────────────────────────────────
    @Transactional(readOnly = true)
    public StudyJournalDTO.Response detail(Long userId, Long materialId, Long journalId) {
        getMaterialSafely(userId, materialId);
        StudyJournal journal = journalRepository
                .findByIdAndStatus(journalId, StudyJournal.StudyJournalStatus.ACTIVE)
                .orElseThrow(() -> new IllegalArgumentException("학습일지를 찾을 수 없습니다."));
        if (!journal.getMaterialId().equals(materialId) || !journal.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        String content = extractContentFromS3(journal.getS3Key());
        return toResponse(journal, content);
    }

    // ── 삭제 (soft delete) ─────────────────────────────────────────────────────
    @Transactional
    public void delete(Long userId, Long materialId, Long journalId) {
        getMaterialSafely(userId, materialId);
        StudyJournal journal = journalRepository
                .findByIdAndStatus(journalId, StudyJournal.StudyJournalStatus.ACTIVE)
                .orElseThrow(() -> new IllegalArgumentException("학습일지를 찾을 수 없습니다."));
        if (!journal.getMaterialId().equals(materialId) || !journal.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        journal.setStatus(StudyJournal.StudyJournalStatus.DELETED);
        journal.setDeletedAt(java.time.LocalDateTime.now());
        journalRepository.save(journal);
        // S3 객체는 보존(soft delete). 운영 정책상 물리 삭제가 필요하면 lifecycle 또는 별도 배치로 처리.
    }

    // ── 내부 helper ────────────────────────────────────────────────────────────
    private Material getMaterialSafely(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }
        return material;
    }

    private byte[] buildS3Body(Long materialId, Long userId, String content, StudyJournalValidationResult r) {
        Map<String, Object> validation = new LinkedHashMap<>();
        validation.put("decision", r.getDecision());
        validation.put("category", r.getCategory());
        validation.put("relationType", r.getRelationType());
        validation.put("relationPath", r.getRelationPath());
        validation.put("studyRelated", r.isStudyRelated());
        validation.put("pdfGrounded", r.isPdfGrounded());
        validation.put("conceptExpanded", r.isConceptExpanded());
        validation.put("confidence", r.getConfidence());

        Map<String, Object> obj = new LinkedHashMap<>();
        obj.put("materialId", materialId);
        obj.put("userId", userId);
        obj.put("type", "STUDY_JOURNAL");
        obj.put("content", content);
        obj.put("validation", validation);
        obj.put("createdAt", Instant.now().toString());
        try {
            return objectMapper.writeValueAsBytes(obj);
        } catch (Exception e) {
            throw new IllegalStateException("학습일지 직렬화에 실패했습니다.");
        }
    }

    private String extractContentFromS3(String key) {
        try {
            String json = s3Service.getJournalJson(key);
            Map<?, ?> obj = objectMapper.readValue(json, Map.class);
            Object content = obj.get("content");
            return content == null ? "" : String.valueOf(content);
        } catch (Exception e) {
            log.error("학습일지 S3 원문 읽기 실패. s3Key={}", key);
            throw new IllegalStateException("학습일지 본문을 불러오지 못했습니다.");
        }
    }

    private StudyJournalDTO.Response toResponse(StudyJournal j, String content) {
        boolean gate = gateOn();
        // 게이트 ON: AI 연결 경로(자유 텍스트)는 승인 기록이 있을 때만. 판정 라벨은 허용 enum 값만(그 외 값은 내보내지 않음).
        boolean showPath = !gate || "APPROVED".equals(j.getQualityStatus());
        return StudyJournalDTO.Response.builder()
                .id(j.getId())
                .materialId(j.getMaterialId())
                .type(j.getType())
                .s3Key(j.getS3Key())
                .validationDecision(gate ? allowed(j.getValidationDecision(), DECISIONS) : j.getValidationDecision())
                .validationCategory(gate ? allowed(j.getValidationCategory(), CATEGORIES) : j.getValidationCategory())
                .relationType(gate ? allowed(j.getRelationType(), RELATION_TYPES) : j.getRelationType())
                .relationPath(showPath ? j.getRelationPath() : null)
                .qualityStatus(gate ? j.getQualityStatus() : null)
                .qualityRedacted(!showPath && j.getRelationPath() != null ? Boolean.TRUE : null)
                .confidence(j.getConfidence())
                .byteSize(j.getByteSize())
                .content(content)
                .createdAt(j.getCreatedAt())
                .updatedAt(j.getUpdatedAt())
                .build();
    }

    private static String allowed(String v, Set<String> allowed) {
        return v != null && allowed.contains(v.trim().toUpperCase()) ? v.trim().toUpperCase() : null;
    }

    // ── 품질 게이트(Phase D) — AI 판정 문구 평가 ────────────────────────────────────

    /** 사용자에게 보일 AI 판정 자유 텍스트: ACCEPT = 연결 경로, 거절 = 사유·제안·연결 경로(RejectionResponse 에 실리는 문자열 전부). */
    static String judgementVisibleText(StudyJournalValidationResult r) {
        StringBuilder sb = new StringBuilder();
        if (!r.isAccepted()) {
            appendLine(sb, r.getReason());
            appendLine(sb, r.getSuggestion());
        }
        appendLine(sb, r.getRelationPath());
        String t = sb.toString().strip();
        return t.isEmpty() ? null : t;
    }

    private static void appendLine(StringBuilder sb, String v) {
        if (v != null && !v.isBlank()) {
            sb.append(v.strip()).append('\n');
        }
    }

    /**
     * 게이트 ON: 판정은 그대로 두고, ai07 가 만든 사용자 노출 문구만 GENERAL_EXPLANATION/text 로 평가한다
     * (근거 = 학습자가 쓴 메모 본문(USER_INPUT) + 이 자료의 원문(PDF_ORIGINAL, allowedMaterialIds=[자료])).
     * 재생성하지 않는다 — 다시 검증을 호출하면 판정(저장 허용 여부) 자체가 바뀔 수 있어서. 승인 → 문구 노출·저장(quality_status=APPROVED),
     * 거절/평가 불가 → 연결 경로는 저장·노출하지 않고, 거절 응답의 사유·제안은 분류별 Spring 고정 문구로 바꾼다(qualityRedacted=true).
     * Spring 로컬 폴백/저장 보류 결과는 문구가 Spring 고정 문구라 평가하지 않는다.
     */
    StudyJournalValidationResult gateJudgementText(Material material, String content, StudyJournalValidationResult r) {
        String decision = allowed(r.getDecision(), DECISIONS);
        StudyJournalValidationResult base = copy(r, decision == null ? "REQUEST_REVISION" : decision, allowed(r.getCategory(), CATEGORIES),
                allowed(r.getRelationType(), RELATION_TYPES), r.getRelationPath(), r.getReason(), r.getSuggestion(), null, null);
        if (r.isLocalOrigin()) {
            return base;
        }
        String visible = judgementVisibleText(base);
        if (visible == null) {
            return base;
        }
        Long mid = material.getMaterialId();
        String rid = "sj-" + mid + "-" + UUID.randomUUID().toString().substring(0, 8);
        List<ResponseQualityV1.GroundingEvidence> ev = new java.util.ArrayList<>();
        ev.add(new ResponseQualityV1.GroundingEvidence(null, "USER_INPUT", null, null, null, null, "journal-memo",
                content.length() > 4000 ? content.substring(0, 4000) : content));
        ev.addAll(AiResponseQualityGate.pdfEvidence(mid, material.getExtractedText(), 4000, 12000));
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.GENERAL_EXPLANATION,
                ResponseQualityV1.OutputKind.TEXT,
                "학습자가 자료 '" + safe(material.getTitle()) + "'(키워드: " + safe(material.getKeywords()) + ")를 공부하며 쓴 학습일지가 자료와 어떤 "
                        + "개념 관계인지 판정하고, 사용자에게 보여 줄 개념 연결 경로·판정 사유·수정 제안을 작성해 주세요(판정 " + base.getDecision()
                        + ", 분류 " + base.getCategory() + ", 관계 " + base.getRelationType() + ").",
                ev, new ResponseQualityV1.Constraints(List.of(mid), null, null, null, null, null, null, false, false, null, null, null, null,
                        null, null), null);
        AiResponseQualityGate.Outcome<String> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
            if (attempt > 0) {
                throw new AiResponseQualityGate.StopGeneration("JUDGEMENT_NOT_REGENERATED");
            }
            return visible;
        }, AiResponseQualityGate::text);
        if (outcome.approved()) {
            return copy(base, base.getDecision(), base.getCategory(), base.getRelationType(), base.getRelationPath(), base.getReason(),
                    base.getSuggestion(), "APPROVED", null);
        }
        GateDecision d = outcome.decision();
        log.info("[QUALITY-GATE] study-journal materialId={} rid={} 판정 문구 미승인 decision={} status={} codes={} → 고정 문구",
                mid, rid, base.getDecision(), d.qualityStatus(), d.reasonCodes());
        boolean accepted = base.isAccepted();
        return copy(base, base.getDecision(), base.getCategory(), base.getRelationType(), null,
                accepted ? base.getReason() : fixedReason(base.getCategory()),
                accepted ? base.getSuggestion() : fixedSuggestion(base.getCategory()),
                d.qualityStatus() != null ? d.qualityStatus().name() : "REJECTED", Boolean.TRUE);
    }

    private static StudyJournalValidationResult copy(StudyJournalValidationResult r, String decision, String category, String relationType,
                                                     String relationPath, String reason, String suggestion, String qualityStatus,
                                                     Boolean qualityRedacted) {
        return StudyJournalValidationResult.builder()
                .decision(decision).category(category).relationType(relationType).relationPath(relationPath)
                .studyRelated(r.isStudyRelated()).pdfGrounded(r.isPdfGrounded()).conceptExpanded(r.isConceptExpanded())
                .confidence(r.getConfidence()).reason(reason).suggestion(suggestion).engine(r.getEngine())
                .localOrigin(r.isLocalOrigin()).qualityStatus(qualityStatus).qualityRedacted(qualityRedacted)
                .build();
    }

    /** 미승인 AI 사유 대신 보여 줄 Spring 고정 문구(분류 enum 기준, AI 생성 아님). */
    static String fixedReason(String category) {
        if ("TOXIC_OR_ABUSIVE".equals(category)) {
            return "욕설이나 공격적인 표현이 포함된 것으로 판정되어 저장하지 않았습니다.";
        }
        if ("ADVERTISEMENT".equals(category)) {
            return "광고·홍보·링크성 내용으로 판정되어 저장하지 않았습니다.";
        }
        if ("MEANINGLESS".equals(category) || "TOO_SHORT".equals(category)) {
            return "학습 내용으로 보기에 너무 짧거나 의미가 부족하다고 판정되어 저장하지 않았습니다.";
        }
        return "학습 자료와의 연결을 확인하지 못해 저장하지 않았습니다.";
    }

    static String fixedSuggestion(String category) {
        if ("TOXIC_OR_ABUSIVE".equals(category)) {
            return "학습 개념 중심으로 순화해서 다시 작성해 주세요.";
        }
        if ("ADVERTISEMENT".equals(category)) {
            return "학습한 개념이나 궁금한 점을 작성해 주세요.";
        }
        return "자료의 핵심 개념과 연결해 조금 더 구체적으로 다시 작성해 주세요.";
    }

    private String snippet(String text) {
        if (text == null) return "";
        String t = text.strip();
        return t.length() <= PDF_SNIPPET_LEN ? t : t.substring(0, PDF_SNIPPET_LEN);
    }

    private String safe(String s) {
        return s == null ? "" : s;
    }

    private String sha256(String content) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] digest = md.digest(content.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(digest);
        } catch (Exception e) {
            return null;
        }
    }
}
