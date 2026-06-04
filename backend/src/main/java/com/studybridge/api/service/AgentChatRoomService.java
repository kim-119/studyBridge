package com.studybridge.api.service;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.dto.AgentRoomDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
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
public class AgentChatRoomService {

        private final AgentChatRoomRepository agentChatRoomRepository;
        private final AgentRepository agentRepository;
        private final UserRepository userRepository;
        private final ChatMessageRepository chatMessageRepository;
        private final WebClient fastApiWebClient;

        // 멀티 에이전트 채팅방 생성
        @Transactional
        public AgentRoomDTO.Response createRoomWithAgents(Long userId, AgentRoomDTO.CreateRequest request) {
                User user = userRepository.findById(userId)
                                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

                if (request.getAgents() != null && request.getAgents().size() > 3) {
                        throw new RuntimeException("에이전트는 최대 3명까지 생성할 수 있습니다.");
                }

                AgentChatRoom room = AgentChatRoom.builder()
                                .user(user)
                                .roomName(request.getRoomName())
                                .build();

                AgentChatRoom savedRoom = agentChatRoomRepository.save(room);

                List<Agent> agents = request.getAgents().stream()
                                .map(agentReq -> Agent.builder()
                                                .agentChatRoom(savedRoom)
                                                .name(agentReq.getName())
                                                .role(agentReq.getRole())
                                                .persona(agentReq.getPersona())
                                                .tone(agentReq.getTone())
                                                .goal(agentReq.getGoal())
                                                .build())
                                .collect(Collectors.toList());

                agentRepository.saveAll(agents);

                return convertToRoomResponse(savedRoom, agents);
        }

        public List<AgentRoomDTO.Response> getRoomsByUserId(Long userId) {
                return agentChatRoomRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                                .map(room -> convertToRoomResponse(room, room.getAgents()))
                                .collect(Collectors.toList());
        }

        // 채팅방 삭제
        @Transactional
        public void deleteRoom(Long userId, Long roomId) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new RuntimeException("채팅방을 찾을 수 없습니다."));

                if (!room.getUser().getId().equals(userId)) {
                        throw new RuntimeException("삭제 권한이 없습니다.");
                }

                agentChatRoomRepository.delete(room);
        }

        // 개인 에이전트 채팅방 대화 및 DB 저장
        @Transactional
        public AgentRoomDTO.ChatResponse chatWithAgent(Long userId, Long roomId, AgentRoomDTO.ChatRequest request) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new RuntimeException("채팅방을 찾을 수 없습니다."));

                if (!room.getUser().getId().equals(userId)) {
                        throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
                }

                // 에이전트 조회 (기본적으로 채팅방의 첫 번째 에이전트와 대화)
                Agent agent = room.getAgents().stream()
                                .findFirst()
                                .orElseThrow(() -> new RuntimeException("채팅방에 생성된 에이전트가 존재하지 않습니다."));

                // 1. 유저 질문 저장
                ChatMessage userMessage = ChatMessage.builder()
                                .agentChatRoom(room)
                                .content(request.getQuestion())
                                .sender("USER")
                                .build();
                chatMessageRepository.save(userMessage);

                // 2. FastAPI 호출 준비
                String knowledgeLevel = (request.getKnowledgeLevel() != null && !request.getKnowledgeLevel().isBlank())
                                ? request.getKnowledgeLevel()
                                : "학사";
                String personality = (request.getPersonality() != null && !request.getPersonality().isBlank())
                                ? request.getPersonality()
                                : (agent.getTone() != null ? agent.getTone() : "전문적");

                Map<String, Object> apiRequest = Map.of(
                                "question", request.getQuestion(),
                                "agent_name", agent.getName(),
                                "knowledge_level", knowledgeLevel,
                                "personality", personality,
                                "enable_tiki_taka", false,
                                "use_gpt_validation", false
                );

                Map response;
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/chat")
                                        .bodyValue(apiRequest)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block();
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버와 통신 중 오류가 발생했습니다: " + e.getMessage());
                }

                String answer = (response != null && response.get("answer") != null)
                                ? response.get("answer").toString()
                                : "답변을 가져오지 못했습니다.";

                // 3. AI 답변 저장
                ChatMessage aiMessage = ChatMessage.builder()
                                .agentChatRoom(room)
                                .agent(agent)
                                .content(answer)
                                .sender("AI")
                                .build();
                chatMessageRepository.save(aiMessage);

                List<String> processLogs = (response != null && response.get("process_logs") instanceof List)
                                ? (List<String>) response.get("process_logs")
                                : List.of();

                return AgentRoomDTO.ChatResponse.builder()
                                .answer(answer)
                                .status((response != null && response.get("status") != null) ? response.get("status").toString() : "complete")
                                .knowledgeLevel(knowledgeLevel)
                                .personality(personality)
                                .processLogs(processLogs)
                                .validationJobId((response != null && response.get("validation_job_id") != null) ? response.get("validation_job_id").toString() : null)
                                .build();
        }

        private AgentRoomDTO.Response convertToRoomResponse(AgentChatRoom room, List<Agent> agents) {
                List<AgentDTO.Response> agentResponses = agents.stream()
                                .map(agent -> AgentDTO.Response.builder()
                                                .id(agent.getId())
                                                .name(agent.getName())
                                                .role(agent.getRole())
                                                .persona(agent.getPersona())
                                                .tone(agent.getTone())
                                                .goal(agent.getGoal())
                                                .build())
                                .collect(Collectors.toList());

                return AgentRoomDTO.Response.builder()
                                .roomId(room.getId())
                                .roomName(room.getRoomName())
                                .agents(agentResponses)
                                .createdAt(room.getCreatedAt() != null ? room.getCreatedAt().toString() : null)
                                .build();
        }
}
