package com.studybridge.api.controller;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.ReportService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/reports")
@RequiredArgsConstructor
public class ReportController {

    private final ReportService reportService;

    // 사용자: 특정 대상(자료, 유저 등)을 신고
    @PostMapping
    public ResponseEntity<?> submitReport(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @Valid @RequestBody ReportDTO.ReportRequest request) {
        if (userDetails == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            ReportDTO.ReportResponse response = reportService.submitReport(userDetails.getId(), request);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }
}
