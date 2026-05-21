package com.studybridge.api.controller;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MaterialService;
import com.studybridge.api.service.S3Service;
import com.studybridge.api.service.PdfExtractionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;

@RestController
@RequestMapping("/api/materials")
@RequiredArgsConstructor
public class MaterialController {

    private final MaterialService materialService;
    private final S3Service s3Service;
    private final PdfExtractionService pdfExtractionService;

    // 자료보관함 조회
    @GetMapping
    public ResponseEntity<List<MaterialDTO>> getMyMaterials(@AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(materialService.getUserMaterials(userDetails.getId()));
    }

    // 상세 조회
    @GetMapping("/{materialId}")
    public ResponseEntity<MaterialDTO> getMaterialDetail(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(materialService.getMaterial(userDetails.getId(), materialId));
    }

    // PDF 학습 자료 업로드 및 비동기 텍스트 추출 체인 연동
    @PostMapping("/upload")
    public ResponseEntity<?> uploadMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("file") MultipartFile file) {
        
        if (userDetails == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("로그인이 필요한 서비스입니다.");
        }
        
        if (file == null || file.isEmpty()) {
            return ResponseEntity.badRequest().body("업로드할 파일이 비어 있습니다.");
        }

        try {
            // 1. S3 서비스 가동 (S3Config 자격 증명이 부재할 시 로컬 temp-materials/ 폴백으로 안전하게 가동)
            String storedFileName = s3Service.uploadFile(file, userDetails.getId());
            String s3Url = s3Service.getPresignedUrl(storedFileName);

            // 2. DB에 기본 자료 엔티티 메타데이터 저장 (PENDING 상태로 등록)
            MaterialDTO savedMaterial = materialService.saveMaterial(
                    userDetails.getId(), 
                    file.getOriginalFilename(), 
                    storedFileName, 
                    storedFileName, // s3Key로도 사용
                    file.getSize()
            );

            // 3. 비동기 텍스트 추출 파이프라인 위임 (MultipartFile 소멸 방지를 위해 바이트 어레이 복사본 전달)
            pdfExtractionService.sendToFastApiForExtraction(
                    savedMaterial.getMaterialId(), 
                    file.getBytes(), 
                    file.getOriginalFilename()
            );

            // 202 Accepted 반환: 업로드 접수 완료 및 백그라운드 파싱 처리 중임을 의미
            return ResponseEntity.status(HttpStatus.ACCEPTED).body(savedMaterial);

        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        } catch (IOException e) {
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body("파일 처리 중 오류가 발생했습니다: " + e.getMessage());
        }
    }
}