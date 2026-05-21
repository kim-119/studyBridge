package com.studybridge.api.service;

import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.repository.MaterialRepository;
import lombok.extern.slf4j.Slf4j;
import lombok.RequiredArgsConstructor;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.*;
import org.springframework.beans.factory.annotation.Value;
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

    /**
     * 비동기 스레드에서 FastAPI로 PDF를 전달합니다.
     * MultipartFile 대신 byte[]를 받아 파일 소멸 문제를 방지합니다.
     */
    @Async
    public void sendToFastApiForExtraction(Long materialId, byte[] fileBytes, String originalFilename) {
        try {
            log.info("Material ID: {} - FastAPI로 PDF 전달 시작", materialId);

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

            HttpEntity<MultiValueMap<String, Object>> requestEntity = new HttpEntity<>(body, headers);

            ResponseEntity<Map> response = restTemplate.postForEntity(fastApiUrl, requestEntity, Map.class);

            if (response.getStatusCode() == HttpStatus.OK && response.getBody() != null) {
                String extractedText = (String) response.getBody().get("extracted_text");
                updateMaterialSuccess(materialId, extractedText);
                log.info("Material ID: {} - 텍스트 추출 및 DB 저장 완료", materialId);
            } else {
                log.error("Material ID: {} - FastAPI 응답 오류: {}", materialId, response.getStatusCode());
                updateMaterialFailure(materialId);
            }
        } catch (Exception e) {
            log.error("Material ID: {} - FastAPI 연동 중 에러 발생: ", materialId, e);
            updateMaterialFailure(materialId);
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