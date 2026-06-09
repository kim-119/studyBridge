package com.studybridge.api.service;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.dto.AgentRoomDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.AgentRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AgentChatRoomService {

        private final AgentChatRoomRepository agentChatRoomRepository;
        private final AgentRepository agentRepository;
        private final UserRepository userRepository;

        // 멀티 에이전트 채팅방 생성
        @Transactional
        public AgentRoomDTO.Response createRoomWithAgents(Long userId, AgentRoomDTO.CreateRequest request) {
                User user = userRepository.findById(userId)
                                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

                if (request.getAgents() != null && request.getAgents().size() > 3) {
                        throw new RuntimeException("에이전트는 최대 3명까지 생성할 수 있습니다.");
                }

                String normalizedLearningMode = normalizeLearningMode(request.getLearningMode());

                AgentChatRoom room = AgentChatRoom.builder()
                                .user(user)
                                .roomName(request.getRoomName())
                                .learningMode(normalizedLearningMode)
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

                // ChatMessage가 Agent를 참조하므로, 메시지를 먼저 지워야 외래 키 제약 조건 위배 방지 가능
                room.getChatMessages().clear();
                agentChatRoomRepository.flush();

                agentChatRoomRepository.delete(room);
        }

        /** 학습 진행 모드를 basic/socratic/debate 중 하나로 정규화한다. 잘못된 값/null은 basic. */
        private String normalizeLearningMode(String learningMode) {
                if (learningMode == null || learningMode.isBlank()) {
                        return "basic";
                }
                String v = learningMode.trim().toLowerCase();
                if (v.equals("socratic")) {
                        return "socratic";
                }
                if (v.equals("debate") || v.equals("discussion")
                                || v.equals("tikitaka") || v.equals("multi_agent_discussion")) {
                        return "debate";
                }
                return "basic";
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
                                // 기존 DB에 learning_mode가 null인 방은 basic으로 간주(마이그레이션 없이 서비스 레벨 폴백).
                                .learningMode(normalizeLearningMode(room.getLearningMode()))
                                .agents(agentResponses)
                                .createdAt(room.getCreatedAt() != null ? room.getCreatedAt().toString() : null)
                                .build();
        }
}
