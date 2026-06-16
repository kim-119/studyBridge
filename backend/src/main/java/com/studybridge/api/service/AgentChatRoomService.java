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

                // 플랜별 방(AI 그룹) 개수 제한 (FREE=3, PREMIUM/ROOT/ADMIN=10).
                int roomLimit = resolveRoomLimit(user);
                if (agentChatRoomRepository.countByUserId(userId) >= roomLimit) {
                        throw new RuntimeException("현재 플랜에서는 학습방을 최대 " + roomLimit + "개까지 생성할 수 있습니다.");
                }

                // 플랜별 에이전트 생성 제한 (FREE=3, PREMIUM/ROOT=10). 하드코딩 3 대신 resolveAgentLimit 사용.
                int agentLimit = resolveAgentLimit(user);
                if (request.getAgents() != null && request.getAgents().size() > agentLimit) {
                        throw new RuntimeException("현재 플랜에서는 에이전트를 최대 " + agentLimit + "명까지 생성할 수 있습니다.");
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
                                                // agentPreset은 Agent 엔티티 컬럼이 없으므로 persona에 [프리셋: X] 태그로 인코딩해
                                                // 마이그레이션 없이 영속/복원한다(기존 [지식수준:]/[성격:] 태그 패턴과 동일).
                                                .persona(withPresetTag(agentReq.getPersona(), agentReq.getAgentPreset()))
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

        /** 학습 진행 모드를 basic/socratic/debate/simulation 중 하나로 정규화한다. 잘못된 값/null은 basic. */
        private String normalizeLearningMode(String learningMode) {
                if (learningMode == null || learningMode.isBlank()) {
                        return "basic";
                }
                String v = learningMode.trim().toLowerCase();
                if (v.equals("socratic") || v.equals("소크라테스") || v.equals("소크라테스 모드")) {
                        return "socratic";
                }
                if (v.equals("simulation") || v.equals("상황극") || v.equals("상황극 모드")
                                || v.equals("시뮬레이션") || v.equals("시뮬레이션 모드")) {
                        return "simulation";
                }
                if (v.equals("debate") || v.equals("토론") || v.equals("토론 모드")) {
                        return "debate";
                }
                return "basic";
        }

        /**
         * 플랜별 에이전트 생성 한도를 결정한다.
         * - FREE(기본): 3명
         * - ADMIN/ROOT(또는 추후 PREMIUM): 10명
         * TODO: 토스 결제 연동 후 User에 plan/agentLimit 필드가 생기면 그 값을 우선 사용한다.
         */
        private int resolveAgentLimit(User user) {
                return isPremiumRole(user) ? 10 : 3;
        }

        /**
         * 플랜별 방(AI 그룹) 생성 한도를 결정한다.
         * - FREE(기본): 3개
         * - ADMIN/ROOT/PREMIUM: 10개
         * 에이전트 한도와 동일한 role 게이트를 사용한다.
         */
        private int resolveRoomLimit(User user) {
                return isPremiumRole(user) ? 10 : 3;
        }

        // ADMIN/ROOT/PREMIUM 여부. 한도 상향 대상 role 판정의 단일 지점.
        private boolean isPremiumRole(User user) {
                if (user != null && user.getRole() != null) {
                        String role = user.getRole().trim().toUpperCase();
                        return role.equals("ADMIN") || role.equals("ROOT") || role.equals("PREMIUM");
                }
                return false;
        }

        // persona 문자열에 [프리셋: X] 태그를 부착(이미 있으면 그대로). agentPreset 영속화용.
        private String withPresetTag(String persona, String agentPreset) {
                String base = persona == null ? "" : persona;
                if (agentPreset == null || agentPreset.isBlank() || base.contains("[프리셋:")) {
                        return base;
                }
                return ("[프리셋: " + agentPreset.trim() + "] " + base).trim();
        }

        private String firstNonBlank(String... values) {
                if (values == null) return null;
                for (String v : values) {
                        if (v != null && !v.isBlank()) return v;
                }
                return null;
        }

        // persona에서 [태그: 값] 추출 (없으면 null).
        private String extractPersonaTag(String persona, String tagName) {
                if (persona == null) return null;
                java.util.regex.Matcher m = java.util.regex.Pattern
                                .compile("\\[" + java.util.regex.Pattern.quote(tagName) + ":\\s*([^\\]]+)\\]")
                                .matcher(persona);
                return m.find() ? m.group(1).trim() : null;
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
                                                // persona 태그에서 프리셋/성격/지식수준 복원(프론트 selectAgent 복원용)
                                                .agentPreset(extractPersonaTag(agent.getPersona(), "프리셋"))
                                                .personality(firstNonBlank(agent.getTone(), extractPersonaTag(agent.getPersona(), "성격")))
                                                .knowledgeLevel(extractPersonaTag(agent.getPersona(), "지식수준"))
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
