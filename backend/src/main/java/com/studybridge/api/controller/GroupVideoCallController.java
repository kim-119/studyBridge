package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupVideoDTO;
import com.studybridge.api.exception.VideoCallException;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupVideoCallService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 그룹스터디 화상통화(OpenVidu) Connection API. 인증은 SecurityConfig(JWT, anyRequest().authenticated()),
 * 그룹 접근 권한(JOINED 멤버)·연결 소유자 검증은 GroupVideoCallService 가 한다. OpenVidu Secret 은 서버에만 있다.
 */
@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupVideoCallController {

    private final GroupVideoCallService videoCallService;

    /** PRIMARY(음성·카메라) 토큰. 본문 없이 호출해도 된다(하위 호환): 응답의 token 필드는 기존과 동일. */
    @PostMapping("/{id}/video/token")
    public ResponseEntity<Map<String, Object>> getVideoToken(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @RequestBody(required = false) GroupVideoDTO.TokenRequest request) {
        log.info("Requesting video call connection token. userId={}, groupId={}", userDetails.getId(), id);
        return ResponseEntity.ok(videoCallService.issuePrimaryToken(userDetails.getId(), id,
                request == null ? null : request.clientInstanceId(),
                request == null ? null : request.deviceType()));
    }

    /**
     * 화면공유(SCREEN) 전용 토큰. 내 active PRIMARY Connection 에 귀속된다(인원 증가 없음). 사용자당 동시 1개.
     * 오류 code: NOT_GROUP_MEMBER(403) · CONNECTION_OWNER_MISMATCH(403) · INVALID_CONNECTION_ID(400)
     *           · PRIMARY_NOT_ACTIVE(409) · SCREEN_ALREADY_ACTIVE(409, details.connectionId)
     */
    @PostMapping("/{id}/video/screen-token")
    public ResponseEntity<Map<String, Object>> getScreenShareToken(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @RequestBody GroupVideoDTO.ScreenTokenRequest request) {
        return ResponseEntity.ok(videoCallService.issueScreenToken(userDetails.getId(), id,
                request.primaryConnectionId(), request.clientInstanceId(), request.deviceType()));
    }

    /** 내 화면공유 Connection 서버측 종료(멱등). 클라이언트 disconnect 유실 시 안전망. */
    @DeleteMapping("/{id}/video/screen/{connectionId}")
    public ResponseEntity<Map<String, Object>> stopScreenShare(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id,
            @PathVariable String connectionId) {
        return ResponseEntity.ok(videoCallService.stopScreenShare(userDetails.getId(), id, connectionId));
    }

    /** 실시간 접속 Source of Truth(OpenVidu active Connection). 참여 인원·ghost 정리에 쓴다. */
    @GetMapping("/{id}/video/connections")
    public ResponseEntity<Map<String, Object>> getVideoConnections(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long id) {
        return ResponseEntity.ok(videoCallService.listActiveConnections(userDetails.getId(), id));
    }

    @ExceptionHandler(VideoCallException.class)
    public ResponseEntity<Map<String, Object>> handleVideoCall(VideoCallException ex) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", ex.getStatus().value());
        payload.put("code", ex.getCode());
        payload.put("message", ex.getMessage());
        if (!ex.getDetails().isEmpty()) payload.put("details", ex.getDetails());
        return ResponseEntity.status(ex.getStatus()).contentType(MediaType.APPLICATION_JSON).body(payload);
    }
}
