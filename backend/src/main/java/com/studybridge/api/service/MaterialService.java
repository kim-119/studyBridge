package com.studybridge.api.service;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class MaterialService {

    private final MaterialRepository materialRepository;
    private final S3Service s3Service;
    private final PdfExtractionService pdfExtractionService;
    private final MaterialFeedbackRepository materialFeedbackRepository;
    private final MaterialSummaryRepository materialSummaryRepository;

    @Transactional
    public MaterialDTO uploadAndSaveMaterial(Long userId, String title, MaterialType type, String keywords,
            org.springframework.web.multipart.MultipartFile file) throws java.io.IOException {
        // S3에 파일 업로드
        String s3Key = s3Service.uploadFile(file, userId);

        // DB에 데이터 저장
        Material material = Material.builder()
                .userId(userId)
                .title(title)
                .materialType(type)
                .keywords(keywords)
                .originalFileName(file.getOriginalFilename())
                .storedFileName(s3Key)
                .s3FileUrl(s3Key)
                .fileSize(file.getSize())
                .extractionStatus(ExtractionStatus.PENDING)
                .build();

        Material savedMaterial = materialRepository.save(material);

        // FastAPI로 텍스트 추출
        pdfExtractionService.sendToFastApiForExtraction(
                savedMaterial.getMaterialId(),
                file.getBytes(),
                file.getOriginalFilename());

        return convertToDTO(savedMaterial);
    }

    @Transactional
    public MaterialDTO saveStudyLog(Long userId, String title, String keywords, java.time.LocalDate studyDate,
            String learningContent, String nextPlan) {
        Material material = Material.builder()
                .userId(userId)
                .title(title)
                .materialType(MaterialType.STUDY_LOG)
                .keywords(keywords)
                .studyDate(studyDate)
                .learningContent(learningContent)
                .nextPlan(nextPlan)
                .fileSize(0L)
                .extractionStatus(ExtractionStatus.SUCCESS) // 텍스트만 있으므로 추출 성공(완료)으로 간주
                .build();

        Material savedMaterial = materialRepository.save(material);
        return convertToDTO(savedMaterial);
    }

    @Transactional
    public MaterialDTO updateMaterial(Long userId, Long materialId, MaterialDTO.UpdateRequest request) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 수정 권한이 없습니다.");
        }

        if (request.getTitle() != null && !request.getTitle().isBlank()) {
            material.setTitle(request.getTitle());
        }
        if (request.getKeywords() != null) {
            material.setKeywords(request.getKeywords());
        }
        
        // 학습일지인 경우 학습 내용 및 계획 업데이트
        if (material.getMaterialType() == MaterialType.STUDY_LOG) {
            boolean contentChanged = false;
            
            if (request.getLearningContent() != null && !request.getLearningContent().equals(material.getLearningContent())) {
                material.setLearningContent(request.getLearningContent());
                contentChanged = true;
            }
            if (request.getNextPlan() != null && !request.getNextPlan().equals(material.getNextPlan())) {
                material.setNextPlan(request.getNextPlan());
                contentChanged = true;
            }
            
            // 학습 내용이 변경되었다면, 기존에 생성된 AI 피드백 및 요약 데이터를 삭제하여 다음에 다시 생성되도록 함
            if (contentChanged) {
                materialFeedbackRepository.findByMaterial_MaterialId(materialId)
                        .ifPresent(fb -> {
                            material.setFeedback(null);
                            materialFeedbackRepository.delete(fb);
                        });
                materialSummaryRepository.findByMaterial_MaterialId(materialId)
                        .ifPresent(sm -> {
                            material.setSummary(null);
                            materialSummaryRepository.delete(sm);
                        });
                materialRepository.saveAndFlush(material); // 강제 동기화
            }
        }

        return convertToDTO(material);
    }

    @Transactional
    public void deleteMaterial(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 삭제 권한이 없습니다.");
        }

        // S3에서 삭제
        if (material.getMaterialType() != MaterialType.STUDY_LOG && material.getStoredFileName() != null) {
            s3Service.deleteFile(material.getStoredFileName());
        }

        materialRepository.delete(material);
    }

    public List<MaterialDTO> getUserMaterials(Long userId) {
        return materialRepository.findByUserIdOrderByUploadedAtDesc(userId).stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    // 자료 상세 조회
    public MaterialDTO getMaterial(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));

        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 조회 권한이 없습니다.");
        }

        return convertToDTO(material);
    }

    private MaterialDTO convertToDTO(Material material) {
        return MaterialDTO.builder()
                .materialId(material.getMaterialId())
                .title(material.getTitle())
                .materialType(material.getMaterialType())
                .keywords(material.getKeywords())
                .studyDate(material.getStudyDate())
                .learningContent(material.getLearningContent())
                .nextPlan(material.getNextPlan())
                .originalFileName(material.getOriginalFileName())
                .fileSize(material.getFileSize())
                .extractionStatus(material.getExtractionStatus())
                .s3PresignedUrl(material.getS3FileUrl() != null ? generatePresignedUrl(material.getS3FileUrl()) : null)
                .uploadedAt(material.getUploadedAt())
                .build();
    }

    private String generatePresignedUrl(String s3Key) {
        return s3Service.getPresignedUrl(s3Key);
    }
}