package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudyDTO;
import com.studybridge.api.dto.GroupStudyInvitationDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyInvitationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

/**
 * 비공개 그룹스터디 초대 링크 API. 모든 엔드포인트는 인증 필수(401), 관리 엔드포인트는 방장만(403).
 *  POST   /api/groups/{id}/invitations                  초대 링크 생성(재생성 = 기존 활성 링크 폐기)
 *  GET    /api/groups/{id}/invitations/active           활성 링크 목록(방장)
 *  DELETE /api/groups/{id}/invitations/{invitationId}   링크 폐기
 *  GET    /api/groups/invite/{token}                    링크 미리보기(유효성 + 그룹 요약)
 *  POST   /api/groups/invite/{token}/accept             링크로 가입(즉시 MEMBER)
 */
@RestController
@RequestMapping("/api/groups")
@RequiredArgsConstructor
@Slf4j
public class GroupStudyInvitationController {

    private final GroupStudyInvitationService invitationService;

    @PostMapping("/{id}/invitations")
    public ResponseEntity<GroupStudyInvitationDTO.Response> create(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @RequestBody(required = false) GroupStudyInvitationDTO.CreateRequest request) {
        log.info("Create group invitation. userId={}, groupId={}", userDetails.getId(), id);
        return ResponseEntity.ok(invitationService.create(userDetails.getId(), id, request));
    }

    @GetMapping("/{id}/invitations/active")
    public ResponseEntity<List<GroupStudyInvitationDTO.Response>> listActive(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(invitationService.listActive(userDetails.getId(), id));
    }

    @DeleteMapping("/{id}/invitations/{invitationId}")
    public ResponseEntity<Void> revoke(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @PathVariable Long invitationId) {
        log.info("Revoke group invitation. userId={}, groupId={}, invitationId={}", userDetails.getId(), id, invitationId);
        invitationService.revoke(userDetails.getId(), id, invitationId);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/invite/{token}")
    public ResponseEntity<GroupStudyInvitationDTO.Preview> preview(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable String token) {
        return ResponseEntity.ok(invitationService.preview(userDetails.getId(), token));
    }

    @PostMapping("/invite/{token}/accept")
    public ResponseEntity<GroupStudyDTO.Response> accept(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable String token,
            @RequestBody(required = false) GroupStudyInvitationDTO.AcceptRequest request) {
        log.info("Accept group invitation. userId={}", userDetails.getId());
        return ResponseEntity.ok(invitationService.accept(userDetails.getId(), token, request));
    }
}
