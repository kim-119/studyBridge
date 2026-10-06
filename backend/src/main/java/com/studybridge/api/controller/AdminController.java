package com.studybridge.api.controller;

import com.studybridge.api.dto.AdminDTO;
import com.studybridge.api.dto.GroupStudyReportDTO;
import com.studybridge.api.dto.InquiryDTO;
import com.studybridge.api.entity.Inquiry;
import com.studybridge.api.repository.InquiryRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.AdminService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import java.util.List;
import java.util.stream.Collectors;
import java.time.format.DateTimeFormatter;

@Slf4j
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;
    private final InquiryRepository inquiryRepository;

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

    // 그룹스터디 신고 전체 내역 조회
    @GetMapping("/reports/groups")
    public ResponseEntity<List<GroupStudyReportDTO.Response>> listGroupStudyReports(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        verifyAdminRole(userDetails);
        List<GroupStudyReportDTO.Response> responses = adminService.listAllGroupStudyReports();
        return ResponseEntity.ok(responses);
    }

    // 그룹스터디 강제 삭제
    @DeleteMapping("/groups/{groupId}")
    public ResponseEntity<AdminDTO.ModerationResponse> crushGroupStudy(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId) {
        verifyAdminRole(userDetails);
        AdminDTO.ModerationResponse response = adminService.crushGroupStudy(groupId);
        return ResponseEntity.ok(response);
    }

    // 문의 목록 전체 조회 (관리자 전용)
    @GetMapping("/inquiries")
    public ResponseEntity<List<InquiryDTO.Response>> listInquiries(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        verifyAdminRole(userDetails);
        List<Inquiry> inquiries = inquiryRepository.findAllByOrderByCreatedAtDesc();
        DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
        List<InquiryDTO.Response> responses = inquiries.stream()
                .map(inquiry -> new InquiryDTO.Response(
                        inquiry.getId(),
                        inquiry.getType(),
                        inquiry.getTitle(),
                        inquiry.getContent(),
                        inquiry.getReply(),
                        inquiry.getStatus(),
                        inquiry.getAuthor().getDisplayName(),
                        inquiry.getCreatedAt() != null ? inquiry.getCreatedAt().format(formatter) : java.time.LocalDate.now().format(formatter)
                ))
                .collect(Collectors.toList());
        return ResponseEntity.ok(responses);
    }

    // 문의 답변 등록 (관리자 전용)
    @PostMapping("/inquiries/{inquiryId}/reply")
    public ResponseEntity<Void> replyInquiry(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long inquiryId,
            @RequestBody InquiryDTO.ReplyRequest request) {
        verifyAdminRole(userDetails);
        Inquiry inquiry = inquiryRepository.findById(inquiryId)
                .orElseThrow(() -> new IllegalArgumentException("문의 건이 존재하지 않습니다."));
        
        inquiry.setReply(request.getReply());
        inquiry.setStatus("답변완료");
        inquiryRepository.save(inquiry);
        
        return ResponseEntity.ok().build();
    }
}
