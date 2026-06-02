package com.studybridge.api.controller;

import com.studybridge.api.dto.StudyGroupDTO;
import com.studybridge.api.service.StudyGroupService;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/study-groups")
public class StudyGroupController {

    private final StudyGroupService studyGroupService;

    // 1. 형성된 스터디 그룹 상세 조회
    @GetMapping("/{id}")
    public ResponseEntity<StudyGroupDTO.Response> getStudyGroup(@PathVariable("id") Long id) {
        return ResponseEntity.ok(studyGroupService.getStudyGroup(id));
    }

    // 2. 형성된 스터디 그룹 최종 멤버 목록 조회
    @GetMapping("/{id}/members")
    public ResponseEntity<List<StudyGroupDTO.MemberResponse>> getMembers(@PathVariable("id") Long id) {
        return ResponseEntity.ok(studyGroupService.getMembers(id));
    }

    // 3. 형성된 스터디 탈퇴
    @DeleteMapping("/{id}/leave")
    public ResponseEntity<Void> leaveStudyGroup(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable("id") Long id) {
        studyGroupService.leaveStudyGroup(userDetails.getId(), id);
        return ResponseEntity.noContent().build();
    }
}
