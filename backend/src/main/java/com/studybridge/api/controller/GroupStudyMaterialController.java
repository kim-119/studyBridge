package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudyMaterialDTO;
import com.studybridge.api.dto.GroupStudyQuizDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyMaterialService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.util.List;
import java.util.Map;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupStudyMaterialController {

    private final GroupStudyMaterialService groupStudyMaterialService;

    // 그룹원 전용 PDF 학습 자료를 업로드하고 자동으로 퀴즈 세트를 생성
    @PostMapping("/{groupId}/materials/upload-quiz")
    public ResponseEntity<GroupStudyMaterialDTO> uploadQuizMaterial(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestParam("title") String title,
            @RequestParam("file") MultipartFile file) throws IOException {

        log.info("Received request to upload material & generate quiz. uploaderId={}, groupId={}, title={}",
                userDetails.getId(), groupId, title);

        GroupStudyMaterialDTO response = groupStudyMaterialService.uploadMaterialAndGenerateQuiz(
                userDetails.getId(), groupId, title, file);

        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }

    // 특정 스터디 룸 내부의 모든 공유 자료 목록을 조회
    @GetMapping("/{groupId}/materials")
    public ResponseEntity<List<GroupStudyMaterialDTO>> getMaterials(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId) {

        log.info("Request for materials list. userId={}, groupId={}", userDetails.getId(), groupId);
        List<GroupStudyMaterialDTO> response = groupStudyMaterialService.getMaterials(userDetails.getId(), groupId);
        return ResponseEntity.ok(response);
    }

    // 특정 스터디 룸 내부의 모든 생성 퀴즈 목록을 조회
    @GetMapping("/{groupId}/quizzes")
    public ResponseEntity<List<GroupStudyQuizDTO.QuizResponse>> getGroupQuizzes(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId) {

        log.info("Request for group quizzes list. userId={}, groupId={}", userDetails.getId(), groupId);
        List<GroupStudyQuizDTO.QuizResponse> response = groupStudyMaterialService.getGroupQuizzes(
                userDetails.getId(), groupId);
        return ResponseEntity.ok(response);
    }

    // 다운로드 URL 저장
    @GetMapping("/materials/{materialId}/download")
    public ResponseEntity<Map<String, String>> getDownloadUrl(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {

        log.info("Request download url. userId={}, materialId={}", userDetails.getId(), materialId);
        String url = groupStudyMaterialService.downloadMaterialUrl(userDetails.getId(), materialId);
        return ResponseEntity.ok(Map.of("downloadUrl", url));
    }
}
