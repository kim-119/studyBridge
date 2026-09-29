package com.studybridge.api.service;

import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.repository.MaterialRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.client.RestTemplate;

import java.time.Duration;
import java.util.Map;

@Slf4j
@Service
public class PdfExtractionService {

    private final MaterialRepository materialRepository;
    private final StudyNoteAnalysisService studyNoteAnalysisService;
    private final RestTemplate restTemplate;
    private final String fastApiUrl;
    private final String aiServerApiKey;

    public PdfExtractionService(MaterialRepository materialRepository,
                                StudyNoteAnalysisService studyNoteAnalysisService,
                                RestTemplateBuilder restTemplateBuilder,
                                @Value("${external-api.fastapi.url}") String fastApiUrl,
                                @Value("${external-api.fastapi.timeout}") int timeout,
                                @Value("${AI_SERVER_API_KEY:}") String aiServerApiKey) {
        this.materialRepository = materialRepository;
        this.studyNoteAnalysisService = studyNoteAnalysisService;
        this.fastApiUrl = fastApiUrl;
        this.aiServerApiKey = aiServerApiKey;
        this.restTemplate = restTemplateBuilder
                .setConnectTimeout(Duration.ofMillis(5000))
                .setReadTimeout(Duration.ofMillis(timeout))
                .build();
    }

    @Async
    public void sendToFastApiForExtraction(Long materialId, byte[] fileBytes, String originalFilename, String contentType) {
        try {
            log.info("Material ID: {} - FastAPI로 문서 전달 시작", materialId);

            String imageHash = calculateSHA256(fileBytes);
            log.info("Material ID: {} - 계산된 파일 Hash: {}", materialId, imageHash);

            ByteArrayResource fileResource = new ByteArrayResource(fileBytes) {
                @Override
                public String getFilename() {
                    return originalFilename;
                }
            };

            HttpHeaders fileHeaders = new HttpHeaders();
            fileHeaders.setContentType(resolveMediaType(contentType, originalFilename));
            HttpEntity<ByteArrayResource> filePart = new HttpEntity<>(fileResource, fileHeaders);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.MULTIPART_FORM_DATA);

            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add("file", filePart);
            body.add("material_id", materialId.toString());
            body.add("image_hash", imageHash);

            HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

            ResponseEntity<Map> response = restTemplate.postForEntity(fastApiUrl, requestEntity, Map.class);

            String extractedText = null;
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                extractedText = firstText(response.getBody());
            }

            boolean pdf = isPdf(originalFilename, contentType);
            if (pdf && (extractedText == null || extractedText.trim().length() < 50)) {
                log.warn("Material ID: {} - 일반 텍스트 추출 결과가 너무 짧거나 없음 (길이: {}). Vision OCR 추출을 시도합니다.",
                        materialId, extractedText != null ? extractedText.trim().length() : 0);

                String visionUrl = fastApiUrl.replace("/api/extract", "") + "/api/ai/pdf/extract-vision-text/upload";

                MultiValueMap<String, Object> visionBody = new LinkedMultiValueMap<>();
                visionBody.add("file", filePart);
                visionBody.add("material_id", materialId.toString());
                visionBody.add("user_goal", "자료 기반 질문 답변");

                HttpEntity<MultiValueMap<String, Object>> visionRequestEntity = new HttpEntity<>(visionBody, headers);

                try {
                    log.info("Material ID: {} - Vision OCR API 호출 시작 ({})", materialId, visionUrl);
                    ResponseEntity<Map> visionResponse = restTemplate.postForEntity(visionUrl, visionRequestEntity, Map.class);

                    if (visionResponse.getStatusCode() == HttpStatus.OK && visionResponse.getBody() != null) {
                        extractedText = firstText(visionResponse.getBody());
                        log.info("Material ID: {} - Vision OCR 텍스트 추출 성공", materialId);
                    } else {
                        log.error("Material ID: {} - Vision OCR API 응답 오류: {}", materialId, visionResponse.getStatusCode());
                    }
                } catch (Exception ve) {
                    log.error("Material ID: {} - Vision OCR API 호출 중 예외 발생: ", materialId, ve);
                }
            }

