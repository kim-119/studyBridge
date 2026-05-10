package com.studybridge.api.controller;

import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.service.ChatService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/chat")
@CrossOrigin(origins = "http://localhost:3000")
public class ChatController {

    private final ChatService chatService;

    // 멀티 에이전트 채팅방에서 채팅하기
    @PostMapping("/rooms/{roomId}")
    public ResponseEntity<ChatDTO.MultiChatResponse> chatWithRoom(
            @PathVariable Long userId,
            @PathVariable Long roomId,
            @Valid @RequestBody ChatDTO.MultiChatRequest request) {

        return ResponseEntity.ok(chatService.chatWithRoom(userId, roomId, request));
    }

    // 채팅방 내역 조회
    @GetMapping("/rooms/{roomId}/history")
    public ResponseEntity<List<ChatDTO.MessageResponse>> getRoomChatHistory(
            @PathVariable Long userId,
            @PathVariable Long roomId) {

        return ResponseEntity.ok(chatService.getRoomChatHistory(roomId));
    }
}
