package com.studybridge.api.controller;

import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.service.ChatService;
import com.studybridge.api.security.domain.CustomUserDetails;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/chat")
public class ChatController {

    private final ChatService chatService;

    // 멀티 에이전트 채팅방에서 채팅하기
    @PostMapping("/rooms/{roomId}")
    public ResponseEntity<ChatDTO.MultiChatResponse> chatWithRoom(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long roomId,
            @Valid @RequestBody ChatDTO.MultiChatRequest request) {

        return ResponseEntity.ok(chatService.chatWithRoom(userDetails.getId(), roomId, request));
    }

    // 채팅방 내역 조회
    @GetMapping("/rooms/{roomId}/history")
    public ResponseEntity<List<ChatDTO.MessageResponse>> getRoomChatHistory(
            @PathVariable Long roomId) {

        return ResponseEntity.ok(chatService.getRoomChatHistory(roomId));
    }
}
