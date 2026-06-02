package com.studybridge.api.controller;

import com.studybridge.api.dto.AdminDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.AdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;

    // 관리자 권한 확인 헬퍼
    private void verifyAdminRole(CustomUserDetails userDetails) {
        boolean isAdmin = userDetails.getAuthorities().stream()
                .anyMatch(auth -> "ROLE_ADMIN".equals(auth.getAuthority()));
        if (!isAdmin) {
            log.warn("[권한 거부] 비관리자 계정이 관리자 API 호출 시도. 유저 ID: {}", userDetails.getId());
            throw new SecurityException("관리자 권한이 필요합니다.");
        }
    }

    // 유저 일시 정지
    @PostMapping("/users/{userId}/suspend")
    public ResponseEntity<AdminDTO.ModerationResponse> suspendUser(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long userId,
            @RequestBody AdminDTO.UserSuspendRequest request) {
        verifyAdminRole(userDetails);
        AdminDTO.ModerationResponse response = adminService.suspendUser(userId, request);
        return ResponseEntity.ok(response);
    }

    // 유저 영구 정지
    @PostMapping("/users/{userId}/ban")
    public ResponseEntity<AdminDTO.ModerationResponse> banUser(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long userId,
            @RequestBody AdminDTO.UserBanRequest request) {
        verifyAdminRole(userDetails);
        AdminDTO.ModerationResponse response = adminService.banUserPermanently(userId, request);
        return ResponseEntity.ok(response);
    }

    // 게시물 강제 삭제
    @DeleteMapping("/blogs/{blogId}")
    public ResponseEntity<AdminDTO.ModerationResponse> crushPost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long blogId) {
        verifyAdminRole(userDetails);
        AdminDTO.ModerationResponse response = adminService.crushPost(blogId);
        return ResponseEntity.ok(response);
    }

    // 댓글 강제 삭제
    @DeleteMapping("/comments/{commentId}")
    public ResponseEntity<AdminDTO.ModerationResponse> crushComment(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long commentId) {
        verifyAdminRole(userDetails);
        AdminDTO.ModerationResponse response = adminService.crushComment(commentId);
        return ResponseEntity.ok(response);
    }
}
