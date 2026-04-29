package com.studybridge.api.service;

import com.studybridge.api.dto.AgentDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.User;
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
public class AgentService {

    private final AgentRepository agentRepository;
    private final UserRepository userRepository;

    private static final int MAX_AGENT_COUNT = 3;

    @Transactional
    public AgentDTO.Response createAgent(Long userId, AgentDTO.CreateRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new RuntimeException("사용자를 찾을 수 없습니다."));

        if (agentRepository.countByUserId(userId) >= MAX_AGENT_COUNT) {
            throw new RuntimeException("AI 에이전트는 최대 " + MAX_AGENT_COUNT + "개까지만 생성할 수 있습니다.");
        }

        Agent agent = Agent.builder()
                .user(user)
                .name(request.getName())
                .role(request.getRole())
                .persona(request.getPersona())
                .tone(request.getTone() != null ? request.getTone() : "친절하고 전문적인 말투")
                .goal(request.getGoal() != null ? request.getGoal() : "사용자의 학습을 돕는다")
                .build();

        Agent savedAgent = agentRepository.save(agent);
        return convertToResponse(savedAgent);
    }

    public List<AgentDTO.Response> getAgentsByUserId(Long userId) {
        return agentRepository.findByUserId(userId).stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    @Transactional
    public void deleteAgent(Long userId, Long agentId) {
        Agent agent = agentRepository.findById(agentId)
                .orElseThrow(() -> new RuntimeException("해당 AI 에이전트를 찾을 수 없습니다."));

        if (!agent.getUser().getId().equals(userId)) {
            throw new RuntimeException("해당 에이전트를 삭제할 권한이 없습니다.");
        }

        agentRepository.delete(agent);
    }

    private AgentDTO.Response convertToResponse(Agent agent) {
        return AgentDTO.Response.builder()
                .id(agent.getId())
                .name(agent.getName())
                .role(agent.getRole())
                .persona(agent.getPersona())
                .tone(agent.getTone())
                .goal(agent.getGoal())
                .build();
    }
}
