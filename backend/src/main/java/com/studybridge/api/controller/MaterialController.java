package com.studybridge.api.controller;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MaterialService;
import com.studybridge.api.service.PdfExtractionService;
import com.studybridge.api.service.AiIntegrationService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/materials")
@RequiredArgsConstructor
public class MaterialController {

    private final MaterialService materialService;
    private final AiIntegrationService aiIntegrationService;
    private final PdfExtractionService pdfExtractionService;

    // 학습일지 생성
    @PostMapping("/log")
    public ResponseEntity<MaterialDTO> createStudyLog(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody MaterialDTO.StudyLogRequest request) {
        
        MaterialDTO savedMaterial = materialService.saveStudyLog(
                userDetails.getId(),
                request.getTitle(),
                request.getKeywords(),
                request.getStudyDate(),
                request.getLearningContent(),
                request.getNextPlan()
        );
        return ResponseEntity.ok(savedMaterial);
    }

    // 자료 업로드 및 비동기 텍스트 추출 파이프라인 위임
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<MaterialDTO> uploadMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("title") String title,
            @RequestParam("materialType") MaterialType materialType,
            @RequestParam(value = "keywords", required = false) String keywords,
            @RequestParam("file") MultipartFile file) throws IOException {
        
        MaterialDTO savedMaterial = materialService.uploadAndSaveMaterial(
                userDetails.getId(),
                title,
                materialType,
                keywords,
                file
        );

        // 비동기 텍스트 추출 파이프라인 위임 (MultipartFile 바이트 복사본 전달)
        try {
            pdfExtractionService.sendToFastApiForExtraction(
                    savedMaterial.getMaterialId(), 
                    file.getBytes(), 
                    file.getOriginalFilename()
            );
        } catch (Exception e) {
            // 비동기 처리에 실패하더라도 업로드 자체 응답은 지장없도록 예외 격리
        }

        return ResponseEntity.ok(savedMaterial);
    }

    // 자료 정보 수정 (제목, 키워드 등)
    @PutMapping("/{materialId}")
    public ResponseEntity<MaterialDTO> updateMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody MaterialDTO.UpdateRequest request) {
        
        MaterialDTO updatedMaterial = materialService.updateMaterial(userDetails.getId(), materialId, request);
        return ResponseEntity.ok(updatedMaterial);
    }

    // 자료 삭제
    @DeleteMapping("/{materialId}")
    public ResponseEntity<Void> deleteMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        materialService.deleteMaterial(userDetails.getId(), materialId);
        return ResponseEntity.ok().build();
    }

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

    @GetMapping("/{materialId}/summary")
    public ResponseEntity<com.studybridge.api.dto.SummaryDTO> getSummary(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.getSummary(userDetails.getId(), materialId));
    }

    @GetMapping("/{materialId}/feedback")
    public ResponseEntity<com.studybridge.api.dto.FeedbackDTO> getFeedback(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.getFeedback(userDetails.getId(), materialId));
    }

    @GetMapping("/{materialId}/memo")
    public ResponseEntity<com.studybridge.api.dto.MemoDTO> getMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.getMemo(userDetails.getId(), materialId));
    }

    @PutMapping("/{materialId}/memo")
    public ResponseEntity<com.studybridge.api.dto.MemoDTO> saveMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody Map<String, String> request) {
        return ResponseEntity.ok(aiIntegrationService.saveMemo(userDetails.getId(), materialId, request.get("content")));
    }

    @GetMapping("/{materialId}/quiz")
    public ResponseEntity<List<com.studybridge.api.dto.QuizDTO.Response>> getQuizzes(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.getQuizzes(userDetails.getId(), materialId));
    }

    @PostMapping("/{materialId}/quiz")
    public ResponseEntity<com.studybridge.api.dto.QuizDTO.Response> generateQuiz(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody com.studybridge.api.dto.QuizDTO.Request request) {
        return ResponseEntity.ok(aiIntegrationService.generateQuiz(userDetails.getId(), materialId, request));
    }

    @PostMapping("/{materialId}/question")
    public ResponseEntity<com.studybridge.api.dto.QuestionDTO.Response> askQuestion(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody com.studybridge.api.dto.QuestionDTO.Request request) {
        return ResponseEntity.ok(aiIntegrationService.askQuestion(userDetails.getId(), materialId, request));
    }

    @GetMapping("/{materialId}/roadmap")
    public ResponseEntity<com.studybridge.api.dto.RoadmapDTO> getRoadmap(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.getRoadmap(userDetails.getId(), materialId));
    }

    @PutMapping("/{materialId}/roadmap/tasks/{taskId}/toggle")
    public ResponseEntity<com.studybridge.api.dto.RoadmapDTO.RoadmapTaskDTO> toggleRoadmapTask(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @PathVariable Long taskId) {
        return ResponseEntity.ok(aiIntegrationService.toggleRoadmapTask(userDetails.getId(), materialId, taskId));
    }
}
