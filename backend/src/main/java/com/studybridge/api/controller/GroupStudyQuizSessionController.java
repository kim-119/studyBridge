package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyQuizSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupStudyQuizSessionController {

    private final GroupStudyQuizSessionService quizSessionService;

    @GetMapping("/{groupId}/quiz/session")
    public ResponseEntity<GroupStudySocketDTO.QuizSessionPayload> getCurrentSession(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId) {
        return ResponseEntity.ok(quizSessionService.getCurrentSession(groupId, userDetails.getId()));
    }
}
