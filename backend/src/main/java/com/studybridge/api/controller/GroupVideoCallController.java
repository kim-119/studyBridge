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
        return ResponseEntity.status(ex.getStatus()).contentType(MediaType.APPLICATION_JSON).body(payload);
    }
}
