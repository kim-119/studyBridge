package com.studybridge.api.service;

import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.repository.MaterialRepository;
import lombok.extern.slf4j.Slf4j;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.web.client.RestTemplateBuilder;
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
    private final RestTemplate restTemplate;

    @Autowired(required = false)
    private RagIngestService ragIngestService;
    private final String fastApiUrl;

    public PdfExtractionService(MaterialRepository materialRepository, 
                                RestTemplateBuilder restTemplateBuilder,
                                @Value("${external-api.fastapi.url}") String fastApiUrl,
                                @Value("${external-api.fastapi.timeout}") int timeout) {
        this.materialRepository = materialRepository;
        this.fastApiUrl = fastApiUrl;
        // 타임아웃 설정이 포함된 RestTemplate 생성
        this.restTemplate = restTemplateBuilder
                .setConnectTimeout(Duration.ofMillis(5000))
                .setReadTimeout(Duration.ofMillis(timeout))
                .build();
    }

    @Async
    public void sendToFastApiForExtraction(Long materialId, byte[] fileBytes, String originalFilename) {
        try {
            log.info("Material ID: {} - FastAPI로 PDF 전달 시작", materialId);

            String imageHash = calculateSHA256(fileBytes);
            log.info("Material ID: {} - 계산된 파일 Hash: {}", materialId, imageHash);

            ByteArrayResource fileResource = new ByteArrayResource(fileBytes) {
                @Override
                public String getFilename() {
                    return originalFilename;
                }
            };

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.MULTIPART_FORM_DATA);

            MultiValueMap<String, Object> body = new LinkedMultiValueMap<>();
            body.add("file", fileResource);
            body.add("material_id", materialId.toString());
            body.add("image_hash", imageHash);

            HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

            ResponseEntity<Map> response = restTemplate.postForEntity(fastApiUrl, requestEntity, Map.class);

            String extractedText = null;
            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                extractedText = (String) response.getBody().get("extracted_text");
            }

            // 만약 추출된 텍스트가 너무 짧거나 비어있으면 이미지 PDF로 간주하고 Vision OCR 추출 시도
            if (extractedText == null || extractedText.trim().length() < 50) {
                log.warn("Material ID: {} - 일반 텍스트 추출 결과가 너무 짧거나 없음 (길이: {}). Vision OCR 추출을 시도합니다.", 
                        materialId, extractedText != null ? extractedText.trim().length() : 0);
                
                String visionUrl = fastApiUrl.replace("/api/extract", "") + "/api/ai/pdf/extract-vision-text/upload";
                
                MultiValueMap<String, Object> visionBody = new LinkedMultiValueMap<>();
                visionBody.add("file", fileResource);
                visionBody.add("material_id", materialId.toString());
                visionBody.add("user_goal", "자료 기반 질문 답변");
                
                HttpEntity<MultiValueMap<String, Object>> visionRequestEntity = new HttpEntity<>(visionBody, headers);
                
                try {
                    log.info("Material ID: {} - Vision OCR API 호출 시작 ({})", materialId, visionUrl);
                    ResponseEntity<Map> visionResponse = restTemplate.postForEntity(visionUrl, visionRequestEntity, Map.class);
                    
                    if (visionResponse.getStatusCode() == HttpStatus.OK && visionResponse.getBody() != null) {
                        extractedText = (String) visionResponse.getBody().get("extracted_text");
                        log.info("Material ID: {} - Vision OCR 텍스트 추출 성공!", materialId);
                    } else {
                        log.error("Material ID: {} - Vision OCR API 응답 오류: {}", materialId, visionResponse.getStatusCode());
                    }
                } catch (Exception ve) {
                    log.error("Material ID: {} - Vision OCR API 호출 중 예외 발생: ", materialId, ve);
                }
            }

            if (extractedText != null && !extractedText.trim().isEmpty()) {
                updateMaterialSuccess(materialId, extractedText);
                if (ragIngestService != null) {
                    ragIngestService.ingestMaterialAsync(materialId, "material-" + materialId, extractedText);
                }
                log.info("Material ID: {} - 최종 텍스트 저장 완료 (길이: {})", materialId, extractedText.length());
            } else {
                log.error("Material ID: {} - 텍스트 추출 최종 실패", materialId);
                updateMaterialFailure(materialId);
            }
        } catch (Exception e) {
            log.error("Material ID: {} - FastAPI 연동 중 에러 발생: ", materialId, e);
            updateMaterialFailure(materialId);
        }
    }

    // 파일 SHA-256 해시값 계산
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
    }

    @Transactional
    public void updateMaterialFailure(Long materialId) {
        materialRepository.findById(materialId).ifPresent(material -> {
            material.setExtractionStatus(ExtractionStatus.FAILED);
        });
    }
}