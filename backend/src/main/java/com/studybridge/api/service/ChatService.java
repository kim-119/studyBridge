package com.studybridge.api.service;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
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
    private final UserRepository userRepository;
    private final ChatMessageRepository chatMessageRepository;
    private final WebClient fastApiWebClient;

    @Transactional
    public AgentDTO.ChatResponse chatWithAgent(Long userId, Long agentId, AgentDTO.ChatRequest request) {
        Agent agent = agentRepository.findById(agentId)
                .orElseThrow(() -> new RuntimeException("해당 AI 에이전트를 찾을 수 없습니다."));

        if (!agent.getUser().getId().equals(userId)) {
            throw new RuntimeException("해당 에이전트와 대화할 권한이 없습니다.");
        }

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

        // FastAPI 서버에 보낼 프롬프트 생성
        String prompt = buildPrompt(agent, request.getMessage());

        Map<String, String> requestBody = Map.of("prompt", prompt);

        Map<String, Object> response;
        try {
            response = fastApiWebClient.post()
                    .uri("/ai/chat")
                    .bodyValue(requestBody)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .block();
        } catch (Exception e) {
            throw new RuntimeException("AI 서버와 통신 중 오류가 발생했습니다: " + e.getMessage());
        }

        String aiAnswer = "AI 응답을 가져오지 못했습니다.";
        if (response != null && response.containsKey("result")) {
            aiAnswer = response.get("result").toString();
        }

        // DB에 채팅 내역 저장
        saveMessage(agent, user, request.getMessage(), "USER");
        saveMessage(agent, user, aiAnswer, "AI");

        return AgentDTO.ChatResponse.builder()
                .agentId(agent.getId())
                .agentName(agent.getName())
                .role(agent.getRole())
                .answer(aiAnswer)
                .build();
    }

    public List<ChatDTO.MessageResponse> getChatHistory(Long agentId) {
        return chatMessageRepository.findByAgentIdOrderByCreatedAtAsc(agentId).stream()
                .map(msg -> ChatDTO.MessageResponse.builder()
                        .id(msg.getId())
                        .content(msg.getContent())
                        .sender(msg.getSender())
                        .createdAt(msg.getCreatedAt())
                        .build())
                .collect(Collectors.toList());
    }

    private String buildPrompt(Agent agent, String userMessage) {
        StringBuilder sb = new StringBuilder();
        sb.append("당신은 다음 설정에 따라 사용자를 돕는 커스텀 AI 에이전트입니다.\n");
        
        sb.append("[에이전트 정보]\n");
        sb.append("- 이름: ").append(agent.getName()).append("\n");
        sb.append("- 역할: ").append(agent.getRole()).append("\n");
        sb.append("- 페르소나: ").append(agent.getPersona()).append("\n");

        if (agent.getTone() != null && !agent.getTone().isBlank()) {
            sb.append("- 말투: ").append(agent.getTone()).append("\n");
        }
        if (agent.getGoal() != null && !agent.getGoal().isBlank()) {
            sb.append("- 목표: ").append(agent.getGoal()).append("\n");
        }

        sb.append("\n[사용자 질문]\n").append(userMessage).append("\n");
        sb.append("위 설정을 반드시 반영해서 한국어로 답변해 주세요.");

        return sb.toString();
    }

    private void saveMessage(Agent agent, User user, String content, String sender) {
        ChatMessage message = ChatMessage.builder()
                .agent(agent)
                .user(user)
                .content(content)
                .sender(sender)
                .build();
        chatMessageRepository.save(message);
    }
}
