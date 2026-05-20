package com.studybridge.api.controller;

import com.studybridge.api.dto.MaterialDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MaterialService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequestMapping("/api/materials")
@RequiredArgsConstructor
public class MaterialController {

    private final MaterialService materialService;

    // 내 자료보관함 전체 조회 (100% JWT 기반)
    @GetMapping
    public ResponseEntity<List<MaterialDTO>> getMyMaterials(@AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(materialService.getUserMaterials(userDetails.getId()));
    }

    // 특정 자료 상세 조회 (철벽 보안 IDOR 취약점 방어 가드 탑재)
    @GetMapping("/{materialId}")
    public ResponseEntity<MaterialDTO> getMaterialDetail(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId) {
        return ResponseEntity.ok(materialService.getMaterial(userDetails.getId(), materialId));
    }
}