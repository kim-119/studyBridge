package com.studybridge.api.controller;

import com.studybridge.api.dto.MindmapSemanticGraphDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.MindmapSemanticGraphService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 마인드맵 Semantic Graph 릴레이(인증 필수). 브라우저 → 여기 → AI07.
 *  · 업스트림 FAILED/404/timeout 도 HTTP 200 + status=FAILED 로 내려준다(브라우저가 상태를 명시 표시). 4xx 는 요청/권한 오류만.
 */
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/mindmap")
public class MindmapSemanticGraphController {

    private final MindmapSemanticGraphService mindmapSemanticGraphService;

    @PostMapping("/semantic-graph")
    public ResponseEntity<MindmapSemanticGraphDTO.Response> semanticGraph(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody MindmapSemanticGraphDTO.Request request) {
        return ResponseEntity.ok(mindmapSemanticGraphService.semanticGraph(userDetails.getId(), request));
    }
}
