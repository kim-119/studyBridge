package com.studybridge.api.controller;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.ReportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@Slf4j
@RestController
@RequestMapping("/api/reports")
@RequiredArgsConstructor
public class ReportController {

    private final ReportService reportService;

    // 관리자 권한 확인 헬퍼
    private void verifyAdminRole(CustomUserDetails userDetails) {
        boolean isAdmin = userDetails.getAuthorities().stream()
                .anyMatch(auth -> "ROLE_ADMIN".equals(auth.getAuthority()));
        if (!isAdmin) {
            log.warn("[권한 거부] 비관리자 계정이 관리자 권한 API 호출 시도. 유저 ID: {}", userDetails.getId());
            throw new SecurityException("관리자 권한이 필요합니다.");
        }
    }

    // 유저 신고 등록
    @PostMapping("/user")
    public ResponseEntity<ReportDTO.Response> reportUser(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody ReportDTO.UserReportRequest request) {
        ReportDTO.Response response = reportService.reportUser(userDetails.getId(), request);
        return ResponseEntity.ok(response);
    }

    // 게시글 신고 등록
    @PostMapping("/post")
    public ResponseEntity<ReportDTO.Response> reportPost(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody ReportDTO.PostReportRequest request) {
        ReportDTO.Response response = reportService.reportPost(userDetails.getId(), request);
        return ResponseEntity.ok(response);
    }

    // 신고 내역 목록 조회
    @GetMapping
    public ResponseEntity<List<ReportDTO.Response>> listReports(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        verifyAdminRole(userDetails);
        List<ReportDTO.Response> responses = reportService.listReports();
        return ResponseEntity.ok(responses);
    }

    // 신고 상태 처리 (RESOLVED / REJECTED)
    @PutMapping("/{reportId}/resolve")
    public ResponseEntity<ReportDTO.Response> resolveReport(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long reportId,
            @RequestParam("status") ReportStatus status) {
        verifyAdminRole(userDetails);
        ReportDTO.Response response = reportService.resolveReport(reportId, status);
        return ResponseEntity.ok(response);
    }
}
