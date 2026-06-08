package com.studybridge.api.service;

import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class ChatService {

        private final AgentChatRoomRepository agentChatRoomRepository;
        private final ChatMessageRepository chatMessageRepository;
        private final WebClient fastApiWebClient;
        private final TransactionTemplate transactionTemplate;

        @Transactional
        public ChatDTO.MultiChatResponse chatWithRoom(Long userId, Long roomId, ChatDTO.MultiChatRequest request) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new RuntimeException("해당 채팅방을 찾을 수 없습니다."));

                if (!room.getUser().getId().equals(userId)) {
                        throw new RuntimeException("해당 채팅방에 접근할 권한이 없습니다.");
                }

                // 사용자의 메시지 저장
                transactionTemplate.execute(status -> {
                        saveRoomMessage(room, null, request.getMessage(), "USER");
                        return null;
                });

                // 에이전트 간 상호 피드백을 위해 최근 10개의 AI 답변 가져오기
                List<ChatMessage> lastAiMessages = chatMessageRepository
                                .findTop10ByAgentChatRoomIdAndSenderOrderByCreatedAtDesc(roomId, "AI");
                java.util.Collections.reverse(lastAiMessages);

                List<Map<String, String>> previousAnswers = lastAiMessages.stream()
                                .map(msg -> Map.of(
                                                "agentName", msg.getAgent() != null ? msg.getAgent().getName() : "AI",
                                                "answer", msg.getContent()))
                                .collect(Collectors.toList());

                String requestKnowledgeLevel = firstNonBlank(request.getKnowledgeLevel(), request.getKnowledge_level());
                String requestPersonality = firstNonBlank(request.getPersonality(), request.getStyle(), request.getTone());
                String requestPersonalityStrength = firstNonBlank(
                                request.getPersonalityStrength(),
                                request.getPersonality_strength(),
                                "extreme");
                String requestCustomInstruction = firstNonBlank(
                                request.getCustomInstruction(),
                                request.getCustom_instruction(),
                                stripPersonaTags(request.getPersona()));

                log.info(
                                "chat settings received roomId={} personality={} knowledgeLevel={} customInstructionPresent={}",
                                roomId,
                                requestPersonality,
                                requestKnowledgeLevel,
                                requestCustomInstruction != null && !requestCustomInstruction.isBlank());

                // FastAPI의 /api/ai/multi-chat 요구사항에 맞춰 데이터 구성
                List<Map<String, Object>> agentsList = room.getAgents().stream()
                                .map(agent -> {
                                        String persona = nullToEmpty(agent.getPersona());
                                        String agentKnowledgeLevel = firstNonBlank(
                                                        extractPersonaTag(persona, "지식수준"),
                                                        requestKnowledgeLevel,
                                                        "학사 수준");
                                        String agentPersonality = firstNonBlank(
                                                        agent.getTone(),
                                                        extractPersonaTag(persona, "성격"),
                                                        requestPersonality,
                                                        "전문적");
                                        String agentCustomInstruction = firstNonBlank(
                                                        stripPersonaTags(persona),
                                                        requestCustomInstruction,
                                                        agent.getGoal(),
                                                        "");

                                        Map<String, Object> agentMap = new LinkedHashMap<>();
                                        agentMap.put("id", agent.getId());
                                        agentMap.put("agentId", agent.getId());
                                        agentMap.put("name", agent.getName());
                                        agentMap.put("role", agent.getRole());
                                        agentMap.put("personality", agentPersonality);
                                        agentMap.put("personalityStrength", requestPersonalityStrength);
                                        agentMap.put("personality_strength", requestPersonalityStrength);
                                        agentMap.put("style", agentPersonality);
                                        agentMap.put("tone", agentPersonality);
                                        agentMap.put("knowledgeLevel", agentKnowledgeLevel);
                                        agentMap.put("knowledge_level", agentKnowledgeLevel);
                                        agentMap.put("customInstruction", agentCustomInstruction);
                                        agentMap.put("custom_instruction", agentCustomInstruction);
                                        agentMap.put("persona", persona);
                                        agentMap.put("goal", agent.getGoal());
                                        return agentMap;
                                })
                                .collect(Collectors.toList());

                if (request.getAgents() != null && !request.getAgents().isEmpty()) {
                        agentsList = request.getAgents().stream()
                                        .map(agent -> mapRequestAgent(agent, requestKnowledgeLevel, requestPersonality, requestPersonalityStrength))
                                        .collect(Collectors.toList());
                }

                log.info("[CHAT REQUEST] mode={} message={} agents.size={}",
                                firstNonBlank(request.getMode(), agentsList.size() > 1 ? "multi_agent_discussion" : "single_answer"),
                                request.getMessage(),
                                agentsList.size());
                for (int i = 0; i < agentsList.size(); i++) {
                        Map<String, Object> agent = agentsList.get(i);
                        log.info("[AGENT {}] name={} personality={} knowledgeLevel={}",
                                        i + 1,
                                        agent.get("name"),
                                        agent.get("personality"),
                                        agent.get("knowledgeLevel"));
                }

                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("message", request.getMessage());
                requestBody.put("agentId", request.getAgentId());
                requestBody.put("roomId", request.getRoomId() != null ? request.getRoomId() : roomId);
                requestBody.put("mode", firstNonBlank(
                                request.getMode(),
                                agentsList.size() > 1 ? "multi_agent_discussion" : "single_answer"));
                requestBody.put("rounds", request.getRounds() != null ? Math.min(Math.max(request.getRounds(), 1), 3) : 3);
                // 학습 진행 모드 (basic/socratic/debate) — 미지정 시 FastAPI에서 basic으로 정규화됨
                requestBody.put("learningMode", request.getLearningMode());
                requestBody.put("showFinalSynthesis", request.getShowFinalSynthesis() != null ? request.getShowFinalSynthesis() : false);
                requestBody.put("personality", requestPersonality);
                requestBody.put("personalityStrength", requestPersonalityStrength);
                requestBody.put("personality_strength", requestPersonalityStrength);
                requestBody.put("style", firstNonBlank(request.getStyle(), requestPersonality));
                requestBody.put("tone", firstNonBlank(request.getTone(), requestPersonality));
                requestBody.put("knowledgeLevel", requestKnowledgeLevel);
                requestBody.put("knowledge_level", requestKnowledgeLevel);
                requestBody.put("customInstruction", requestCustomInstruction);
                requestBody.put("custom_instruction", requestCustomInstruction);
                requestBody.put("persona", request.getPersona());
                requestBody.put("agents", agentsList);
                requestBody.put("previousAnswers", previousAnswers);
                // 특정 에이전트 지칭 전달 (프론트 → Spring → FastAPI)
                if (request.getTargetAgentId() != null && !request.getTargetAgentId().isBlank()) {
                        requestBody.put("targetAgentId", request.getTargetAgentId());
                }
                log.info("chat fastapi payload roomId={} payload={}", roomId, requestBody);

                // 모드별 타임아웃: 소크라테스/토론/멀티에이전트는 단계적 검토로 오래 걸리므로 길게 허용한다.
                long aiTimeoutSeconds = resolveAiTimeoutSeconds(request.getLearningMode(), request.getMode());
                long aiTimeoutMillis = aiTimeoutSeconds * 1000L;

                Map<String, Object> response;
                long faStart = System.currentTimeMillis();
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/multi-chat")
                                        .bodyValue(requestBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(aiTimeoutSeconds));
                        log.info("chat fastapi elapsed_ms={} roomId={} timeout_s={}",
                                        System.currentTimeMillis() - faStart, roomId, aiTimeoutSeconds);
                } catch (Exception e) {
                        long elapsed = System.currentTimeMillis() - faStart;
                        // 타임아웃 여부 판단 (block(Duration) 타임아웃은 IllegalStateException으로 올 수 있음)
                        boolean isTimeout = e instanceof WebClientRequestException
                                        || (e.getCause() != null && e.getCause() instanceof java.util.concurrent.TimeoutException)
                                        || elapsed >= (aiTimeoutMillis - 10_000);
                        if (isTimeout) {
                                log.error("chat fastapi TIMEOUT elapsed_ms={} roomId={} timeout_s={}", elapsed, roomId, aiTimeoutSeconds);
                                return ChatDTO.MultiChatResponse.builder()
                                                .success(false)
                                                .errorCode("AI_TIMEOUT")
                                                .errorMessage("AI 답변 생성이 예상보다 오래 걸리고 있습니다. 잠시 후 다시 시도해주세요.")
                                                .replies(java.util.Collections.emptyList())
                                                .build();
                        }
                        log.error("chat fastapi ERROR elapsed_ms={} roomId={} err={} class={}", elapsed, roomId, e.getMessage(), e.getClass().getSimpleName());
                        return ChatDTO.MultiChatResponse.builder()
                                        .success(false)
                                        .errorCode("FASTAPI_ERROR")
                                        .errorMessage("AI 서버와 통신 중 오류가 발생했습니다. FastAPI 서버 상태를 확인해주세요.")
                                        .replies(java.util.Collections.emptyList())
                                        .build();
                }

                List<ChatDTO.AgentReply> replies = new java.util.ArrayList<>();
                List<ChatDTO.DiscussionMessage> discussionMessages = new java.util.ArrayList<>();
                String responseMode = response != null && response.get("mode") != null ? response.get("mode").toString() : null;
                String finalSynthesis = response != null && response.get("finalSynthesis") != null
                                ? response.get("finalSynthesis").toString()
                                : null;
                // 1차/2차/3차 생성 과정 — FastAPI 응답을 그대로 패스스루 (없으면 null)
                Map<String, Object> processSteps = response != null && response.get("processSteps") instanceof Map
                                ? (Map<String, Object>) response.get("processSteps")
                                : null;

                if (response != null && response.containsKey("messages") && response.get("messages") instanceof List) {
                        List<Map<String, Object>> messages = (List<Map<String, Object>>) response.get("messages");

                        for (Map<String, Object> messageMap : messages) {
                                String aiContent = String.valueOf(messageMap.getOrDefault("content", ""));
                                String agentName = String.valueOf(messageMap.getOrDefault("agentName", "AI"));
                                String responseAgentId = String.valueOf(messageMap.getOrDefault("agentId", ""));

                                // IndexOutOfBoundsException 방어: agents가 비어있으면 null 허용
                                Agent targetAgent = room.getAgents().stream()
                                                .filter(a -> String.valueOf(a.getId()).equals(responseAgentId) || a.getName().equals(agentName))
                                                .findFirst()
                                                .orElse(room.getAgents().isEmpty() ? null : room.getAgents().get(0));

                                saveRoomMessage(room, targetAgent, aiContent, "AI");

                                ChatDTO.DiscussionMessage discussionMessage = ChatDTO.DiscussionMessage.builder()
                                                .id(String.valueOf(messageMap.getOrDefault("id", "")))
                                                .round(asInteger(messageMap.get("round")))
                                                .agentId(responseAgentId)
                                                .agentName(agentName)
                                                .role(String.valueOf(messageMap.getOrDefault("role", "")))
                                                .personality(String.valueOf(messageMap.getOrDefault("personality", "")))
                                                .personalityStrength(String.valueOf(messageMap.getOrDefault("personalityStrength", "extreme")))
                                                .knowledgeLevel(String.valueOf(messageMap.getOrDefault("knowledgeLevel", "")))
                                                .speechType(String.valueOf(messageMap.getOrDefault("speechType", "")))
                                                .targetAgentId(messageMap.get("targetAgentId") != null
                                                                ? messageMap.get("targetAgentId").toString()
                                                                : null)
                                                .content(aiContent)
                                                .build();
                                discussionMessages.add(discussionMessage);

                                if (targetAgent != null) {
                                        replies.add(ChatDTO.AgentReply.builder()
                                                        .agentId(targetAgent.getId())
                                                        .agentName(targetAgent.getName())
                                                        .answer(aiContent)
                                                        .build());
                                } else {
                                        replies.add(ChatDTO.AgentReply.builder()
                                                        .agentName(agentName)
                                                        .answer(aiContent)
                                                        .build());
                                }
                        }
                } else if (response != null && response.containsKey("answers")) {
                        List<Map<String, Object>> answers = (List<Map<String, Object>>) response.get("answers");

                        for (int i = 0; i < answers.size(); i++) {
                                Map<String, Object> answerMap = answers.get(i);
                                // NPE 방어: answerMap 값이 null일 수 있음
                                Object answerObj = answerMap.get("answer");
                                Object nameObj = answerMap.get("agentName");
                                String aiAnswer = answerObj != null ? answerObj.toString() : "";
                                String agentName = nameObj != null ? nameObj.toString() : "AI";

                                // IndexOutOfBoundsException 방어
                                final String finalAgentName = agentName;
                                final int finalIdx = i;
                                Agent targetAgent = room.getAgents().stream()
                                                .filter(a -> a.getName().equals(finalAgentName))
                                                .findFirst()
                                                .orElse(room.getAgents().isEmpty() ? null
                                                                : room.getAgents().get(Math.min(finalIdx, room.getAgents().size() - 1)));

                                saveRoomMessage(room, targetAgent, aiAnswer, "AI");

                                if (targetAgent != null) {
                                        replies.add(ChatDTO.AgentReply.builder()
                                                        .agentId(targetAgent.getId())
                                                        .agentName(targetAgent.getName())
                                                        .answer(aiAnswer)
                                                        .build());
                                } else {
                                        replies.add(ChatDTO.AgentReply.builder()
                                                        .agentName(agentName)
                                                        .answer(aiAnswer)
                                                        .build());
                                }
                        }
                }

                return ChatDTO.MultiChatResponse.builder()
                                .mode(responseMode)
                                .messages(discussionMessages.isEmpty() ? null : discussionMessages)
                                .finalSynthesis(finalSynthesis)
                                .replies(replies)
                                .processSteps(processSteps)
                                .build();
        }

        // 채팅방 기록 조회
        public List<ChatDTO.MessageResponse> getRoomChatHistory(Long roomId) {
                return chatMessageRepository.findByAgentChatRoomIdOrderByCreatedAtAsc(roomId).stream()
                                .map(msg -> ChatDTO.MessageResponse.builder()
                                                .id(msg.getId())
                                                .content(msg.getContent())
                                                .sender(msg.getSender())
                                                .senderName(msg.getAgent() != null ? msg.getAgent().getName() : null)
                                                .agentId(msg.getAgent() != null ? msg.getAgent().getId() : null)
                                                .createdAt(msg.getCreatedAt())
                                                .build())
                                .collect(Collectors.toList());
        }

        // 채팅 기록 저장
        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender) {
                ChatMessage message = ChatMessage.builder()
                                .agentChatRoom(room)
                                .agent(agent)
                                .content(content)
                                .sender(sender)
                                .build();
                chatMessageRepository.save(message);
        }

        private Map<String, Object> mapRequestAgent(
                        ChatDTO.RequestAgent agent,
                        String requestKnowledgeLevel,
                        String requestPersonality,
                        String requestPersonalityStrength) {
                String persona = nullToEmpty(agent.getPersona());
                String agentId = firstNonBlank(agent.getAgentId(), agent.getId());
                String agentKnowledgeLevel = firstNonBlank(
                                agent.getKnowledgeLevel(),
                                agent.getKnowledge_level(),
                                requestKnowledgeLevel,
                                "학사 수준");
                String agentPersonality = firstNonBlank(
                                agent.getPersonality(),
                                agent.getStyle(),
                                agent.getTone(),
                                requestPersonality,
                                "전문적");
                String agentPersonalityStrength = firstNonBlank(
                                agent.getPersonalityStrength(),
                                agent.getPersonality_strength(),
                                requestPersonalityStrength,
                                "extreme");
                String agentCustomInstruction = firstNonBlank(
                                stripPersonaTags(agent.getCustomInstruction()),
                                stripPersonaTags(agent.getCustom_instruction()),
                                stripPersonaTags(persona),
                                "");

                Map<String, Object> agentMap = new LinkedHashMap<>();
                agentMap.put("id", agentId);
                agentMap.put("agentId", agentId);
                agentMap.put("name", firstNonBlank(agent.getName(), "AI 학습 도우미"));
                agentMap.put("role", firstNonBlank(agent.getRole(), "AI 학습 도우미"));
                agentMap.put("personality", agentPersonality);
                agentMap.put("personalityStrength", agentPersonalityStrength);
                agentMap.put("personality_strength", agentPersonalityStrength);
                agentMap.put("style", agentPersonality);
                agentMap.put("tone", agentPersonality);
                agentMap.put("knowledgeLevel", agentKnowledgeLevel);
                agentMap.put("knowledge_level", agentKnowledgeLevel);
                agentMap.put("customInstruction", agentCustomInstruction);
                agentMap.put("custom_instruction", agentCustomInstruction);
                agentMap.put("persona", persona);
                return agentMap;
        }

        /**
         * 모드별 FastAPI 응답 대기 시간(초)을 결정한다.
         * 소크라테스/토론/멀티에이전트는 단계적 검토·상호 피드백으로 오래 걸리므로 길게 허용한다.
         * 값은 환경변수로 조정 가능하며, 미설정 시 안전 기본값을 쓴다.
         */
        private long resolveAiTimeoutSeconds(String learningMode, String mode) {
                String lm = learningMode == null ? "" : learningMode.trim().toLowerCase();
                String md = mode == null ? "" : mode.trim().toLowerCase();
                if (lm.equals("socratic") || md.contains("socratic")) {
                        return envSeconds("AI_SOCRATIC_TIMEOUT_SECONDS", 240);
                }
                if (lm.equals("debate") || md.contains("debate") || md.contains("multi_agent")) {
                        return envSeconds("AI_DEBATE_TIMEOUT_SECONDS", 300);
                }
                return envSeconds("AI_DEFAULT_TIMEOUT_SECONDS", 90);
        }

        private long envSeconds(String key, long defaultValue) {
                try {
                        String v = System.getenv(key);
                        if (v != null && !v.isBlank()) {
                                long parsed = Long.parseLong(v.trim());
                                if (parsed > 0) {
                                        return parsed;
                                }
                        }
                } catch (NumberFormatException ignored) {
                        // 잘못된 값이면 기본값 사용
                }
                return defaultValue;
        }

        private String firstNonBlank(String... values) {
                if (values == null) {
                        return null;
                }
                for (String value : values) {
                        if (value != null && !value.isBlank()) {
                                return value.trim();
                        }
                }
                return null;
        }

        private String nullToEmpty(String value) {
                return value == null ? "" : value;
        }

        private String extractPersonaTag(String persona, String tagName) {
                if (persona == null || persona.isBlank()) {
                        return null;
                }
                Pattern pattern = Pattern.compile("\\[" + Pattern.quote(tagName) + ":\\s*([^\\]]+)\\]");
                Matcher matcher = pattern.matcher(persona);
                return matcher.find() ? matcher.group(1).trim() : null;
        }

        private String stripPersonaTags(String persona) {
                if (persona == null || persona.isBlank()) {
                        return "";
                }
                return persona.replaceAll("\\[[^\\]]+\\]", "").trim();
        }

        private Integer asInteger(Object value) {
                if (value instanceof Integer) {
                        return (Integer) value;
                }
                if (value instanceof Number) {
                        return ((Number) value).intValue();
                }
                if (value != null) {
                        try {
                                return Integer.parseInt(value.toString());
                        } catch (NumberFormatException ignored) {
                                return null;
                        }
                }
                return null;
        }
}
