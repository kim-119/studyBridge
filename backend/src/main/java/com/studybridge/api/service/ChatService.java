package com.studybridge.api.service;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.AgentRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ChatService {

    private final AgentRepository agentRepository;
    private final AgentChatRoomRepository agentChatRoomRepository;
    private final UserRepository userRepository;
    private final ChatMessageRepository chatMessageRepository;
    private final WebClient fastApiWebClient;

    @Transactional
    public ChatDTO.MultiChatResponse chatWithRoom(Long userId, Long roomId, ChatDTO.MultiChatRequest request) {
        AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                .orElseThrow(() -> new RuntimeException("해당 채팅방을 찾을 수 없습니다."));

        if (!room.getUser().getId().equals(userId)) {
            throw new RuntimeException("해당 채팅방에 접근할 권한이 없습니다.");
        }

        // 1. 사용자의 메시지 저장
        saveRoomMessage(room, null, request.getMessage(), "USER");

        // FastAPI의 /api/ai/multi-chat 요구사항에 맞춰 데이터 구성
        List<Map<String, String>> agentsList = room.getAgents().stream()
                .map(agent -> Map.of(
                        "name", agent.getName(),
                        "role", agent.getRole(),
                        "personality", agent.getPersona(),
                        "tone", agent.getTone() != null ? agent.getTone() : "친절하게",
                        "goal", agent.getGoal() != null ? agent.getGoal() : "학습 도움"
                ))
                .collect(Collectors.toList());

        Map<String, Object> requestBody = Map.of(
                "message", request.getMessage(),
                "agents", agentsList
        );

        Map<String, Object> response;
        try {
            response = fastApiWebClient.post()
                    .uri("/api/ai/multi-chat")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();
        } catch (Exception e) {
            throw new RuntimeException("AI 서버와 통신 중 오류가 발생했습니다: " + e.getMessage());
        }

        List<ChatDTO.AgentReply> replies = new java.util.ArrayList<>();
        if (response != null && response.containsKey("answers")) {
            List<Map<String, Object>> answers = (List<Map<String, Object>>) response.get("answers");
            
            for (int i = 0; i < answers.size(); i++) {
                Map<String, Object> answerMap = answers.get(i);
                String aiAnswer = answerMap.get("answer").toString();
                String agentName = answerMap.get("agentName").toString();
                
                Agent targetAgent = room.getAgents().stream()
                        .filter(a -> a.getName().equals(agentName))
                        .findFirst()
                        .orElse(room.getAgents().get(Math.min(i, room.getAgents().size() - 1)));

                // 2. 각 AI의 응답 저장
                saveRoomMessage(room, targetAgent, aiAnswer, "AI");

                replies.add(ChatDTO.AgentReply.builder()
                        .agentId(targetAgent.getId())
                        .answer(aiAnswer)
                        .build());
            }
        }

        return ChatDTO.MultiChatResponse.builder()
                .replies(replies)
                .build();
    }

    public List<ChatDTO.MessageResponse> getRoomChatHistory(Long roomId) {
        return chatMessageRepository.findByAgentChatRoomIdOrderByCreatedAtAsc(roomId).stream()
                .map(msg -> ChatDTO.MessageResponse.builder()
                        .id(msg.getId())
                        .content(msg.getContent())
                        .sender(msg.getSender())
                        .agentId(msg.getAgent() != null ? msg.getAgent().getId() : null)
                        .createdAt(msg.getCreatedAt())
                        .build())
                .collect(Collectors.toList());
    }

    private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender) {
        ChatMessage message = ChatMessage.builder()
                .agentChatRoom(room)
                .agent(agent)
                .content(content)
                .sender(sender)
                .build();
        chatMessageRepository.save(message);
    }
}
