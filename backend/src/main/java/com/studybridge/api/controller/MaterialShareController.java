package com.studybridge.api.controller;

import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MaterialShareService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

/**
 * 개인 PDF 자료의 그룹 공유 — 공유된 그룹의 JOINED 멤버가 그 자료의 퀴즈에 응시하고 퀴즈별 랭킹에 참여한다.
 * 오류 {status, code, message}: 404 MATERIAL_NOT_FOUND/GROUP_NOT_FOUND, 403 FORBIDDEN, 400 NOT_SHAREABLE/GROUP_REQUIRED.
 */
@RestController
@RequiredArgsConstructor
public class MaterialShareController {

    private final MaterialShareService shareService;

    @PostMapping("/api/materials/{materialId}/shares")
    public ResponseEntity<Map<String, Object>> share(@AuthenticationPrincipal CustomUserDetails userDetails,
                                                     @PathVariable Long materialId,
                                                     @RequestBody(required = false) Map<String, Object> body) {
        Object g = body == null ? null : body.get("groupId");
        Long groupId = g instanceof Number n ? n.longValue() : g == null ? null : Long.valueOf(String.valueOf(g));
        return ResponseEntity.ok(shareService.share(userDetails.getId(), materialId, groupId));
    }

    @GetMapping("/api/materials/{materialId}/shares")
    public ResponseEntity<List<Map<String, Object>>> shares(@AuthenticationPrincipal CustomUserDetails userDetails,
                                                            @PathVariable Long materialId) {
        return ResponseEntity.ok(shareService.sharesOf(userDetails.getId(), materialId));
    }

    @DeleteMapping("/api/materials/{materialId}/shares/{groupId}")
    public ResponseEntity<Void> unshare(@AuthenticationPrincipal CustomUserDetails userDetails,
                                        @PathVariable Long materialId, @PathVariable Long groupId) {
        shareService.unshare(userDetails.getId(), materialId, groupId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/api/groups/{groupId}/shared-materials")
    public ResponseEntity<List<Map<String, Object>>> sharedToGroup(@AuthenticationPrincipal CustomUserDetails userDetails,
                                                                   @PathVariable Long groupId) {
        return ResponseEntity.ok(shareService.sharedToGroup(userDetails.getId(), groupId));
    }
}
