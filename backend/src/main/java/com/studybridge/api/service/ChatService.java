package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import reactor.core.Disposable;
import reactor.core.publisher.Mono;

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
        private final ObjectMapper objectMapper;
        private final IntentRouterService intentRouterService;
        private final AiIntegrationService aiIntegrationService;

        // 답변 길이 사실상 무제한 정책: 본문을 자르지 않으며, FastAPI에 큰 상한을 힌트로 전달한다.
        //  서버 안정성 위한 넉넉한 상수(잘림 방지용 상한). 실제 트림은 어디서도 하지 않는다.
        private static final int AI_MAX_RESPONSE_CHARS = 40000;
        private static final int AI_MAX_TOKENS = 8192;

        // SSE keep-alive 하트비트 전용 데몬 스케줄러(공용). 긴 LLM 응답 중 Nginx/브라우저 idle 타임아웃을 방지한다.
        private static final java.util.concurrent.ScheduledExecutorService SSE_HEARTBEAT =
                        java.util.concurrent.Executors.newScheduledThreadPool(2, r -> {
                                Thread t = new Thread(r, "sse-heartbeat");
                                t.setDaemon(true);
                                return t;
                        });

        // emitter에 N초 간격 하트비트(SSE 주석 ':hb')를 건다. 주석이라 프론트 이벤트 핸들러를 건드리지 않는다.
        //  반환된 future를 onCompletion/onTimeout에서 cancel 하여 누수를 막는다.
        private java.util.concurrent.ScheduledFuture<?> startHeartbeat(SseEmitter emitter) {
                long hb = envSeconds("AI_SSE_HEARTBEAT_SECONDS", 12);
                if (hb <= 0) {
                        hb = 12;
                }
                final long interval = hb;
                return SSE_HEARTBEAT.scheduleAtFixedRate(() -> {
                        try {
                                emitter.send(SseEmitter.event().comment("hb"));
                        } catch (Exception e) {
                                // 클라이언트 종료/완료 등으로 전송 실패 — 라이프사이클 콜백의 cancel이 정리한다.
                        }
                }, interval, interval, java.util.concurrent.TimeUnit.SECONDS);
        }

        // FastAPI(/api/ai/multi-chat[/stream]) 요청 바디 구성 — 블로킹/스트리밍 공용.
        private Map<String, Object> buildFastApiRequestBody(AgentChatRoom room, Long roomId, ChatDTO.MultiChatRequest request) {
                // 에이전트 간 상호 피드백을 위해 최근 10개의 AI 답변 가져오기
                List<ChatMessage> lastAiMessages = chatMessageRepository
                                .findTop10ByAgentChatRoomIdAndSenderOrderByCreatedAtDesc(roomId, "AI");
                java.util.Collections.reverse(lastAiMessages);

                List<Map<String, Object>> previousAnswers = lastAiMessages.stream()
                                .map(msg -> {
                                        Map<String, Object> prev = new LinkedHashMap<>();
                                        prev.put("agentName", msg.getAgent() != null ? msg.getAgent().getName() : "AI");
                                        prev.put("answer", msg.getContent());
                                        Map<String, Object> ps = parseProcessSteps(msg.getProcessStepsJson());
                                        if (ps != null) {
                                                prev.put("processSteps", ps);
                                        }
                                        return prev;
                                })
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
                                        // agentPreset은 persona [프리셋: X] 태그에서 복원해 FastAPI 프롬프트로 전달
                                        agentMap.put("agentPreset", extractPersonaTag(persona, "프리셋"));
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

                // ── 학습 진행 모드 결정 ─────────────────────────────────────────────
                //  request에 learningMode가 없으면 방(room)에 저장된 값으로 폴백, 둘 다 없으면 basic.
                //  effectiveLearningMode에 맞춰 FastAPI mode도 debate/socratic으로 강제 보강한다.
                String effectiveLearningMode = normalizeLearningMode(firstNonBlank(
                                request.getLearningMode(),
                                room.getLearningMode(),
                                "basic"));
                String effectiveMode = firstNonBlank(
                                request.getMode(),
                                agentsList.size() > 1 ? "multi_agent_discussion" : "single_answer");
                // learningMode가 명시 모드면 FastAPI mode도 그에 맞춰 강제 보강한다(request.mode 누락 대비).
                if ("debate".equals(effectiveLearningMode)) {
                        effectiveMode = "debate";
                } else if ("socratic".equals(effectiveLearningMode)) {
                        effectiveMode = "socratic";
                } else if ("simulation".equals(effectiveLearningMode)) {
                        effectiveMode = "simulation";
                } else if ("validation".equals(effectiveLearningMode)) {
                        effectiveMode = "validation";
                } else if ("collaboration".equals(effectiveLearningMode)) {
                        effectiveMode = "collaboration";
                }
                log.info("[CHAT MODE] roomId={} requestLearningMode={} roomLearningMode={} effectiveLearningMode={} effectiveMode={}",
                                roomId, request.getLearningMode(), room.getLearningMode(), effectiveLearningMode, effectiveMode);

                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("message", request.getMessage());
                requestBody.put("agentId", request.getAgentId());
                requestBody.put("roomId", request.getRoomId() != null ? request.getRoomId() : roomId);
                requestBody.put("mode", effectiveMode);
                requestBody.put("rounds", request.getRounds() != null ? Math.min(Math.max(request.getRounds(), 1), 3) : 3);
                // 학습 진행 모드 (basic/socratic/debate/simulation) — request 없으면 방 값으로 폴백된 결과
                requestBody.put("learningMode", effectiveLearningMode);
                // 토론 논제/구조 설정 — 프론트 → FastAPI로 유실 없이 패스스루 (없으면 null)
                requestBody.put("debateConfig", request.getDebateConfig());
                // 소크라테스 문답 설정 — 프론트 → FastAPI로 유실 없이 패스스루 (없으면 null)
                requestBody.put("socraticConfig", request.getSocraticConfig());
                // 상황극 설정 — 프론트 → FastAPI로 유실 없이 패스스루 (없으면 null)
                requestBody.put("simulationConfig", request.getSimulationConfig());
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
                // 소크라테스/ RAG 패스스루: userAttempt(시도 답변), materialId(RAG 자료)
                requestBody.put("userAttempt", request.getUserAttempt());
                requestBody.put("materialId", request.getMaterialId());
                requestBody.put("agents", agentsList);
                requestBody.put("previousAnswers", previousAnswers);
                // 특정 에이전트 지칭 전달 (프론트 → Spring → FastAPI)
                if (request.getTargetAgentId() != null && !request.getTargetAgentId().isBlank()) {
                        requestBody.put("targetAgentId", request.getTargetAgentId());
                }
                // 답변 길이 사실상 무제한: FastAPI가 인식하면 사용, 아니면 무시(가산적 패스스루).
                requestBody.put("answerLength", "unlimited");
                requestBody.put("maxResponseChars", AI_MAX_RESPONSE_CHARS);
                requestBody.put("max_tokens", AI_MAX_TOKENS);
                return requestBody;
        }

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

                Map<String, Object> requestBody = buildFastApiRequestBody(room, roomId, request);
                log.info("chat fastapi payload roomId={} payload={}", roomId, requestBody);

                // 모드별 타임아웃: 소크라테스/토론/멀티에이전트는 단계적 검토로 오래 걸리므로 길게 허용한다.
                //  request에 learningMode가 없으면 방 값으로 폴백해 토론/소크라테스 타임아웃을 정확히 적용한다.
                long aiTimeoutSeconds = resolveAiTimeoutSeconds(
                                firstNonBlank(request.getLearningMode(), room.getLearningMode()),
                                request.getMode());
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
                String responseLearningMode = response != null && response.get("learningMode") != null ? response.get("learningMode").toString() : null;
                String finalSynthesis = response != null && response.get("finalSynthesis") != null
                                ? response.get("finalSynthesis").toString()
                                : null;
                // 1차/2차/3차 생성 과정 — FastAPI 응답을 그대로 패스스루 (없으면 null)
                Map<String, Object> processSteps = response != null && response.get("processSteps") instanceof Map
                                ? (Map<String, Object>) response.get("processSteps")
                                : null;
                // 단계별 구조(stages) / 성격 검증 요약 — 유실 없이 패스스루 (없으면 null)
                List<Object> stages = response != null && response.get("stages") instanceof List
                                ? (List<Object>) response.get("stages")
                                : null;
                List<Object> personalityValidationSummary = response != null
                                && response.get("personalityValidationSummary") instanceof List
                                ? (List<Object>) response.get("personalityValidationSummary")
                                : null;
                List<Object> initialAnswers = response != null && response.get("initialAnswers") instanceof List
                                ? (List<Object>) response.get("initialAnswers")
                                : null;
                List<Object> peerFeedbacks = response != null && response.get("peerFeedbacks") instanceof List
                                ? (List<Object>) response.get("peerFeedbacks")
                                : null;
                List<Object> revisedAnswers = response != null && response.get("revisedAnswers") instanceof List
                                ? (List<Object>) response.get("revisedAnswers")
                                : null;
                String debateSummary = response != null && response.get("debateSummary") != null
                                ? response.get("debateSummary").toString()
                                : null;
                // 구조화 토론 단계/설정 — 유실 없이 패스스루 (없으면 null)
                List<Map<String, Object>> debateStages = response != null && response.get("debateStages") instanceof List
                                ? (List<Map<String, Object>>) response.get("debateStages")
                                : null;
                Map<String, Object> debateConfig = response != null && response.get("debateConfig") instanceof Map
                                ? (Map<String, Object>) response.get("debateConfig")
                                : null;
                // 구조화 소크라테스 단계/설정 — 유실 없이 패스스루 (없으면 null)
                List<Map<String, Object>> socraticSteps = response != null && response.get("socraticSteps") instanceof List
                                ? (List<Map<String, Object>>) response.get("socraticSteps")
                                : null;
                Map<String, Object> socraticConfig = response != null && response.get("socraticConfig") instanceof Map
                                ? (Map<String, Object>) response.get("socraticConfig")
                                : null;
                // 구조화 상황극 단계/설정 — 유실 없이 패스스루 (없으면 null)
                List<Map<String, Object>> simulationStages = response != null && response.get("simulationStages") instanceof List
                                ? (List<Map<String, Object>>) response.get("simulationStages")
                                : null;
                Map<String, Object> simulationConfig = response != null && response.get("simulationConfig") instanceof Map
                                ? (Map<String, Object>) response.get("simulationConfig")
                                : null;
                // processSteps를 JSON 문자열로 직렬화해 AI 메시지와 함께 영속화한다 (새로고침 후 복원용).
                String processStepsJson = null;
                if (processSteps != null) {
                        try {
                                processStepsJson = objectMapper.writeValueAsString(processSteps);
                        } catch (Exception e) {
                                log.warn("processSteps 직렬화 실패 (저장 생략): {}", e.getMessage());
                        }
                }

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

                                saveRoomMessage(room, targetAgent, aiContent, "AI", processStepsJson);

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

                                saveRoomMessage(room, targetAgent, aiAnswer, "AI", processStepsJson);

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
                                .learningMode(responseLearningMode)
                                .messages(discussionMessages.isEmpty() ? null : discussionMessages)
                                .finalSynthesis(finalSynthesis)
                                .replies(replies)
                                .initialAnswers(initialAnswers)
                                .peerFeedbacks(peerFeedbacks)
                                .revisedAnswers(revisedAnswers)
                                .debateSummary(debateSummary)
                                .debateStages(debateStages)
                                .debateConfig(debateConfig)
                                .socraticSteps(socraticSteps)
                                .socraticConfig(socraticConfig)
                                .simulationStages(simulationStages)
                                .simulationConfig(simulationConfig)
                                .processSteps(processSteps)
                                .stages(stages)
                                .personalityValidationSummary(personalityValidationSummary)
                                .build();
        }

        // 멀티 에이전트 채팅 — 1차/2차/3차 단계별 SSE 스트리밍.
        //  · basic(기본채팅) 모드: Spring이 1차→2차→3차를 직접 오케스트레이션하여 단계별로 즉시 emit한다.
        //    (원격 FastAPI 스트림은 FIRST_DRAFT만 내려주고 검증/피드백 단계를 생성하지 않으므로 Spring에서 보강)
        //  · debate/socratic/simulation 모드: 원격 FastAPI /api/ai/multi-chat/stream 의 SSE를 그대로 중계한다.
        @Transactional
        public SseEmitter chatStream(Long userId, Long roomId, ChatDTO.MultiChatRequest request) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new RuntimeException("해당 채팅방을 찾을 수 없습니다."));
                if (!room.getUser().getId().equals(userId)) {
                        throw new RuntimeException("해당 채팅방에 접근할 권한이 없습니다.");
                }

                // 사용자 메시지 저장
                transactionTemplate.execute(status -> {
                        saveRoomMessage(room, null, request.getMessage(), "USER");
                        return null;
                });

                // ── Intent Router 게이트 (surface=learning_mate) ─────────────────────────
                // terminal/파이프라인은 AI 스트림을 시작하지 않고 단일 라우팅 이벤트로 종료. WARN은 notice 후 진행.
                IntentDTO.RouteResult route = intentRouterService.route(
                                request.getMessage(), "learning_mate", learningMateContext(roomId, request));
                if (route.isTerminal() || route.isPipeline()) {
                        SseEmitter gate = new SseEmitter(60_000L);
                        handleLearningMateRouted(gate, route, userId, request);
                        return gate;
                }
                final String routeWarning = route.isWarn() ? route.userMessage() : null;

                // FastAPI 요청 바디 (블로킹과 동일 로직 재사용; room.getAgents() lazy 접근은 현재 트랜잭션 내)
                Map<String, Object> requestBody = buildFastApiRequestBody(room, roomId, request);

                String effectiveLearningMode = normalizeLearningMode(firstNonBlank(
                                request.getLearningMode(), room.getLearningMode(), "basic"));

                // buildFastApiRequestBody가 확정한 최종 mode/learningMode/agents 수로 라우팅을 결정한다.
                int agentCount = (requestBody.get("agents") instanceof List)
                                ? ((List<?>) requestBody.get("agents")).size() : 0;
                Object fapiMode = requestBody.get("mode");
                Object fapiLearningMode = requestBody.get("learningMode");

                // basic + 단일 에이전트일 때만 Spring 자체 1차/2차/3차 오케스트레이션을 사용한다.
                // 그 외(다중 에이전트, validation/collaboration/debate/socratic/simulation)는 ai07 stream을 그대로 중계한다.
                boolean useBasicOrchestration = "basic".equals(effectiveLearningMode) && agentCount <= 1;

                log.info("[CHAT ROUTE] roomId={} effectiveLearningMode={} effectiveMode={} agents.size={} fastapiPayload.mode={} fastapiPayload.learningMode={} route={}",
                                roomId, effectiveLearningMode, fapiMode, agentCount, fapiMode, fapiLearningMode,
                                useBasicOrchestration ? "orchestrateBasicStream" : "relayRemoteStream");

                SseEmitter emitter = new SseEmitter(envSeconds("STUDYMATE_SSE_TIMEOUT_SECONDS", 1800) * 1000L);

                // WARN: 경고 notice를 먼저 보내고 기존 학습 답변 스트림을 그대로 이어간다(중복 토큰 append 아님).
                if (routeWarning != null) {
                        safeSend(emitter, "route_notice", Map.of(
                                        "type", "route_notice", "routeAction", "WARN", "message", routeWarning));
                }

                if (useBasicOrchestration) {
                        return orchestrateBasicStream(roomId, request, requestBody, emitter);
                }

                // 그 외 모드는 ai07 /api/ai/multi-chat/stream의 SSE를 그대로 중계한다.
                return relayRemoteStream(roomId, requestBody, request, room, emitter);
        }

        // ── 기본채팅 1차/2차/3차 오케스트레이션 ────────────────────────────────────────
        //  reactor 체인으로 순차 실행하며 .block() 없이 각 단계 완료 시점에 stage_complete 이벤트를 즉시 emit한다.
        //  1차: 빠른 Ollama 초안(짧은 timeout) → 2차: 1차를 검증/보완 → 3차: 1차·2차에 대한 상호 피드백.
        private SseEmitter orchestrateBasicStream(Long roomId, ChatDTO.MultiChatRequest request,
                        Map<String, Object> baseBody, SseEmitter emitter) {
                long stage1Timeout = envSeconds("AI_BASIC_STAGE1_TIMEOUT_SECONDS", 30);
                long stageNTimeout = envSeconds("AI_BASIC_STAGEN_TIMEOUT_SECONDS", 60);

                String question = request.getMessage();
                // 다시 생성 제어: forceRegenerate 또는 attempt>1 이면 cache 우회 + 변형 지시를 프롬프트에 덧붙인다.
                String regenSuffix = buildRegenSuffix(request);

                // 단계 결과 누적 (단일 구독자가 순차 갱신하므로 plain List로 충분)
                List<Map<String, Object>> initialAnswers = new java.util.ArrayList<>();
                List<Map<String, Object>> validatedAnswers = new java.util.ArrayList<>();
                List<Map<String, Object>> peerFeedback = new java.util.ArrayList<>();

                safeSend(emitter, "turn_start",
                                Map.of("type", "turn_start", "message", "AI 응답 생성을 시작합니다."));

                // 단계 사이 LLM 지연이 길어도 연결이 끊기지 않도록 keep-alive 하트비트를 건다.
                final java.util.concurrent.ScheduledFuture<?> heartbeat = startHeartbeat(emitter);

                // 1차(primary): 각 에이전트가 자신의 persona/지식수준으로 질문에 직접 답한다(검증·피드백 금지).
                Mono<List<Map<String, Object>>> chain = fastApiWebClient.post()
                                .uri("/api/ai/multi-chat")
                                .bodyValue(stageBody(baseBody, primaryPrompt(question, regenSuffix), 1))
                                .retrieve()
                                .bodyToMono(Map.class)
                                .timeout(Duration.ofSeconds(stage1Timeout))
                                .map(resp -> extractAnswerRows(resp, 1))
                                .onErrorResume(e -> {
                                        log.warn("기본채팅 1차 생성 실패 roomId={} err={}", roomId, e.toString());
                                        return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                })
                                .flatMap(primaryRows -> {
                                        if (primaryRows.isEmpty()) {
                                                // 30초 내 실패: 전체를 죽이지 않고 fallback 안내를 1차로 내려보낸 뒤 종료한다.
                                                Map<String, Object> fb = new LinkedHashMap<>();
                                                fb.put("agentName", "StudyMate");
                                                fb.put("answer", "1차 답변 생성이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.");
                                                fb.put("agentIndex", 1);
                                                fb.put("displayOrder", 1);
                                                fb.put("stage", 1);
                                                initialAnswers.add(fb);
                                                emitStage(emitter, 1, "primary", "FIRST_DRAFT", "answers", initialAnswers);
                                                return Mono.<List<Map<String, Object>>>empty();
                                        }
                                        initialAnswers.addAll(primaryRows);
                                        emitStage(emitter, 1, "primary", "FIRST_DRAFT", "answers", initialAnswers);

                                        // 1차 답변(들)을 에이전트명과 함께 묶어 2·3차 프롬프트의 검토 대상으로 넣는다.
                                        String primaryContext = labeledAnswers(primaryRows);
                                        // 2차(verification): 1차를 사실성/누락/논리 관점에서 검증·지적 (재답변 금지)
                                        return fastApiWebClient.post()
                                                        .uri("/api/ai/multi-chat")
                                                        .bodyValue(stageBody(baseBody, verifyPrompt(question, primaryContext, regenSuffix), 2))
                                                        .retrieve()
                                                        .bodyToMono(Map.class)
                                                        .timeout(Duration.ofSeconds(stageNTimeout))
                                                        .map(resp -> extractAnswerRows(resp, 2))
                                                        .onErrorResume(e -> {
                                                                log.warn("기본채팅 2차 검증 실패 roomId={} err={}", roomId, e.toString());
                                                                return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                                        })
                                                        .flatMap(verifyRows -> {
                                                                if (!verifyRows.isEmpty()) {
                                                                        validatedAnswers.addAll(verifyRows);
                                                                        emitStage(emitter, 2, "verification", "VALIDATION", "answers", validatedAnswers);
                                                                }
                                                                String verifyContext = labeledAnswers(verifyRows);
                                                                // 3차(feedback): 1차·2차를 참고한 에이전트 간 상호 피드백(동의/반박/추가관점)
                                                                return fastApiWebClient.post()
                                                                                .uri("/api/ai/multi-chat")
                                                                                .bodyValue(stageBody(baseBody,
                                                                                                feedbackPrompt(question, primaryContext, verifyContext, regenSuffix), 3))
                                                                                .retrieve()
                                                                                .bodyToMono(Map.class)
                                                                                .timeout(Duration.ofSeconds(stageNTimeout))
                                                                                .map(resp -> toFeedbackRows(extractAnswerRows(resp, 3)))
                                                                                .onErrorResume(e -> {
                                                                                        log.warn("기본채팅 3차 피드백 실패 roomId={} err={}", roomId, e.toString());
                                                                                        return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                                                                })
                                                                                .doOnNext(fbRows -> {
                                                                                        if (!fbRows.isEmpty()) {
                                                                                                peerFeedback.addAll(fbRows);
                                                                                                emitStage(emitter, 3, "feedback", "PEER_FEEDBACK", "feedbacks", peerFeedback);
                                                                                        }
                                                                                })
                                                                                .map(fbRows -> initialAnswers);
                                                        });
                                });

                Disposable subscription = chain.subscribe(
                                ignored -> { /* 단계별 emit은 위 체인에서 이미 수행됨 */ },
                                err -> {
                                        log.error("기본채팅 오케스트레이션 오류 roomId={} err={}", roomId, err.toString());
                                        finishBasicStream(emitter, roomId, initialAnswers, validatedAnswers, peerFeedback);
                                },
                                () -> finishBasicStream(emitter, roomId, initialAnswers, validatedAnswers, peerFeedback));

                emitter.onCompletion(() -> {
                        heartbeat.cancel(false);
                        subscription.dispose();
                });
                emitter.onTimeout(() -> {
                        heartbeat.cancel(false);
                        subscription.dispose();
                        emitter.complete();
                });
                return emitter;
        }

        // 누적된 1차/2차/3차를 all_complete(processSteps 포함)로 내려보내고 영속화 후 스트림을 종료한다.
        private void finishBasicStream(SseEmitter emitter, Long roomId,
                        List<Map<String, Object>> initialAnswers,
                        List<Map<String, Object>> validatedAnswers,
                        List<Map<String, Object>> peerFeedback) {
                try {
                        Map<String, Object> processSteps = new LinkedHashMap<>();
                        processSteps.put("mode", "basic");
                        processSteps.put("initialAnswers", initialAnswers);
                        processSteps.put("validatedAnswers", validatedAnswers);
                        processSteps.put("peerFeedback", peerFeedback);

                        // 2차는 검증(critique), 3차는 피드백이므로 대표 answer는 직접 답변인 1차를 사용한다.
                        //  (UI는 processSteps로 1·2·3차를 모두 렌더링하며, answers는 영속화/대표 표시용)
                        List<Map<String, Object>> finalAnswers = !initialAnswers.isEmpty() ? initialAnswers
                                        : validatedAnswers;

                        Map<String, Object> allComplete = new LinkedHashMap<>();
                        allComplete.put("type", "all_complete");
                        allComplete.put("mode", "basic");
                        allComplete.put("learningMode", "basic");
                        allComplete.put("answers", finalAnswers);
                        allComplete.put("processSteps", processSteps);
                        allComplete.put("status", "COMPLETED");

                        String json = objectMapper.writeValueAsString(allComplete);
                        try {
                                emitter.send(SseEmitter.event().name("all_complete").data(json));
                        } catch (Exception sendErr) {
                                log.warn("all_complete 전송 실패 roomId={}: {}", roomId, sendErr.getMessage());
                        }
                        persistStreamedAnswers(roomId, json);
                } catch (Exception e) {
                        log.warn("기본채팅 종료 처리 실패 roomId={}: {}", roomId, e.getMessage());
                } finally {
                        emitter.complete();
                }
        }

        // 단계별 FastAPI 요청 바디. phase 지시문(message)만 교체하고 basic/단답(rounds=1)으로 고정.
        //  모든 단계에서 사용자가 고른 전체 에이전트 구성을 유지한다 → 단계마다 에이전트별로 다른 답이 나온다.
        //  (에이전트별 persona/tone/knowledgeLevel은 base의 agents[]에 그대로 실려 FastAPI 프롬프트에 반영됨)
        private Map<String, Object> stageBody(Map<String, Object> base, String message, int stage) {
                Map<String, Object> body = new LinkedHashMap<>(base);
                body.put("message", message);
                body.put("mode", "single_answer");
                body.put("rounds", 1);
                body.put("learningMode", "basic");
                // 단계 입력(1차/2차 답변)은 message에 직접 포함하므로 이전 답변 누적은 비운다.
                body.put("previousAnswers", java.util.Collections.emptyList());
                return body;
        }

        // FastAPI multi-chat 응답의 answers를 stage 말풍선 row로 정규화한다.
        @SuppressWarnings("unchecked")
        private List<Map<String, Object>> extractAnswerRows(Map<?, ?> resp, int stage) {
                List<Map<String, Object>> out = new java.util.ArrayList<>();
                if (resp == null) {
                        return out;
                }
                Object ans = resp.get("answers");
                if (!(ans instanceof List)) {
                        return out;
                }
                int idx = 1;
                for (Object o : (List<Object>) ans) {
                        if (!(o instanceof Map)) {
                                continue;
                        }
                        Map<String, Object> m = (Map<String, Object>) o;
                        Object answerObj = m.get("answer") != null ? m.get("answer") : m.get("content");
                        String answer = answerObj != null ? answerObj.toString() : "";
                        if (answer.isBlank()) {
                                continue;
                        }
                        Object order = m.get("displayOrder") != null ? m.get("displayOrder") : idx;
                        Map<String, Object> row = new LinkedHashMap<>();
                        row.put("agentName", m.get("agentName") != null ? m.get("agentName").toString() : "AI");
                        row.put("answer", answer);
                        row.put("agentId", m.get("agentId"));
                        row.put("agentIndex", order);
                        row.put("displayOrder", order);
                        row.put("stage", stage);
                        out.add(row);
                        idx++;
                }
                return out;
        }

        // 3차 답변 row를 peerFeedback(fromAgent/toAgent/content) 형태로 변환한다.
        private List<Map<String, Object>> toFeedbackRows(List<Map<String, Object>> answers) {
                List<Map<String, Object>> out = new java.util.ArrayList<>();
                int idx = 1;
                for (Map<String, Object> a : answers) {
                        Map<String, Object> fb = new LinkedHashMap<>();
                        fb.put("fromAgent", a.getOrDefault("agentName", "AI"));
                        fb.put("toAgent", "전체");
                        fb.put("content", a.getOrDefault("answer", ""));
                        fb.put("agentIndex", a.getOrDefault("agentIndex", idx));
                        out.add(fb);
                        idx++;
                }
                return out;
        }

        // 단계 답변(들)을 "- 에이전트명: 답변" 형태로 묶어 다음 단계 프롬프트의 검토 대상으로 넣는다.
        private String labeledAnswers(List<Map<String, Object>> rows) {
                if (rows == null || rows.isEmpty()) {
                        return "(없음)";
                }
                return rows.stream()
                                .map(r -> "- " + r.getOrDefault("agentName", "AI") + ": "
                                                + String.valueOf(r.getOrDefault("answer", "")))
                                .filter(s -> s != null && !s.isBlank())
                                .collect(Collectors.joining("\n\n"));
        }

        // 다시 생성/cache 우회용 변형 지시. forceRegenerate 이거나 attempt>1 일 때만 프롬프트에 붙는다.
        //  (원격 cache가 question 기준이어도 프롬프트가 달라져 cache miss + 표현 변형이 유도된다)
        private String buildRegenSuffix(ChatDTO.MultiChatRequest request) {
                int attempt = request.getRegenerateAttempt() != null ? request.getRegenerateAttempt() : 1;
                boolean force = Boolean.TRUE.equals(request.getForceRegenerate());
                if (!force && attempt <= 1) {
                        return "";
                }
                return "\n\n(재생성 요청 #" + attempt
                                + ": 이전 답변과 완전히 다른 설명 방식·예시·구성·문장 구조로 작성하라. 이전과 동일한 문장/예시를 재사용하지 말 것.)";
        }

        // 1차 primary 프롬프트 — 검증/피드백 없이 질문에 직접 답하게 한다(빠른 초안).
        private String primaryPrompt(String question, String regenSuffix) {
                return question
                                + "\n\n[작성 지침] 위 질문에 대해 30초 안에 이해할 수 있는 1차 답변을 직접 작성하라. "
                                + "검증이나 다른 답변에 대한 피드백은 하지 말고, 질문 자체에 대한 답변만 하라."
                                + regenSuffix;
        }

        // 2차 verification 프롬프트 — 1차 답변을 검증·지적한다(재답변 금지).
        private String verifyPrompt(String question, String primaryContext, String regenSuffix) {
                return "너는 검증 담당자다. 아래 사용자 질문과 1차 답변(들)을 검토하라.\n\n"
                                + "[사용자 질문]\n" + question + "\n\n"
                                + "[1차 답변]\n" + primaryContext + "\n\n"
                                + "다음 항목만 수행하라.\n"
                                + "① 사실 오류: 틀린 내용을 구체적으로 지적하고 바로잡는다.\n"
                                + "② 누락된 핵심 개념: 1차 답변이 빠뜨린 중요한 개념을 짚는다.\n"
                                + "③ 논리적 비약/오류: 근거가 약하거나 비약된 부분을 찾는다.\n"
                                + "④ 더 나은 설명 방향: 어떻게 보완하면 좋을지 제시한다.\n\n"
                                + "금지:\n"
                                + "- 1차 답변 문장을 그대로 반복하지 말 것.\n"
                                + "- 같은 비유·예시를 그대로 재사용하지 말 것.\n"
                                + "- 질문에 처음부터 다시 답하는 형태로 쓰지 말 것(검증/지적 형태로만).\n"
                                + "본인 성격과 지식수준에 맞는 어조로 작성하라."
                                + regenSuffix;
        }

        // 3차 feedback 프롬프트 — 1차·2차를 참고한 에이전트 간 상호 피드백(동의/반박/추가관점).
        private String feedbackPrompt(String question, String primaryContext, String verifyContext, String regenSuffix) {
                return "너는 상호 피드백 담당자다. 다른 에이전트들의 답변에 대해 피드백하라.\n\n"
                                + "[사용자 질문]\n" + question + "\n\n"
                                + "[1차 답변]\n" + primaryContext + "\n\n"
                                + "[2차 검증]\n" + (verifyContext == null || verifyContext.isBlank()
                                                ? "(검증 답변 없음)" : verifyContext) + "\n\n"
                                + "다음을 수행하라.\n"
                                + "- 다른 답변 중 동의하는 점과 반박하는 점을 구분해 밝힌다.\n"
                                + "- 아직 부족한 설명을 보완한다.\n"
                                + "- 사용자의 이해를 돕는 새로운 관점이나 예시를 1개 이상 추가한다.\n"
                                + "- 본인 persona(성격/말투)가 분명히 드러나게 작성한다.\n\n"
                                + "금지:\n"
                                + "- 1차 답변 반복 금지.\n"
                                + "- 2차 검증 반복 금지.\n"
                                + "- 단순 요약 금지."
                                + regenSuffix;
        }

        // stage_complete 이벤트를 표준 형태로 emit한다. payloadKey는 answers(1·2차)/feedbacks(3차).
        //  phase(primary/verification/feedback)와 stage(1/2/3)를 함께 실어 프론트가 단계를 구분한다.
        private void emitStage(SseEmitter emitter, int stage, String phase, String stageType, String payloadKey,
                        List<Map<String, Object>> rows) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("type", "stage_complete");
                data.put("phase", phase);
                data.put("stage", stage);
                data.put("stageType", stageType);
                data.put(payloadKey, rows);
                safeSend(emitter, "stage_complete", data);
        }

        private void safeSend(SseEmitter emitter, String event, Map<String, Object> data) {
                try {
                        emitter.send(SseEmitter.event().name(event).data(objectMapper.writeValueAsString(data)));
                } catch (Exception e) {
                        log.warn("SSE 이벤트 전송 실패 event={}: {}", event, e.getMessage());
                }
        }

        // ── Intent Router: 학습메이트 라우팅 ──────────────────────────────────────────
        private Map<String, Object> learningMateContext(Long roomId, ChatDTO.MultiChatRequest request) {
                Map<String, Object> ctx = new LinkedHashMap<>();
                ctx.put("roomId", roomId);
                if (request.getMaterialId() != null) ctx.put("materialId", request.getMaterialId());
                if (request.getLearningMode() != null) ctx.put("mode", request.getLearningMode());
                if (request.getTone() != null) ctx.put("tone", request.getTone());
                if (request.getKnowledgeLevel() != null) ctx.put("learnerLevel", request.getKnowledgeLevel());
                return ctx;
        }

        // terminal/파이프라인을 단일 SSE 이벤트로 처리하고 emitter를 닫는다(기존 AI 스트림 미시작).
        private void handleLearningMateRouted(SseEmitter emitter, IntentDTO.RouteResult route,
                        Long userId, ChatDTO.MultiChatRequest request) {
                try {
                        if (route.isPipeline()) {
                                Long materialId = request.getMaterialId();
                                if (materialId == null) {
                                        safeSend(emitter, "route_message", Map.of("type", "route_message",
                                                        "routeAction", "CLARIFY",
                                                        "message", "어떤 자료를 기준으로 만들까요? 자료를 선택해 주세요."));
                                } else {
                                        Object payload = null;
                                        String msg;
                                        switch (route.getAction()) {
                                                case QUIZ_PIPELINE:
                                                        payload = aiIntegrationService.generateQuiz(userId, materialId,
                                                                        new QuizDTO.Request("보통", 10, "전체"));
                                                        msg = "요청하신 문제를 생성했습니다."; break;
                                                case SUMMARY_PIPELINE:
                                                        payload = aiIntegrationService.getSummary(userId, materialId);
                                                        msg = "자료 요약을 정리했습니다."; break;
                                                case ROADMAP_PIPELINE:
                                                        payload = aiIntegrationService.getRoadmap(userId, materialId);
                                                        msg = "학습 로드맵을 불러왔습니다."; break;
                                                default:
                                                        msg = route.userMessage();
                                        }
                                        Map<String, Object> data = new LinkedHashMap<>();
                                        data.put("type", "route_pipeline");
                                        data.put("routeAction", route.actionName());
                                        data.put("message", msg);
                                        if (payload != null) data.put("pipeline", payload);
                                        safeSend(emitter, "route_pipeline", data);
                                }
                        } else { // terminal: DIRECT_REPLY/BLOCK/CLARIFY
                                safeSend(emitter, "route_message", Map.of("type", "route_message",
                                                "routeAction", route.actionName(), "message", route.userMessage()));
                        }
                        safeSend(emitter, "all_complete", Map.of("type", "all_complete", "routed", true));
                } catch (Exception e) {
                        log.warn("[intent-router] learning_mate routed 처리 실패: {}", e.toString());
                } finally {
                        emitter.complete();
                }
        }

        // 원격 FastAPI /api/ai/multi-chat/stream SSE를 그대로 브라우저로 중계 (토론/소크라테스/상황극).
        private SseEmitter relayRemoteStream(Long roomId, Map<String, Object> requestBody,
                        ChatDTO.MultiChatRequest request, AgentChatRoom room, SseEmitter emitter) {
                // 원격 FastAPI가 첫 이벤트를 늦게 보내거나 이벤트 간 간격이 길어도 연결 유지.
                final java.util.concurrent.ScheduledFuture<?> heartbeat = startHeartbeat(emitter);
                Disposable subscription = fastApiWebClient.post()
                                .uri("/api/ai/multi-chat/stream")
                                .bodyValue(requestBody)
                                .retrieve()
                                .bodyToFlux(new ParameterizedTypeReference<ServerSentEvent<String>>() {})
                                .subscribe(
                                                ev -> {
                                                        try {
                                                                String event = ev.event() != null ? ev.event() : "message";
                                                                String data = ev.data();
                                                                emitter.send(SseEmitter.event().name(event)
                                                                                .data(data != null ? data : "{}"));
                                                                if ("all_complete".equals(event) && data != null) {
                                                                        // 비동기 스레드에서 별도 트랜잭션으로 영속화 (room 재조회로 lazy 회피)
                                                                        persistStreamedAnswers(roomId, data);
                                                                }
                                                        } catch (Exception e) {
                                                                log.warn("SSE 이벤트 전송 실패: {}", e.getMessage());
                                                        }
                                                },
                                                err -> {
                                                        log.error("FastAPI 스트리밍 오류 roomId={} err={}", roomId, err.getMessage());
                                                        try {
                                                                Map<String, Object> fallback = fastApiWebClient.post()
                                                                                .uri("/api/ai/multi-chat")
                                                                                .bodyValue(requestBody)
                                                                                .retrieve()
                                                                                .bodyToMono(Map.class)
                                                                                .block(Duration.ofSeconds(resolveAiTimeoutSeconds(
                                                                                                firstNonBlank(request.getLearningMode(), room.getLearningMode()),
                                                                                                request.getMode())));
                                                                String data = objectMapper.writeValueAsString(fallback != null ? fallback : Map.of());
                                                                emitter.send(SseEmitter.event().name("all_complete").data(data));
                                                                persistStreamedAnswers(roomId, data);
                                                                emitter.complete();
                                                        } catch (Exception fallbackErr) {
                                                                log.error("FastAPI 스트리밍 fallback 오류 roomId={} err={}", roomId, fallbackErr.getMessage());
                                                                try {
                                                                        emitter.send(SseEmitter.event().name("error")
                                                                                        .data("{\"message\":\"AI 스트리밍 중 오류가 발생했습니다.\"}"));
                                                                } catch (Exception ignored) {
                                                                }
                                                                emitter.completeWithError(err);
                                                        }
                                                },
                                                emitter::complete);

                emitter.onCompletion(() -> {
                        heartbeat.cancel(false);
                        subscription.dispose();
                });
                emitter.onTimeout(() -> {
                        heartbeat.cancel(false);
                        subscription.dispose();
                        emitter.complete();
                });
                return emitter;
        }

        // 스트리밍 all_complete 결과(JSON)를 파싱해 AI 메시지 + processStepsJson을 영속화한다.
        private void persistStreamedAnswers(Long roomId, String allCompleteJson) {
                try {
                        Map<String, Object> resp = objectMapper.readValue(
                                        allCompleteJson, new TypeReference<Map<String, Object>>() {});
                        Object psObj = resp.get("processSteps");
                        String processStepsJson = psObj != null ? objectMapper.writeValueAsString(psObj) : null;
                        Object ansObj = resp.get("answers");
                        if (!(ansObj instanceof List)) {
                                return;
                        }
                        @SuppressWarnings("unchecked")
                        List<Map<String, Object>> answers = (List<Map<String, Object>>) ansObj;

                        transactionTemplate.execute(status -> {
                                AgentChatRoom room = agentChatRoomRepository.findById(roomId).orElse(null);
                                if (room == null) {
                                        return null;
                                }
                                for (Map<String, Object> a : answers) {
                                        String agentName = String.valueOf(a.getOrDefault("agentName", "AI"));
                                        Object answerObj = a.get("answer");
                                        String content = answerObj != null ? answerObj.toString() : "";
                                        if (content.isBlank()) {
                                                continue;
                                        }
                                        Agent targetAgent = room.getAgents().stream()
                                                        .filter(ag -> ag.getName().equals(agentName))
                                                        .findFirst()
                                                        .orElse(room.getAgents().isEmpty() ? null : room.getAgents().get(0));
                                        saveRoomMessage(room, targetAgent, content, "AI", processStepsJson);
                                }
                                return null;
                        });
                } catch (Exception e) {
                        log.warn("스트리밍 결과 영속화 실패 roomId={}: {}", roomId, e.getMessage());
                }
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
                                                .processSteps(parseProcessSteps(msg.getProcessStepsJson()))
                                                .build())
                                .collect(Collectors.toList());
        }

        // 영속화된 processSteps JSON을 Map으로 역직렬화한다. 실패/없음이면 null.
        private Map<String, Object> parseProcessSteps(String json) {
                if (json == null || json.isBlank()) {
                        return null;
                }
                try {
                        return objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
                } catch (Exception e) {
                        log.warn("processSteps 역직렬화 실패 (생략): {}", e.getMessage());
                        return null;
                }
        }

        // 채팅 기록 저장 (processSteps 없는 경우)
        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender) {
                saveRoomMessage(room, agent, content, sender, null);
        }

        // 채팅 기록 저장 (AI 메시지는 processStepsJson 함께 영속화)
        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender, String processStepsJson) {
                ChatMessage message = ChatMessage.builder()
                                .agentChatRoom(room)
                                .agent(agent)
                                .content(content)
                                .sender(sender)
                                .processStepsJson(processStepsJson)
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
                agentMap.put("agentPreset", extractPersonaTag(persona, "프리셋"));
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
                if (lm.equals("simulation") || md.contains("simulation")) {
                        return envSeconds("AI_SIMULATION_TIMEOUT_SECONDS", 240);
                }
                if (lm.equals("debate") || md.contains("debate") || md.contains("multi_agent")) {
                        return envSeconds("AI_DEBATE_TIMEOUT_SECONDS", 300);
                }
                return envSeconds("AI_DEFAULT_TIMEOUT_SECONDS", 900);
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

        /**
         * 학습 진행 모드를 basic/validation/collaboration/socratic/debate/simulation 중 하나로 정규화한다.
         * 잘못된 값/null은 basic.
         */
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
                // 검증 모드: 1차 답변 → 검증 → 상호 피드백 (ai07 multi-chat/stream relay)
                if (v.equals("validation") || v.equals("검증") || v.equals("검증 모드")) {
                        return "validation";
                }
                // 협업 모드: 다중 에이전트 협업 (1차 → 검증 → 상호 피드백) relay
                if (v.equals("collaboration") || v.equals("collaborative") || v.equals("협업") || v.equals("협업 모드")) {
                        return "collaboration";
                }
                return "basic";
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
