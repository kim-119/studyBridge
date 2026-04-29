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

        // FastAPI 서버의 프롬프트 양식 구성
        String prompt = String.format(
                "너는 StudyBridge 플랫폼의 사용자 커스텀 AI 에이전트다.\n\n" +
                "[에이전트 이름]\n%s\n\n" +
                "[에이전트 역할]\n%s\n\n" +
                "[페르소나]\n%s\n\n" +
                "[말투]\n%s\n\n" +
                "[목표]\n%s\n\n" +
                "[사용자 질문]\n%s\n\n" +
                "위 설정을 반드시 반영해서 한국어로 답변해라.\n" +
                "답변은 너무 길게 늘어놓지 말고, 학습자가 바로 이해할 수 있게 구조화해라.",
                agent.getName(), agent.getRole(), agent.getPersona(),
                agent.getTone(), agent.getGoal(), request.getMessage()
        );

        Map<String, String> requestBody = Map.of("prompt", prompt);

        Map<String, Object> response;
        try {
            response = fastApiWebClient.post()
                    .uri("/ai/gemini")
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
