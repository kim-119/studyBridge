package com.studybridge.api.service;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.repository.MaterialRepository;
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
    private final S3Service s3Service; // S3 Presigned URL 생성을 위해 주입

    @Transactional
    public MaterialDTO saveMaterial(Long userId, String originalName, String storedName, String s3Url, Long size) {
        Material material = Material.builder()
                .userId(userId)
                .originalFileName(originalName)
                .storedFileName(storedName)
                .s3FileUrl(s3Url)
                .fileSize(size)
                .extractionStatus(ExtractionStatus.PENDING) // Enum 적용
                .build();
        
        Material savedMaterial = materialRepository.save(material);
        return convertToDTO(savedMaterial);
    }

    public List<MaterialDTO> getUserMaterials(Long userId) {
        return materialRepository.findByUserIdOrderByUploadedAtDesc(userId).stream()
                .map(this::convertToDTO)
                .collect(Collectors.toList());
    }

    // 자료 상세 조회 (보안 검증 레이어 장착)
    public MaterialDTO getMaterial(Long userId, Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
        
        // 철벽 보안: 자료의 소유자와 현재 로그인한 JWT 인증 유저가 일치하는지 삼중 검증
        if (!material.getUserId().equals(userId)) {
            throw new SecurityException("해당 자료에 대한 조회 권한이 없습니다.");
        }
        
        return convertToDTO(material);
    }

    private MaterialDTO convertToDTO(Material material) {
        return MaterialDTO.builder()
                .materialId(material.getMaterialId())
                .originalFileName(material.getOriginalFileName())
                .fileSize(material.getFileSize())
                .extractionStatus(material.getExtractionStatus())
                .s3PresignedUrl(generatePresignedUrl(material.getS3FileUrl())) // 보안 URL 생성
                .uploadedAt(material.getUploadedAt())
                .build();
    }

    private String generatePresignedUrl(String s3Key) {
        return s3Service.getPresignedUrl(s3Key);
    }
}