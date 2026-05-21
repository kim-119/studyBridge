package com.studybridge.api.service;

import com.studybridge.api.dto.AdminDashboardDTO;
import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AdminService {

    private final UserRepository userRepository;
    private final MaterialRepository materialRepository;
    private final TodoRepository todoRepository;
    private final S3Service s3Service; // For deleting material from S3

    /**
     * 관리자 대시보드 통계 정보를 조회합니다.
     * @return 대시보드 DTO
     */
    public AdminDashboardDTO getDashboardStatistics() {
        long totalUserCount = userRepository.count();
        long todayNewUserCount = userRepository.countByCreatedAtAfter(LocalDate.now().atStartOfDay());
        long totalMaterialCount = materialRepository.count();
        long totalTodoCount = todoRepository.count();

        return AdminDashboardDTO.builder()
                .totalUserCount(totalUserCount)
                .todayNewUserCount(todayNewUserCount)
                .totalMaterialCount(totalMaterialCount)
                .totalTodoCount(totalTodoCount)
                .build();
    }

    /**
     * 모든 사용자의 학습 자료를 조회합니다.
     * @return 학습 자료 DTO 리스트
     */
    public List<MaterialDTO> getAllMaterials() {
        return materialRepository.findAll().stream()
                .map(this::convertMaterialToDTO)
                .collect(Collectors.toList());
    }

    /**
     * 관리자가 특정 학습 자료를 삭제합니다.
     * @param materialId 삭제할 학습 자료 ID
     */
    @Transactional
    public void deleteMaterialByAdmin(Long materialId) {
        Material material = materialRepository.findById(materialId)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 학습 자료입니다."));

        // S3에서도 파일 삭제 (저장된 파일명이 S3 키 역할을 함)
        s3Service.deleteFile(material.getStoredFileName());
        
        // DB에서 자료 삭제
        materialRepository.delete(material);
    }

    /**
     * 이메일 또는 닉네임으로 사용자를 검색합니다.
     * @param keyword 검색 키워드
     * @return 사용자 DTO 리스트
     */
    public List<UserDTO.Response> searchUsers(String keyword) {
        return userRepository.findByEmailContainingIgnoreCaseOrDisplayNameContainingIgnoreCase(keyword, keyword)
                .stream()
                .map(user -> UserDTO.Response.builder()
                        .id(user.getId())
                        .email(user.getEmail())
                        .displayName(user.getDisplayName())
                        .major(user.getMajor())
                        .photoUrl(user.getPhotoUrl())
                        .status(user.getStatus())
                        .isSubscribed(user.getIsSubscribed())
                        .admin(user.getAdmin())
                        .build())
                .collect(Collectors.toList());
    }

    private MaterialDTO convertMaterialToDTO(Material material) {
        return MaterialDTO.builder()
                .materialId(material.getMaterialId())
                .originalFileName(material.getOriginalFileName())
                .fileSize(material.getFileSize())
                .extractionStatus(material.getExtractionStatus())
                // 관리자가 조회할 때도 다운로드/확인할 수 있도록 Presigned URL 발급
                .s3PresignedUrl(s3Service.getPresignedUrl(material.getStoredFileName()))
                .uploadedAt(material.getUploadedAt())
                .updatedAt(material.getUpdatedAt())
                .build();
    }
}