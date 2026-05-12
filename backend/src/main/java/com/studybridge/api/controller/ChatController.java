package com.studybridge.api.controller;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/agents/{agentId}/chat")
@CrossOrigin(origins = "http://localhost:3000")
public class ChatController {

    private final ChatService chatService;

    // 특정 에이전트와 채팅하기
    @PostMapping
    public ResponseEntity<AgentDTO.ChatResponse> chatWithAgent(
            @PathVariable Long userId,
            @PathVariable Long agentId,
            @Valid @RequestBody AgentDTO.ChatRequest request) {
        
        return ResponseEntity.ok(chatService.chatWithAgent(userId, agentId, request));
    }

    // 채팅 내역 조회
    @GetMapping("/history")
    public ResponseEntity<List<ChatDTO.MessageResponse>> getChatHistory(
            @PathVariable Long userId,
            @PathVariable Long agentId) {
        
        return ResponseEntity.ok(chatService.getChatHistory(agentId));
    }
}
