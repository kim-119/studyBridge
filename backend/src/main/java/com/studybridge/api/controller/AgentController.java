package com.studybridge.api.controller;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.service.AgentService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/agents")
@CrossOrigin(origins = "http://localhost:3000")
public class AgentController {

    private final AgentService agentService;

    // 사용자별 에이전트 목록 조회
    @GetMapping
    public ResponseEntity<List<AgentDTO.Response>> getAgents(@PathVariable Long userId) {
        return ResponseEntity.ok(agentService.getAgentsByUserId(userId));
    }

    // 새로운 에이전트 생성
    @PostMapping
    public ResponseEntity<AgentDTO.Response> createAgent(
            @PathVariable Long userId,
            @Valid @RequestBody AgentDTO.CreateRequest request) {
        
        return ResponseEntity.ok(agentService.createAgent(userId, request));
    }

    // 에이전트 삭제
    @DeleteMapping("/{agentId}")
    public ResponseEntity<Void> deleteAgent(
            @PathVariable Long userId,
            @PathVariable Long agentId) {
        
        agentService.deleteAgent(userId, agentId);
        return ResponseEntity.noContent().build();
    }
}
