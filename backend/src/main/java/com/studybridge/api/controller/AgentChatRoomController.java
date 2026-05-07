package com.studybridge.api.controller;

import com.studybridge.api.dto.AgentRoomDTO;
import com.studybridge.api.service.AgentChatRoomService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/agent-rooms")
@CrossOrigin(origins = "http://localhost:3000")
public class AgentChatRoomController {

    private final AgentChatRoomService agentChatRoomService;

    // 새로운 멀티 에이전트 채팅방 생성
    @PostMapping
    public ResponseEntity<AgentRoomDTO.Response> createRoom(
            @PathVariable Long userId,
            @Valid @RequestBody AgentRoomDTO.CreateRequest request) {
        return ResponseEntity.ok(agentChatRoomService.createRoomWithAgents(userId, request));
    }

    // 사용자의 채팅방 목록 조회
    @GetMapping
    public ResponseEntity<List<AgentRoomDTO.Response>> getRooms(@PathVariable Long userId) {
        return ResponseEntity.ok(agentChatRoomService.getRoomsByUserId(userId));
    }

    // 채팅방 삭제 (속해있는 에이전트, 메시지 모두 삭제됨)
    @DeleteMapping("/{roomId}")
    public ResponseEntity<Void> deleteRoom(
            @PathVariable Long userId,
            @PathVariable Long roomId) {
        agentChatRoomService.deleteRoom(userId, roomId);
        return ResponseEntity.noContent().build();
    }
}
