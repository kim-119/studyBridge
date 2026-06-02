package com.studybridge.api.controller;

import com.studybridge.api.dto.StudyApplicationDTO;
import com.studybridge.api.dto.StudyGroupDTO;
import com.studybridge.api.dto.StudyRecruitmentDTO;
import com.studybridge.api.service.StudyApplicationService;
import com.studybridge.api.service.StudyRecruitmentService;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/study-recruitments")
public class StudyRecruitmentController {

    private final StudyRecruitmentService studyRecruitmentService;
    private final StudyApplicationService studyApplicationService;

    // 1. 모집글 생성
    @PostMapping
    public ResponseEntity<StudyRecruitmentDTO.Response> createRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody StudyRecruitmentDTO.Request request) {
        return ResponseEntity.ok(studyRecruitmentService.createRecruitment(userDetails.getId(), request));
    }

    // 2. 전체 모집글 조회
    @GetMapping
    public ResponseEntity<List<StudyRecruitmentDTO.Response>> getRecruitments() {
        return ResponseEntity.ok(studyRecruitmentService.getRecruitments());
    }

    // 3. 모집글 키워드 검색
    @GetMapping("/search")
    public ResponseEntity<List<StudyRecruitmentDTO.Response>> searchRecruitments(
            @RequestParam(value = "keyword", required = false) String keyword) {
        return ResponseEntity.ok(studyRecruitmentService.searchRecruitments(keyword));
    }

    // 4. 모집글 상세 조회
    @GetMapping("/{id}")
    public ResponseEntity<StudyRecruitmentDTO.Response> getRecruitment(@PathVariable("id") Long id) {
        return ResponseEntity.ok(studyRecruitmentService.getRecruitment(id));
    }

    // 5. 모집글 수정
    @PutMapping("/{id}")
    public ResponseEntity<StudyRecruitmentDTO.Response> updateRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id,
            @RequestBody StudyRecruitmentDTO.Request request) {
        return ResponseEntity.ok(studyRecruitmentService.updateRecruitment(userDetails.getId(), id, request));
    }

    // 6. 모집글 삭제
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id) {
        studyRecruitmentService.deleteRecruitment(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }

    // 7. 참가 신청
    @PostMapping("/{id}/apply")
    public ResponseEntity<StudyApplicationDTO.Response> applyToJoin(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id) {
        return ResponseEntity.ok(studyApplicationService.applyToJoin(userDetails.getId(), id));
    }

    // 8. 참가 신청 취소 또는 탈퇴
    @DeleteMapping("/{id}/leave")
    public ResponseEntity<Void> leaveRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id) {
        studyApplicationService.leaveRecruitment(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }

    // 9. 리더용 - 지원자 대기 목록 조회
    @GetMapping("/{id}/applications")
    public ResponseEntity<List<StudyApplicationDTO.Response>> getApplications(@PathVariable("id") Long id) {
        return ResponseEntity.ok(studyApplicationService.getApplications(id));
    }

    // 10. 리더용 - 지원자 상태 변경 (승인/거절)
    @PatchMapping("/applications/{applicationId}")
    public ResponseEntity<StudyApplicationDTO.Response> updateApplicationStatus(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("applicationId") Long applicationId,
            @RequestBody StudyApplicationDTO.Request request) {
        return ResponseEntity.ok(studyApplicationService.updateApplicationStatus(userDetails.getId(), applicationId, request.getStatus()));
    }

    // 11. 리더용 - 모집 완료 및 스터디 결성 (Start Study)
    @PostMapping("/{id}/complete")
    public ResponseEntity<StudyGroupDTO.Response> completeRecruitment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id) {
        return ResponseEntity.ok(studyRecruitmentService.completeRecruitment(userDetails.getId(), id));
    }
}
