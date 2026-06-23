package com.studybridge.api.controller;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MaterialService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import com.studybridge.api.entity.MaterialType;
import org.springframework.http.MediaType;
import org.springframework.web.multipart.MultipartFile;
import java.io.IOException;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/materials")
@RequiredArgsConstructor
public class MaterialController {

    private final MaterialService materialService;
    private final com.studybridge.api.service.AiIntegrationService aiIntegrationService;
    private final com.studybridge.api.service.StudyNoteAnalysisService studyNoteAnalysisService;

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
                request.getNextPlan(),
                request.getFolderId()
        );
        return ResponseEntity.ok(savedMaterial);
    }

    // 마인드맵(Obsidian Graph) 저장. PDF 변환/업로드 경로를 타지 않고 그래프 JSON 으로 보관한다.
    @PostMapping("/mindmap")
    public ResponseEntity<MaterialDTO> saveMindMap(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody MaterialDTO.MindMapRequest request) {
        return ResponseEntity.ok(materialService.saveMindMap(userDetails.getId(), request));
    }

    // 자료 업로드 (folderId 지정 시 해당 폴더 안에 저장, 미지정/null 이면 루트)
    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<MaterialDTO> uploadMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("title") String title,
            @RequestParam("materialType") MaterialType materialType,
            @RequestParam(value = "keywords", required = false) String keywords,
            @RequestParam(value = "folderId", required = false) Long folderId,
            @RequestParam("file") MultipartFile file) throws IOException {

        MaterialDTO savedMaterial = materialService.uploadAndSaveMaterial(
                userDetails.getId(),
                title,
                materialType,
                keywords,
                file,
                folderId
        );

        return ResponseEntity.ok(savedMaterial);
    }

    /**
     * 업로드 전 AI 파일 유형 판별. 실제 저장은 하지 않는다.
     * 파일/선택유형을 받아 ai07 분류 결과(추천 유형·불일치 여부·안내 문구)를 돌려준다.
     * PDF_TEXT_EMPTY 보다 먼저 호출되어 빈 텍스트 PDF도 파일명/메타로 추천한다.
     */
    @PostMapping(value = "/classify-before-save", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<Map<String, Object>> classifyBeforeSave(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("selectedType") String selectedType,
            @RequestParam(value = "title", required = false) String title,
            @RequestParam(value = "keywords", required = false) String keywords,
            @RequestParam("file") MultipartFile file) {
        List<String> kw = (keywords == null || keywords.isBlank())
                ? List.of()
                : java.util.Arrays.stream(keywords.split(",")).map(String::trim).filter(s -> !s.isEmpty()).toList();
        String effectiveTitle = (title == null || title.isBlank()) ? file.getOriginalFilename() : title;
        Map<String, Object> res = aiIntegrationService.classifyBeforeSave(
                file.getOriginalFilename(), file.getContentType(), toAiVocab(selectedType), null, effectiveTitle, kw);
        return ResponseEntity.ok(res);
    }

    /** 프론트/엔티티 유형명을 ai07 분류 vocab으로 변환 (PDF↔STUDY_PDF, REVIEW_NOTE↔WRONG_NOTE). */
    private static String toAiVocab(String t) {
        if (t == null) return "UNKNOWN";
        switch (t.trim().toUpperCase()) {
            case "PDF": case "STUDY_PDF": return "STUDY_PDF";
            case "PLANNER": return "PLANNER";
            case "REVIEW_NOTE": case "WRONG_NOTE": return "WRONG_NOTE";
            case "STUDY_LOG": return "STUDY_LOG";
            default: return "UNKNOWN";
        }
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

    // 자료보관함 조회 (전체 평면 목록 — 하위 호환 유지)
    @GetMapping
    public ResponseEntity<List<MaterialDTO>> getMyMaterials(@AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(materialService.getUserMaterials(userDetails.getId()));
    }

    // 자료보관함 폴더 뷰: 현재 위치(parentId)의 하위 폴더 + 자료 + breadcrumb
    @GetMapping("/items")
    public ResponseEntity<com.studybridge.api.dto.ArchiveListDTO> getArchiveItems(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam(value = "parentId", required = false) Long parentId,
            @RequestParam(value = "domain", required = false) String domain) {
        return ResponseEntity.ok(materialService.getArchiveItems(userDetails.getId(), parentId, domain));
    }

    // 자료를 다른 폴더로 이동 (folderId=null 이면 루트로)
    @PatchMapping("/{materialId}/move")
    public ResponseEntity<MaterialDTO> moveMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody MaterialDTO.MoveRequest request) {
        return ResponseEntity.ok(materialService.moveMaterial(userDetails.getId(), materialId, request.getFolderId()));
    }

    // AI 핵심 요약 노트(전공 분야·핵심 객체 중심). PDF 외 자료는 null(프론트는 기존 요약 표시).
    @GetMapping("/{materialId}/study-note")
    public ResponseEntity<com.studybridge.api.dto.StudyNoteAnalysisDTO> getStudyNote(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(studyNoteAnalysisService.get(userDetails.getId(), materialId));
    }

    // 상세 조회
    // context=review-note 일 때만 오답노트(REVIEW_NOTE) 상세 허용(전용 복습 화면). 그 외엔 오답노트 materialId 차단(404).
    @GetMapping("/{materialId}")
    public ResponseEntity<MaterialDTO> getMaterialDetail(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestParam(value = "context", required = false) String context) {
        return ResponseEntity.ok(materialService.getMaterial(userDetails.getId(), materialId, context));
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

    // 균형 잡힌 피드백 다시 생성 (L)
    @PostMapping("/{materialId}/feedback/regenerate")
    public ResponseEntity<com.studybridge.api.dto.FeedbackDTO> regenerateFeedback(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(aiIntegrationService.regenerateFeedback(userDetails.getId(), materialId));
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
            @RequestBody java.util.Map<String, String> request) {
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

    // 84일(12주x7일) 로드맵 재생성 — 기존(레거시 포함) 로드맵을 새 84일 구조로 교체
    @PostMapping("/{materialId}/roadmap/regenerate")
    public ResponseEntity<com.studybridge.api.dto.RoadmapDTO> regenerateRoadmap(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody(required = false) java.util.Map<String, String> body) {
        String level = body != null ? body.getOrDefault("level", body.get("difficulty")) : null;
        return ResponseEntity.ok(aiIntegrationService.regenerateRoadmap(userDetails.getId(), materialId, level));
    }

    // 84일 로드맵 일자(day) 완료 토글
    @PutMapping("/{materialId}/roadmap/days/toggle")
    public ResponseEntity<com.studybridge.api.dto.RoadmapDTO> toggleRoadmapDay(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody java.util.Map<String, Integer> body) {
        int week = body.getOrDefault("week", 0);
        int dayIndex = body.getOrDefault("dayIndex", 0);
        return ResponseEntity.ok(aiIntegrationService.toggleRoadmapDay(userDetails.getId(), materialId, week, dayIndex));
    }

    // 핵심 키워드 개념 정의 (chip 클릭 → GPT/Wikipedia)
    @PostMapping("/{materialId}/keywords/define")
    public ResponseEntity<com.studybridge.api.dto.KeywordDefineDTO.Response> defineKeyword(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody com.studybridge.api.dto.KeywordDefineDTO.Request request) {
        return ResponseEntity.ok(aiIntegrationService.defineKeyword(userDetails.getId(), materialId, request));
    }
}