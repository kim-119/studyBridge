package com.studybridge.api.controller;

import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.service.ChatService;
import com.studybridge.api.security.domain.CustomUserDetails;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

import java.util.List;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/agent-rooms")
public class ChatController {

    private final ChatService chatService;

    // 멀티 에이전트 채팅방에서 채팅하기
    @PostMapping("/{roomId}/chat")
    public ResponseEntity<ChatDTO.MultiChatResponse> chatWithRoom(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long roomId,
            @Valid @RequestBody ChatDTO.MultiChatRequest request) {

        log.info("chat controller received roomId={} request={}", roomId, request);
        return ResponseEntity.ok(chatService.chatWithRoom(userDetails.getId(), roomId, request));
    }

    // 멀티 에이전트 채팅 — SSE 스트리밍. 리액티브 체인(Flux)을 컨트롤러까지 유지한다:
    //  PRIMARY(ai07) stream → SECONDARY(EC2 :8000) stream → non-stream 폴백은 ChatService/AiMultiChatFailoverService 가
    //  block() 없이 처리하며, 어떤 경우에도 error/done 이벤트로 정상 종료한다(500·premature close 금지).
    @PostMapping(value = "/{roomId}/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> chatStream(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long roomId,
            @Valid @RequestBody ChatDTO.MultiChatRequest request,
            HttpServletResponse response) {

        // SSE가 Nginx/프록시/브라우저에서 버퍼링되지 않도록 응답 헤더를 명시한다.
        //  (Content-Type은 produces로 이미 text/event-stream)
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-cache, no-transform");
        response.setHeader("Connection", "keep-alive");

        log.info("chat stream controller received roomId={}", roomId);
        return chatService.chatStream(userDetails.getId(), roomId, request);
    }

    // 채팅방 내역 조회
    @GetMapping("/{roomId}/history")
    public ResponseEntity<List<ChatDTO.MessageResponse>> getRoomChatHistory(
            @PathVariable Long roomId) {

        return ResponseEntity.ok(chatService.getRoomChatHistory(roomId));
    }
}
