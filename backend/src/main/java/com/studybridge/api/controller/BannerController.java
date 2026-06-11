package com.studybridge.api.controller;

import com.studybridge.api.dto.BannerDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.BannerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.Map;

@Slf4j
@RestController
@RequiredArgsConstructor
public class BannerController {

    private final BannerService bannerService;

    /** 메인 배너 설정 조회 (공개). 외부 원본 URL/MCP 토큰은 노출하지 않고 S3 presigned URL만 반환. */
    @GetMapping("/api/banners/main")
    public ResponseEntity<BannerDTO.MainBanner> getMainBanner() {
        return ResponseEntity.ok(bannerService.getMainBanner());
    }

    /** 배너 이미지 S3 재동기화 (관리자 전용). */
    @PostMapping("/api/admin/banners/main/sync-s3")
    public ResponseEntity<Map<String, String>> syncMainBanner(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        boolean isAdmin = userDetails != null && userDetails.getAuthorities().stream()
                .anyMatch(auth -> "ROLE_ADMIN".equals(auth.getAuthority()));
        if (!isAdmin) {
            log.warn("[배너] 비관리자 배너 동기화 시도. userId={}", userDetails != null ? userDetails.getId() : null);
            throw new SecurityException("관리자 권한이 필요합니다.");
        }
        String key = bannerService.syncImageToS3();
        return ResponseEntity.ok(Map.of("status", "SUCCESS", "s3Key", key));
    }
}
