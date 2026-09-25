package com.studybridge.api.controller;

import com.studybridge.api.dto.MindmapNodeMemoDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MindmapNodeMemoService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

/**
 * 마인드맵 노드 메모 API (material 중심).
 *  · nodeId 는 그래프 생성 id 라 슬래시/특수문자가 섞일 수 있어 path 가 아닌 query/body 로 받는다.
 *  · 모든 엔드포인트가 로그인 사용자 기준 + material 소유권 검증(Service) 을 거친다.
 *
 *   GET    /api/materials/{materialId}/mindmap-memo?nodeId=...
 *   PUT    /api/materials/{materialId}/mindmap-memo   body { nodeId, nodeLabel, content }
 *   DELETE /api/materials/{materialId}/mindmap-memo?nodeId=...
 */
@RestController
@RequestMapping("/api/materials/{materialId}/mindmap-memo")
@RequiredArgsConstructor
public class MindmapNodeMemoController {

    private final MindmapNodeMemoService memoService;

    @GetMapping
    public ResponseEntity<MindmapNodeMemoDTO.Response> getMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestParam String nodeId) {
        MindmapNodeMemoDTO.Memo memo = memoService.get(userDetails.getId(), materialId, nodeId);
        return ResponseEntity.ok(MindmapNodeMemoDTO.Response.of(memo));
    }

    @PutMapping
    public ResponseEntity<MindmapNodeMemoDTO.Response> saveMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestBody MindmapNodeMemoDTO.SaveRequest request) {
        MindmapNodeMemoDTO.Memo memo = memoService.upsert(userDetails.getId(), materialId, request);
        return ResponseEntity.ok(MindmapNodeMemoDTO.Response.of(memo));
    }

    @DeleteMapping
    public ResponseEntity<MindmapNodeMemoDTO.Response> deleteMemo(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long materialId,
            @RequestParam String nodeId) {
        memoService.delete(userDetails.getId(), materialId, nodeId);
        return ResponseEntity.ok(MindmapNodeMemoDTO.Response.of(null));
    }
}
