package com.studybridge.api.controller;

import com.studybridge.api.dto.AgentRoomDTO;
import com.studybridge.api.service.AgentChatRoomService;
import com.studybridge.api.security.domain.CustomUserDetails;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/agent-rooms")
public class AgentChatRoomController {

    private final AgentChatRoomService agentChatRoomService;

    // 새로운 멀티 에이전트 채팅방 생성
    @PostMapping
    public ResponseEntity<AgentRoomDTO.Response> createRoom(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @Valid @RequestBody AgentRoomDTO.CreateRequest request) {
        return ResponseEntity.ok(agentChatRoomService.createRoomWithAgents(userDetails.getId(), request));
    }

    // 사용자의 채팅방 목록 조회
    @GetMapping
    public ResponseEntity<List<AgentRoomDTO.Response>> getRooms(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        return ResponseEntity.ok(agentChatRoomService.getRoomsByUserId(userDetails.getId()));
    }

    // 채팅방 삭제 (속해있는 에이전트, 메시지 모두 삭제됨)
    @DeleteMapping("/{roomId}")
    public ResponseEntity<Void> deleteRoom(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long roomId) {
        agentChatRoomService.deleteRoom(userDetails.getId(), roomId);
        return ResponseEntity.noContent().build();
    }
}
