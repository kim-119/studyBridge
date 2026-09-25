package com.studybridge.api.controller;

import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.OpenViduService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupVideoCallController {

    private final OpenViduService openViduService;
    private final GroupStudyMemberRepository groupStudyMemberRepository;

    @PostMapping("/{id}/video/token")
    public ResponseEntity<Map<String, String>> getVideoToken(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        
        log.info("Requesting video call connection token. userId={}, groupId={}", userDetails.getId(), id);

        boolean isMember = groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                id, userDetails.getId(), GroupStudyMemberStatus.JOINED);

        if (!isMember) {
            log.warn("Access denied. User is not a member of group study. userId={}, groupId={}", userDetails.getId(), id);
            return ResponseEntity.status(403).build();
        }

        String sessionId = "group_study_" + id;

        openViduService.createSession(sessionId);

        String token = openViduService.generateToken(sessionId);

        return ResponseEntity.ok(Map.of("token", token));
    }
}