            if (extractedText != null && !extractedText.trim().isEmpty()) {
                updateMaterialSuccess(materialId, extractedText);
                log.info("Material ID: {} - 문서 텍스트 추출 성공 chars={}", materialId, extractedText.length());
                ingestMaterial(materialId, originalFilename, extractedText);
                // 추출 성공 후 백그라운드로 전공 분야·핵심 객체 중심 학습 노트 생성(실패해도 업로드/추출에는 영향 없음)
                try { studyNoteAnalysisService.analyzeAsync(materialId); }
                catch (Exception ne) { log.warn("Material ID: {} - 학습 노트 분석 트리거 실패: {}", materialId, ne.getMessage()); }
            } else {
                log.error("Material ID: {} - 텍스트 추출 최종 실패", materialId);
                updateMaterialFailure(materialId);
            }
        } catch (Exception e) {
            log.error("Material ID: {} - FastAPI 연동 중 에러 발생: ", materialId, e);
            updateMaterialFailure(materialId);
        }
    }

    private String firstText(Map body) {
        for (String key : new String[]{"extracted_text", "extractedText", "text", "content"}) {
            Object value = body.get(key);
            if (value != null && !value.toString().isBlank()) {
                return value.toString();
            }
        }
        return null;
    }

    private boolean isPdf(String filename, String contentType) {
        return "application/pdf".equalsIgnoreCase(contentType)
                || (filename != null && filename.toLowerCase().endsWith(".pdf"));
    }

    private MediaType resolveMediaType(String contentType, String filename) {
        try {
            if (contentType != null && !contentType.isBlank()) {
                return MediaType.parseMediaType(contentType);
            }
        } catch (Exception ignored) {
        }
        String lower = filename != null ? filename.toLowerCase() : "";
        if (lower.endsWith(".pdf")) {
            return MediaType.APPLICATION_PDF;
        }
        if (lower.endsWith(".docx")) {
            return MediaType.parseMediaType("application/vnd.openxmlformats-officedocument.wordprocessingml.document");
        }
        if (lower.endsWith(".txt")) {
            return MediaType.TEXT_PLAIN;
        }
        return MediaType.APPLICATION_OCTET_STREAM;
    }

    private void ingestMaterial(Long materialId, String originalFilename, String extractedText) {
        String ragUrl = fastApiUrl.replace("/api/extract", "") + "/api/rag/ingest";
        try {
            log.info("[RAG INGEST START] materialId={}", materialId);
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            if (aiServerApiKey != null && !aiServerApiKey.isBlank()) {
                headers.setBearerAuth(aiServerApiKey);
            }
            Map<String, Object> body = Map.of(
                    "material_id", materialId,
                    "document_title", originalFilename != null && !originalFilename.isBlank() ? originalFilename : "material-" + materialId,
                    "text", extractedText
            );
            ResponseEntity<Map> response = restTemplate.postForEntity(ragUrl, new HttpEntity<>(body, headers), Map.class);
            if (response.getStatusCode().is2xxSuccessful()) {
                log.info("[RAG INGEST OK] materialId={}", materialId);
            } else {
                log.error("[RAG INGEST FAIL] materialId={} status={}", materialId, response.getStatusCode());
            }
        } catch (Exception e) {
            log.error("[RAG INGEST FAIL] materialId={}", materialId, e);
        }
    }

    private String calculateSHA256(byte[] bytes) {
        try {
            java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
            byte[] hash = digest.digest(bytes);
            StringBuilder hexString = new StringBuilder();
            for (byte b : hash) {
                String hex = Integer.toHexString(0xff & b);
                if (hex.length() == 1) {
                    hexString.append('0');
                }
                hexString.append(hex);
            }
            return hexString.toString();
        } catch (Exception e) {
            log.error("해시 계산 실패", e);
            return "default_hash_" + System.currentTimeMillis();
        }
    }

    @Transactional
    public void updateMaterialSuccess(Long materialId, String text) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 자료입니다."));

        material.setExtractedText(text);
        material.setExtractionStatus(ExtractionStatus.SUCCESS);
        materialRepository.save(material);
    }

    @Transactional
    public void updateMaterialFailure(Long materialId) {
        materialRepository.findById(materialId).ifPresent(material -> {
            material.setExtractionStatus(ExtractionStatus.FAILED);
            materialRepository.save(material);
        });
    }
}
