package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.StudyJournalDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.StudyJournal;
import com.studybridge.api.exception.StudyJournalRejectedException;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.StudyJournalRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
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
        return StudyJournalDTO.Response.builder()
                .id(j.getId())
                .materialId(j.getMaterialId())
                .type(j.getType())
                .s3Key(j.getS3Key())
                .validationDecision(j.getValidationDecision())
                .validationCategory(j.getValidationCategory())
                .relationType(j.getRelationType())
                .relationPath(j.getRelationPath())
                .confidence(j.getConfidence())
                .byteSize(j.getByteSize())
                .content(content)
                .createdAt(j.getCreatedAt())
                .updatedAt(j.getUpdatedAt())
                .build();
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
