package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.AgentProfileContract;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.exception.AiUpstreamException;
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
import reactor.core.Disposable;
import reactor.core.publisher.Flux;
import reactor.core.publisher.FluxSink;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

import java.time.Duration;
import java.util.HashMap;
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
        private final RedisChatService redisChatService;
        private final AiMultiChatFailoverService aiFailover;

        // 답변 길이 사실상 무제한 정책: 본문을 자르지 않으며, FastAPI에 큰 상한을 힌트로 전달한다.
        //  서버 안정성 위한 넉넉한 상수(잘림 방지용 상한). 실제 트림은 어디서도 하지 않는다.
        private static final int AI_MAX_RESPONSE_CHARS = 40000;
        private static final int AI_MAX_TOKENS = 8192;

        // ── SSE 출력 어댑터 ──────────────────────────────────────────────────────────
        //  서블릿 emitter 대신 Flux sink 로 이벤트를 내보낸다(리액티브 체인을 컨트롤러까지 유지, 서비스 내 fire-and-forget 없음).
        @FunctionalInterface
        private interface SseOut {
                void send(String event, String json);
        }

        private static ServerSentEvent<String> sse(String event, String json) {
                return ServerSentEvent.<String>builder(json != null ? json : "{}").event(event).build();
        }

        private String toJson(Map<String, Object> data) {
                try {
                        return objectMapper.writeValueAsString(data);
                } catch (Exception e) {
                        return "{}";
                }
        }

        // 브라우저 keep-alive: SSE 주석(':hb')을 N초 간격으로 병합한다. 주석이라 프론트 이벤트 핸들러를 건드리지 않는다.
        //  본 스트림이 끝나면 sentinel 로 interval 을 함께 정리한다(누수 없음).
        //  · 첫 business 이벤트가 나간 뒤에만 tick 을 시작한다 → 스트림을 열기 전(pre-stream) 실패는 응답이 커밋되기 전이라
        //    AiUpstreamException 으로 상태코드+JSON 응답이 가능하다(정상 SSE 위장 금지, §10).
        //  · tick 은 control event 라 backpressure 시 drop 해도 된다(business event 는 절대 drop 하지 않는다, §18).
        static Flux<ServerSentEvent<String>> withHeartbeat(Flux<ServerSentEvent<String>> main, long hbSeconds) {
                final long hb = hbSeconds <= 0 ? 12 : hbSeconds;
                final ServerSentEvent<String> end = ServerSentEvent.<String>builder().comment("end").build();
                return main.switchOnFirst((signal, flux) -> {
                        if (!signal.hasValue()) {
                                return flux; // 값 없이 error/complete → 그대로 전파(heartbeat 없음)
                        }
                        Flux<ServerSentEvent<String>> ticks = Flux.interval(Duration.ofSeconds(hb), Duration.ofSeconds(hb))
                                        .onBackpressureDrop()
                                        .map(i -> ServerSentEvent.<String>builder().comment("hb").build());
                        return Flux.merge(flux.concatWith(Mono.just(end)), ticks)
                                        .takeUntil(ev -> ev == end)
                                        .filter(ev -> ev != end);
                });
        }

        private Flux<ServerSentEvent<String>> withHeartbeat(Flux<ServerSentEvent<String>> main) {
                return withHeartbeat(main, envSeconds("AI_SSE_HEARTBEAT_SECONDS", 12));
        }

        // ── 요청 상관 id: 브라우저 X-Request-ID → (없으면) 프론트 messageId → (없으면) Spring 발급 ─────────────
        //  허용 형식 [A-Za-z0-9._:-]{4,64}. 같은 값이 Spring 로그·AI07 요청(X-Request-ID 헤더 + body.requestId)·모든 SSE 이벤트에 실린다.
        private static final Pattern REQUEST_ID_PATTERN = Pattern.compile("^[A-Za-z0-9._:-]{4,64}$");

        public static String resolveRequestId(String... candidates) {
                if (candidates != null) {
                        for (String c : candidates) {
                                if (c != null && REQUEST_ID_PATTERN.matcher(c.trim()).matches()) {
                                        return c.trim();
                                }
                        }
                }
                return "req_" + java.util.UUID.randomUUID().toString().replace("-", "").substring(0, 12);
        }

        // FastAPI(/api/ai/multi-chat[/stream]) 요청 바디 구성 — 블로킹/스트리밍 공용.
        private Map<String, Object> buildFastApiRequestBody(AgentChatRoom room, Long roomId, ChatDTO.MultiChatRequest request) {
                return buildFastApiRequestBody(room, roomId, request, null, null);
        }

        private Map<String, Object> buildFastApiRequestBody(AgentChatRoom room, Long roomId, ChatDTO.MultiChatRequest request,
                        Long userId, String requestId) {
                // Redis에서 최근 대화 가져오기
                List<com.studybridge.api.dto.RedisChatMessage> recentHistory = redisChatService.getRecentPersonalHistory(roomId);
                
                List<Map<String, Object>> previousAnswers;
                if (recentHistory == null || recentHistory.isEmpty()) {
                        // Redis가 비어있다면 DB에서 가져와서 Redis에 적재(Cache Hydration)
                        List<ChatMessage> lastAiMessages = chatMessageRepository
                                        .findTop10ByAgentChatRoomIdAndSenderOrderByCreatedAtDesc(roomId, "AI");
                        java.util.Collections.reverse(lastAiMessages);
                        
                        previousAnswers = lastAiMessages.stream()
                                        .map(msg -> {
                                                Map<String, Object> prev = new LinkedHashMap<>();
                                                prev.put("agentName", msg.getAgent() != null ? msg.getAgent().getName() : "AI");
                                                prev.put("answer", msg.getContent());
                                                Map<String, Object> ps = parseProcessSteps(msg.getProcessStepsJson());
                                                if (ps != null) {
                                                        prev.put("processSteps", ps);
                                                }
                                                // Redis에도 저장 (다음 조회 시 빠른 처리를 위함)
                                                redisChatService.savePersonalMessage(roomId, com.studybridge.api.dto.RedisChatMessage.builder()
                                                        .agentName(msg.getAgent() != null ? msg.getAgent().getName() : "AI")
                                                        .answer(msg.getContent())
                                                        .role("ASSISTANT")
                                                        .agentId(msg.getAgent() != null ? msg.getAgent().getId() : null)
                                                        .build());
                                                return prev;
                                        })
                                        .collect(Collectors.toList());
                } else {
                        // Redis에서 바로 변환
                        previousAnswers = recentHistory.stream()
                                        .map(h -> {
                                                Map<String, Object> map = new LinkedHashMap<>();
                                                map.put("agentName", h.getAgentName());
                                                map.put("answer", h.getAnswer());
                                                map.put("role", h.getRole());
                                                if (h.getAgentId() != null) {
                                                        map.put("agentId", h.getAgentId());
                                                }
                                                return map;
                                        })
                                        .collect(Collectors.toList());
                }

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

                // FastAPI의 /api/ai/multi-chat 요구사항에 맞춰 데이터 구성 — canonical contract(AgentProfileContract) 단일 지점.
                //  agentSlot = 방 에이전트 배열의 1-based 위치(순서 identity). identity 는 agentId, 표시는 name.
                final List<Agent> roomAgents = room.getAgents();
                List<Map<String, Object>> agentsList = new java.util.ArrayList<>();
                for (int i = 0; i < roomAgents.size(); i++) {
                        agentsList.add(buildAgentPayload(roomAgents.get(i), i + 1, requestKnowledgeLevel, requestPersonality,
                                        requestPersonalityStrength, requestCustomInstruction, request.getTemperature()));
                }

                // 방 에이전트가 유일한 Source of Truth. 과거엔 요청 body 의 agents[] 가 있으면 방 구성을 통째로 대체했는데,
                //  (1) 클라이언트가 임의 이름/persona 의 가짜 교수를 주입할 수 있고 (2) 그 답변은 방 agent 와 매칭되지 않아
                //  agent=null 행으로 영속돼 새로고침 후 작성자 없는 답변이 남았다(감사 재현: agentId=999 "가짜교수").
                //  학습메이트 프론트는 이 필드를 보내지 않으므로(그룹스터디 봇은 별도 컨트롤러) 무시하고 로그만 남긴다.
                if (request.getAgents() != null && !request.getAgents().isEmpty()) {
                        log.warn("[CHAT REQUEST] roomId={} 요청 body 의 agents[]({}명)는 무시한다 — 방 에이전트({}명)만 사용",
                                        roomId, request.getAgents().size(), agentsList.size());
                }

                // previousAnswers: Redis 캐시 전량(최대 100건, USER 포함)이 매 턴 그대로 ai07 로 나가고(방 201 실측 77KB),
                //  직전에 저장한 "이번 질문" USER 항목까지 이전 대화로 실려 갔다 → 최근 N건으로 자르고 이번 질문 echo 는 제외한다.
                previousAnswers = trimPreviousAnswers(previousAnswers, request.getMessage(),
                                (int) envSeconds("AI_PREVIOUS_ANSWERS_MAX", 20));

                log.info("[CHAT REQUEST] mode={} messageLength={} agents.size={} previousAnswers={}",
                                firstNonBlank(request.getMode(), agentsList.size() > 1 ? "multi_agent_discussion" : "single_answer"),
                                request.getMessage() != null ? request.getMessage().length() : 0,
                                agentsList.size(), previousAnswers.size());
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
                // 기본 질문 모드 단계 정책 — 1차에 그치지 않고 2차 심화/3차 상호 피드백/환각 검증까지 진행하도록
                // 플래그를 전달한다(개별 단계 생성 여부는 FastAPI/ai07가 결정, 미인식 시 무시되는 가산적 패스스루).
                if ("basic".equals(effectiveLearningMode)) {
                        requestBody.put("stagePolicy", firstNonBlank(request.getStagePolicy(), "full"));
                        requestBody.put("enableDeepening", request.getEnableDeepening() != null ? request.getEnableDeepening() : Boolean.TRUE);
                        requestBody.put("enablePeerFeedback", request.getEnablePeerFeedback() != null ? request.getEnablePeerFeedback() : Boolean.TRUE);
                        requestBody.put("enableHallucinationValidation",
                                        request.getEnableHallucinationValidation() != null ? request.getEnableHallucinationValidation() : Boolean.TRUE);
                }
                // ── 모드별 설정(단일 지점): 요청 값 > 방 저장값(mode_config_json) > 기본값 ─────────────
                //  · 현재 모드의 설정만 실어 보낸다 → 이전 모드 설정이 payload 에 남지 않는다.
                //  · enum 문자열은 LearningModeContract 가 ai07 canonical 값으로 정규화한다.
                //  · stream/non-stream(fallback) 모두 이 body 를 그대로 쓴다(AiMultiChatFailoverService 는 body 를 재구성하지 않음).
                Map<String, Object> roomModeCfg = parseRoomModeConfig(room);
                if ("debate".equals(effectiveLearningMode)) {
                        Map<String, Object> debateCfg = LearningModeContract.buildDebateConfig(
                                        request.getDebateStrength(), request.getDebateConfig(), subMap(roomModeCfg, "debateConfig"));
                        requestBody.put("debateConfig", debateCfg);
                        // 토론 강도는 top-level 로도 전달(ai07 resolve_strength 1순위). 논제 = message 자체(별도 topic 필드 없음).
                        requestBody.put("debateStrength", debateCfg.get("debateStrength"));
                } else if ("socratic".equals(effectiveLearningMode)) {
                        requestBody.put("socraticConfig", LearningModeContract.buildSocraticConfig(
                                        request.getSocraticConfig(), subMap(roomModeCfg, "socraticConfig")));
                } else if ("simulation".equals(effectiveLearningMode)) {
                        requestBody.put("simulationConfig", LearningModeContract.buildSimulationConfig(
                                        request.getSimulationConfig(), subMap(roomModeCfg, "simulationConfig")));
                }
                requestBody.put("showFinalSynthesis", request.getShowFinalSynthesis() != null ? request.getShowFinalSynthesis() : false);
                // 상관 id(브라우저 X-Request-ID ↔ Spring ↔ AI07) + JWT 사용자 id(본문 userId 는 신뢰하지 않는다).
                if (requestId != null) {
                        requestBody.put("requestId", requestId);
                }
                if (userId != null) {
                        requestBody.put("userId", userId);
                }
                requestBody.put("contractVersion", AiMultiChatFailoverService.CONTRACT_VERSION);
                requestBody.put("personality", requestPersonality);
                // 정규 성격 key + temperature(요청 personalityStyle 우선, 없으면 personality에서 유도). canonical 6키도 함께 전달.
                AgentProfileContract.PersonaResolution reqPersona = AgentProfileContract.resolvePersona(
                                request.getPersonalityStyle(), requestPersonality);
                String requestPersonalityKey = reqPersona.legacyStyle() != null ? reqPersona.legacyStyle()
                                : firstNonBlank(request.getPersonalityStyle(), personalityStyleKey(requestPersonality));
                requestBody.put("personalityStyle", requestPersonalityKey);
                requestBody.put("personalityKey", reqPersona.key());
                requestBody.put("temperature", AgentProfileContract.temperatureFor(reqPersona, request.getTemperature()));
                requestBody.put("personalityStrength", requestPersonalityStrength);
                requestBody.put("personality_strength", requestPersonalityStrength);
                requestBody.put("style", firstNonBlank(request.getStyle(), requestPersonality));
                requestBody.put("tone", firstNonBlank(request.getTone(), requestPersonality));
                String normalizedRequestLevel = normalizeKnowledgeLevel(requestKnowledgeLevel);
                requestBody.put("knowledgeLevel", normalizedRequestLevel);
                requestBody.put("knowledge_level", normalizedRequestLevel);
                requestBody.put("knowledgeLevelLabel", knowledgeLevelLabel(normalizedRequestLevel));
                requestBody.put("knowledgeLevelKey", AgentProfileContract.resolveKnowledge(requestKnowledgeLevel).key());
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
                // "이 교수에게 질문"(single target) 정합 필드 — 값이 있을 때만 ai07로 패스스루.
                //  ai07는 targetAgentId만으로도 1명 필터가 되지만, 이름 기반 멘션 등 agentId가 불안정한
                //  경우를 위해 scope/role/index/name을 함께 실어 보낸다(미지원 필드는 ai07에서 무시됨).
                if (request.getAskScope() != null && !request.getAskScope().isBlank()) {
                        requestBody.put("askScope", request.getAskScope());
                }
                if (request.getTargetProfessorRole() != null && !request.getTargetProfessorRole().isBlank()) {
                        requestBody.put("targetProfessorRole", request.getTargetProfessorRole());
                }
                if (request.getTargetAgentIndex() != null) {
                        requestBody.put("targetAgentIndex", request.getTargetAgentIndex());
                }
                if (request.getTargetAgentKey() != null && !request.getTargetAgentKey().isBlank()) {
                        requestBody.put("targetAgentKey", request.getTargetAgentKey());
                }
                if (request.getTargetAgentName() != null && !request.getTargetAgentName().isBlank()) {
                        requestBody.put("targetAgentName", request.getTargetAgentName());
                }
                if (request.getProfessorSelectedTarget() != null && !request.getProfessorSelectedTarget().isBlank()) {
                        requestBody.put("professorSelectedTarget", request.getProfessorSelectedTarget());
                }
                if (request.getSelectedProfessorRole() != null && !request.getSelectedProfessorRole().isBlank()) {
                        requestBody.put("selectedProfessorRole", request.getSelectedProfessorRole());
                }
                // ── 멀티턴 대화 상태 echo 패스스루(토론 논제/상황극 선택 진행 유지) ──
                //  값이 있을 때만 실어 보낸다. 없으면(기본/첫 턴) 추가하지 않아 기존 동작과 동일하다.
                //  이 echo가 빠지면 ai07가 매 턴 TOPIC_SELECTION/선택지 제시로 되돌아가 같은 논제·선택지를 반복한다.
                if (request.getSelectedTopic() != null && !request.getSelectedTopic().isBlank()) {
                        requestBody.put("selectedTopic", request.getSelectedTopic());
                }
                if (request.getDebateState() != null) {
                        requestBody.put("debateState", request.getDebateState());
                }
                if (request.getDebateSessionId() != null && !request.getDebateSessionId().isBlank()) {
                        requestBody.put("debateSessionId", request.getDebateSessionId());
                }
                if (request.getSimulationState() != null) {
                        requestBody.put("simulationState", request.getSimulationState());
                }
                if (request.getScenarioId() != null && !request.getScenarioId().isBlank()) {
                        requestBody.put("scenarioId", request.getScenarioId());
                }
                Map<String, Object> selectedChoice = LearningModeContract.normalizeSelectedChoice(request.getSelectedChoice());
                if (selectedChoice != null) {
                        requestBody.put("selectedChoice", selectedChoice); // ai07 계약: 객체({choiceId,label})
                }
                if (request.getPreviousChoices() != null && !request.getPreviousChoices().isEmpty()) {
                        requestBody.put("previousChoices", request.getPreviousChoices());
                }
                if (request.getTurnIndex() != null) {
                        requestBody.put("turnIndex", request.getTurnIndex());
                }
                // ── 세션 유지(소크라테스/상황극): 같은 sessionId + 상태 echo → 짧은 답변("응", "덮어써져")이 새 세션으로 가지 않는다 ──
                //  ai07 resolve_session_id: 명시 sessionId > *State.sessionId > room-{roomId}:{mode}.
                if (request.getSessionId() != null && !request.getSessionId().isBlank()) {
                        requestBody.put("sessionId", request.getSessionId());
                }
                if (request.getSocraticState() != null && !request.getSocraticState().isEmpty()) {
                        requestBody.put("socraticState", request.getSocraticState());
                }
                if (request.getTopicSelected() != null) {
                        requestBody.put("topicSelected", request.getTopicSelected());
                }
                // 답변 길이 사실상 무제한: FastAPI가 인식하면 사용, 아니면 무시(가산적 패스스루).
                requestBody.put("answerLength", "unlimited");
                requestBody.put("maxResponseChars", AI_MAX_RESPONSE_CHARS);
                requestBody.put("max_tokens", AI_MAX_TOKENS);

                // ── [payload 검증] personality/mode/level/temperature가 FastAPI까지 실제로 실리는지 로그로 확인 ──
                //  (운영 과다 로깅 방지를 위해 요약만 남긴다. 에이전트별 정규화 결과를 한 줄로 정리.)
                if (log.isInfoEnabled()) {
                        StringBuilder agentSummary = new StringBuilder();
                        for (Map<String, Object> a : agentsList) {
                                if (agentSummary.length() > 0) agentSummary.append(" | ");
                                agentSummary.append(a.get("name")).append("#").append(a.get("agentSlot")).append(":")
                                        .append(a.get("personalityKey")).append("(").append(a.get("personalityStyle")).append(")/")
                                        .append(a.get("knowledgeLevelKey")).append("/t=")
                                        .append(a.get("temperature"));
                        }
                        log.info("[CHAT PAYLOAD] roomId={} mode={} learningMode={} reqPersonality={} reqLevel={} reqTemp={} strength={} agents=[{}]",
                                roomId, requestBody.get("mode"), requestBody.get("learningMode"),
                                requestBody.get("personalityStyle"), normalizedRequestLevel,
                                requestBody.get("temperature"), requestPersonalityStrength, agentSummary);
                }
                return requestBody;
        }

        @Transactional
        public ChatDTO.MultiChatResponse chatWithRoom(Long userId, Long roomId, ChatDTO.MultiChatRequest request) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new java.util.NoSuchElementException("해당 채팅방을 찾을 수 없습니다."));

                if (!room.getUser().getId().equals(userId)) {
                        throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
                }

                // STRICT TARGETING: targetAgentId 는 방 agent 의 stable id(PK) 로만 해석한다.
                //  방에 없는 id 는 첫 번째 교수로 폴백하지 않고 400 으로 거절한다(null/blank = 기존 전체 협업 모드).
                Agent explicitTarget = resolveExplicitTargetAgent(room.getAgents(), request.getTargetAgentId());
                log.info("[TARGET-AGENT] roomId={} mode=sync targetAgentId={} resolved={} scope={}",
                                roomId, request.getTargetAgentId(),
                                explicitTarget != null ? explicitTarget.getId() + ":" + explicitTarget.getName() : null,
                                explicitTarget != null ? "single" : "all");

                final String syncRequestId = resolveRequestId(request.getMessageId());
                // 사용자의 메시지 저장(requestId 를 함께 남겨 늦게 영속되는 AI 답변과 같은 턴으로 묶인다)
                transactionTemplate.execute(status -> {
                        saveRoomMessage(room, null, request.getMessage(), "USER", null,
                                        new AnswerMeta(syncRequestId, null, null, null, null, null, null, null, null));
                        return null;
                });

                Map<String, Object> requestBody = buildFastApiRequestBody(room, roomId, request, userId, syncRequestId);
                log.info("chat fastapi payload roomId={} requestId={} keys={} agents={}", roomId, syncRequestId, requestBody.keySet(),
                                requestBody.get("agents") instanceof List ? ((List<?>) requestBody.get("agents")).size() : 0);

                // 모드별 타임아웃: 소크라테스/토론/멀티에이전트는 단계적 검토로 오래 걸리므로 길게 허용한다.
                //  request에 learningMode가 없으면 방 값으로 폴백해 토론/소크라테스 타임아웃을 정확히 적용한다.
                long aiTimeoutSeconds = resolveAiTimeoutSeconds(
                                firstNonBlank(request.getLearningMode(), room.getLearningMode()),
                                request.getMode());
                long aiTimeoutMillis = aiTimeoutSeconds * 1000L;

                Map<String, Object> response;
                long faStart = System.currentTimeMillis();
                try {
                        // PRIMARY→SECONDARY failover 포함 non-stream 호출. 여기는 MVC(Tomcat) 요청 스레드라 block 허용.
                        response = aiFailover.callMultiChat(roomId, syncRequestId,
                                        requestBody, Duration.ofSeconds(aiTimeoutSeconds))
                                        .block(Duration.ofSeconds(aiTimeoutSeconds * 2 + 5));
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
                //  모드 전용 응답(processSteps 없음)은 구조화 payload(debateStages/socraticSteps/simulationStages …)를 대신 저장한다.
                String processStepsJson = null;
                if (processSteps == null) {
                        processSteps = structuredProcessSteps(response);
                }
                if (processSteps != null) {
                        try {
                                processStepsJson = objectMapper.writeValueAsString(processSteps);
                        } catch (Exception e) {
                                log.warn("processSteps 직렬화 실패 (저장 생략): {}", e.getMessage());
                        }
                }

                if (response != null && response.containsKey("messages") && response.get("messages") instanceof List) {
                        List<Map<String, Object>> messages = (List<Map<String, Object>>) response.get("messages");

                        final String respTurnId = response.get("turnId") != null ? String.valueOf(response.get("turnId")) : null;
                        final String respMode = responseLearningMode != null ? responseLearningMode : responseMode;
                        int msgIndex = 0;
                        for (Map<String, Object> messageMap : messages) {
                                int idx = msgIndex++;
                                String aiContent = String.valueOf(messageMap.getOrDefault("content", ""));
                                String agentName = String.valueOf(messageMap.getOrDefault("agentName", "AI"));
                                String responseAgentId = String.valueOf(messageMap.getOrDefault("agentId", ""));

                                // 응답 identity 보존: agentId → 이름 → null. 첫 번째 교수로 폴백하지 않는다.
                                Agent targetAgent = resolveResponseAgent(room.getAgents(), responseAgentId, agentName);

                                // stream 과 같은 규칙으로 영속화: 실패/빈 답변 제외, 멱등 키(turnId:agentId:round:sequence) 로 중복 저장 방지.
                                if (!aiContent.isBlank() && !AgentProfileContract.isFailedAnswer(messageMap)) {
                                        Map<String, Object> keyed = new LinkedHashMap<>(messageMap);
                                        keyed.putIfAbsent("stage", messageMap.get("round"));
                                        keyed.putIfAbsent("displayOrder", messageMap.get("sequence"));
                                        String dedupKey = dedupKeyOf(keyed, respTurnId, syncRequestId, idx);
                                        Map<String, Object> identity = AgentProfileContract.identityOf(messageMap);
                                        AnswerMeta meta = new AnswerMeta(syncRequestId, respTurnId, dedupKey, (Integer) identity.get("agentIndex"),
                                                        str(messageMap.get("round")), str(identity.get("status")), respMode,
                                                        str(identity.get("personalityKey")), str(identity.get("knowledgeLevelKey")));
                                        if (dedupKey == null || !chatMessageRepository.existsByAgentChatRoomIdAndEventId(roomId, dedupKey)) {
                                                saveRoomMessage(room, targetAgent, aiContent, "AI", processStepsJson, meta);
                                        } else {
                                                log.info("[CHAT PERSIST] roomId={} requestId={} non-stream 중복 답변 건너뜀 key={}", roomId, syncRequestId, dedupKey);
                                        }
                                }

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
                                        replies.add(buildReplyWithMeta(targetAgent.getId(), targetAgent.getName(), aiContent,
                                                        messageMap, extractPersonaTag(targetAgent.getPersona(), "지식수준")));
                                } else {
                                        replies.add(buildReplyWithMeta(null, agentName, aiContent, messageMap, null));
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

                                // 응답 identity 보존: agentId → 이름 → null. 배열 index/첫 번째 교수 폴백 금지.
                                Agent targetAgent = resolveResponseAgent(room.getAgents(), answerMap.get("agentId"), agentName);

                                saveRoomMessage(room, targetAgent, aiAnswer, "AI", processStepsJson);

                                if (targetAgent != null) {
                                        replies.add(buildReplyWithMeta(targetAgent.getId(), targetAgent.getName(), aiAnswer,
                                                        answerMap, extractPersonaTag(targetAgent.getPersona(), "지식수준")));
                                } else {
                                        replies.add(buildReplyWithMeta(null, agentName, aiAnswer, answerMap, null));
                                }
                        }
                }

                // ai07 신계약 필드(세션/상태/가드) — non-stream 폴백도 stream 의 all_complete 와 같은 정보를 프론트에 준다.
                Map<String, Object> rawSocraticState = asMap(response, "socraticState");
                Map<String, Object> rawSimulationState = asMap(response, "simulationState");
                Map<String, Object> rawDebateState = asMap(response, "debateState");
                Map<String, Object> rawDebateResult = asMap(response, "debateResult");
                Object rawBlocked = response != null ? response.get("blocked") : null;
                String guardCode = response != null && response.get("code") != null ? response.get("code").toString() : null;
                if (guardCode != null) {
                        log.info("[CHAT MODE-GUARD] roomId={} mode={} code={} status={} — 모드 안내 상태로 전달(기본 답변 렌더 금지)",
                                        roomId, responseLearningMode, guardCode, response.get("status"));
                }
                return ChatDTO.MultiChatResponse.builder()
                                // 실패 응답은 success=false 를 명시하는데 성공은 null 이라 계약이 비대칭이었다 → 성공도 명시.
                                .success(Boolean.TRUE)
                                .mode(responseMode)
                                .learningMode(responseLearningMode)
                                .sessionId(response != null && response.get("sessionId") != null ? response.get("sessionId").toString() : null)
                                .socraticState(rawSocraticState)
                                .simulationState(rawSimulationState)
                                .debateState(rawDebateState)
                                .turnIndex(response != null ? asInteger(response.get("turnIndex")) : null)
                                .status(response != null && response.get("status") != null ? response.get("status").toString() : null)
                                .code(guardCode)
                                .blocked(rawBlocked instanceof Boolean ? (Boolean) rawBlocked : (guardCode != null ? Boolean.TRUE : null))
                                .message(response != null && response.get("message") != null ? response.get("message").toString() : null)
                                .topic(response != null && response.get("topic") != null ? response.get("topic").toString() : null)
                                .debateStrength(response != null && response.get("debateStrength") != null ? response.get("debateStrength").toString() : null)
                                .debateResult(rawDebateResult)
                                .debatePositions(response != null && response.get("debatePositions") instanceof List
                                                ? (List<Object>) response.get("debatePositions") : null)
                                .answers(response != null && response.get("answers") instanceof List
                                                ? (List<Object>) response.get("answers") : null)
                                .questionIntensity(response != null && response.get("questionIntensity") != null ? response.get("questionIntensity").toString() : null)
                                .hintPolicy(response != null && response.get("hintPolicy") != null ? response.get("hintPolicy").toString() : null)
                                .scenarioType(response != null && response.get("scenarioType") != null ? response.get("scenarioType").toString() : null)
                                .difficulty(response != null && response.get("difficulty") != null ? response.get("difficulty").toString() : null)
                                .choiceCount(response != null ? asInteger(response.get("choiceCount")) : null)
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
        public Flux<ServerSentEvent<String>> chatStream(Long userId, Long roomId, ChatDTO.MultiChatRequest request) {
                return chatStream(userId, roomId, request, resolveRequestId(request.getMessageId()));
        }

        @Transactional
        public Flux<ServerSentEvent<String>> chatStream(Long userId, Long roomId, ChatDTO.MultiChatRequest request, String clientRequestId) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new java.util.NoSuchElementException("해당 채팅방을 찾을 수 없습니다."));
                if (!room.getUser().getId().equals(userId)) {
                        throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
                }
                final String requestId = (clientRequestId != null && !clientRequestId.isBlank()) ? clientRequestId
                                : resolveRequestId(request.getMessageId());

                // STRICT TARGETING: targetAgentId 는 방 agent 의 stable id(PK) 로만 해석한다.
                //  방에 없는 id 는 첫 번째 교수로 폴백하지 않고 400(IllegalArgumentException) 으로 거절한다.
                //  null/blank 는 기존 전체 멀티에이전트 협업 모드 그대로.
                Agent explicitTarget = resolveExplicitTargetAgent(room.getAgents(), request.getTargetAgentId());
                log.info("[TARGET-AGENT] roomId={} requestId={} targetAgentId={} resolved={} scope={} roomAgents={}",
                                roomId, requestId, request.getTargetAgentId(),
                                explicitTarget != null ? explicitTarget.getId() + ":" + explicitTarget.getName() : null,
                                explicitTarget != null ? "single" : "all",
                                room.getAgents().stream().map(a -> a.getId() + ":" + a.getName()).toList());

                // 사용자 메시지 저장 — "다시 시도" 멱등: 직전 메시지가 같은 내용의 USER 메시지(= AI 답변 없이 끝난 턴)면
                //  다시 저장하지 않는다(재시도마다 USER 행이 중복 적재되던 문제. RDS 에서 연속 중복 16건 관측).
                transactionTemplate.execute(status -> {
                        if (isRetryOfUnansweredTurn(roomId, request.getMessage())) {
                                log.info("[CHAT RETRY] roomId={} requestId={} 직전 미응답 USER 메시지와 동일 → 중복 저장 생략", roomId, requestId);
                                return null;
                        }
                        // USER 행에도 requestId 를 남긴다: 취소/새로고침으로 늦게(다음 이벤트 시점) partial 영속되는 AI 답변이
                        //  다음 질문 뒤에 저장되더라도 프론트가 requestId 로 원래 질문 아래에 붙일 수 있다(history ordering).
                        saveRoomMessage(room, null, request.getMessage(), "USER", null,
                                        new AnswerMeta(requestId, null, null, null, null, null, null, null, null));
                        return null;
                });

                // ── Intent Router 게이트 (surface=learning_mate) ─────────────────────────
                // terminal/파이프라인은 AI 스트림을 시작하지 않고 단일 라우팅 이벤트로 종료. WARN은 notice 후 진행.
                IntentDTO.RouteResult route = intentRouterService.route(
                                request.getMessage(), "learning_mate", learningMateContext(roomId, request));
                if (route.isTerminal() || route.isPipeline()) {
                        List<ServerSentEvent<String>> routed = new java.util.ArrayList<>();
                        handleLearningMateRouted((event, json) -> routed.add(sse(event, json)), route, userId, request);
                        return Flux.fromIterable(routed);
                }
                final String routeWarning = route.isWarn() ? route.userMessage() : null;

                // FastAPI 요청 바디 (블로킹과 동일 로직 재사용; room.getAgents() lazy 접근은 현재 트랜잭션 내)
                Map<String, Object> requestBody = buildFastApiRequestBody(room, roomId, request, userId, requestId);

                String effectiveLearningMode = normalizeLearningMode(firstNonBlank(
                                request.getLearningMode(), room.getLearningMode(), "basic"));

                // buildFastApiRequestBody가 확정한 최종 mode/learningMode/agents 수로 라우팅을 결정한다.
                int agentCount = (requestBody.get("agents") instanceof List)
                                ? ((List<?>) requestBody.get("agents")).size() : 0;
                Object fapiMode = requestBody.get("mode");
                Object fapiLearningMode = requestBody.get("learningMode");

                // AI07 v2(basic_v2 파이프라인)는 단일 에이전트 basic 도 같은 SSE 계약(turn_start/agent_start/agent_answer/all_complete/done,
                //  eventId/turnId/agentCoverage)으로 스트리밍한다 → 기본은 모두 relayRemoteStream 으로 중계한다(stream/non-stream 의미 동일).
                //  Spring 자체 1차/2차/3차 오케스트레이션(non-stream 3회 호출)은 AI_BASIC_INTERNAL_STAGES_ENABLED=true 일 때만 유지한다(레거시).
                boolean useBasicOrchestration = "basic".equals(effectiveLearningMode) && agentCount <= 1
                                && envBool("AI_BASIC_INTERNAL_STAGES_ENABLED", false);

                log.info("[CHAT ROUTE] roomId={} requestId={} effectiveLearningMode={} effectiveMode={} agents.size={} targetAgentId={} fastapiPayload.mode={} fastapiPayload.learningMode={} route={}",
                                roomId, requestId, effectiveLearningMode, fapiMode, agentCount, requestBody.get("targetAgentId"), fapiMode, fapiLearningMode,
                                useBasicOrchestration ? "orchestrateBasicStream" : "relayRemoteStream");

                // WARN: 경고 notice를 먼저 보내고 기존 학습 답변 스트림을 그대로 이어간다(중복 토큰 append 아님).
                Flux<ServerSentEvent<String>> notice = routeWarning != null
                                ? Flux.just(sse("route_notice", toJson(Map.of(
                                                "type", "route_notice", "routeAction", "WARN", "message", routeWarning))))
                                : Flux.empty();

                Flux<ServerSentEvent<String>> body = useBasicOrchestration
                                ? orchestrateBasicStream(roomId, requestId, request, requestBody)
                                : relayRemoteStream(roomId, requestId, requestBody, request, room);

                final String rid = requestId;
                final java.util.concurrent.atomic.AtomicBoolean committed = new java.util.concurrent.atomic.AtomicBoolean(false);
                // 응답 커밋 전(이벤트 0건) 실패는 상태코드+JSON 으로(AiUpstreamException → GlobalExceptionHandler), 커밋 후 실패는
                //  error/done 이벤트로 정상 종료한다(500·premature close 금지). 정상 SSE 로 위장하지 않는다(§10).
                return withHeartbeat(notice.concatWith(body))
                                .doOnNext(ev -> committed.set(true))
                                .onErrorResume(err -> {
                                        if (!committed.get()) {
                                                if (err instanceof AiUpstreamException) {
                                                        return Flux.error(err);
                                                }
                                                log.error("[AI-STREAM] roomId={} requestId={} 스트림 개시 전 오류 → 503 JSON: {}", roomId, rid, err.toString());
                                                return Flux.error(AiUpstreamException.unavailable(rid, null));
                                        }
                                        log.error("[AI-STREAM] roomId={} requestId={} 예기치 못한 스트림 오류 — error/done 으로 종료: {}",
                                                        roomId, rid, err.toString());
                                        return Flux.just(
                                                        sse("error", toJson(Map.of("type", "error", "eventType", "stream_error", "code", "AI_STREAM_INTERNAL",
                                                                        "failureCode", "AI_STREAM_INTERNAL", "status", "error", "degraded", true,
                                                                        "message", "AI 스트리밍 중 오류가 발생했습니다.", "requestId", rid))),
                                                        sse("done", toJson(Map.of("type", "done", "eventType", "done", "status", "error", "requestId", rid,
                                                                        "isFinal", true))));
                                });
        }

        // ── 기본채팅 1차/2차/3차 오케스트레이션 ────────────────────────────────────────
        //  reactor 체인으로 순차 실행하며 .block() 없이 각 단계 완료 시점에 stage_complete 이벤트를 즉시 emit한다.
        //  1차: 빠른 Ollama 초안(짧은 timeout) → 2차: 1차를 검증/보완 → 3차: 1차·2차에 대한 상호 피드백.
        private Flux<ServerSentEvent<String>> orchestrateBasicStream(Long roomId, String requestId,
                        ChatDTO.MultiChatRequest request, Map<String, Object> baseBody) {
                long stage1Timeout = envSeconds("AI_BASIC_STAGE1_TIMEOUT_SECONDS", 30);
                long stageNTimeout = envSeconds("AI_BASIC_STAGEN_TIMEOUT_SECONDS", 60);
                // 기본 채팅은 "선택된 에이전트의 최종 답변"만 보여준다는 정책상, 내부 검증(2차)/상호 피드백(3차)은
                //  기본 비활성이다. (켜더라도 React는 visible=false phase로 받아 기본 UI에 노출하지 않는다)
                boolean internalStagesEnabled = envBool("AI_BASIC_INTERNAL_STAGES_ENABLED", false);

                String question = request.getMessage();
                // 다시 생성 제어: forceRegenerate 또는 attempt>1 이면 cache 우회 + 변형 지시를 프롬프트에 덧붙인다.
                String regenSuffix = buildRegenSuffix(request);

                // Flux.create: 구독은 MVC(ReactiveTypeHandler)가 하고, 내부 체인 구독은 sink 수명에 묶는다(onDispose → dispose).
                return Flux.create(sink -> {
                        final SseOut out = (event, json) -> sink.next(sse(event, json));
                        final long startedAt = System.currentTimeMillis();

                        // 단계 결과 누적 (단일 구독자가 순차 갱신하므로 plain List로 충분)
                        List<Map<String, Object>> initialAnswers = new java.util.ArrayList<>();
                        List<Map<String, Object>> validatedAnswers = new java.util.ArrayList<>();
                        List<Map<String, Object>> peerFeedback = new java.util.ArrayList<>();
                        final java.util.concurrent.atomic.AtomicBoolean stage1Failed = new java.util.concurrent.atomic.AtomicBoolean(false);

                        safeSend(out, "turn_start",
                                        Map.of("type", "turn_start", "message", "AI 응답 생성을 시작합니다.", "requestId", requestId));

                        // 1차(primary): 각 에이전트가 자신의 persona/지식수준으로 질문에 직접 답한다(검증·피드백 금지).
                        //  non-stream 호출은 failover 서비스가 PRIMARY→SECONDARY 순으로 시도한다.
                        Mono<List<Map<String, Object>>> chain = aiFailover
                                        .callMultiChat(roomId, requestId, stageBody(baseBody, primaryPrompt(question, regenSuffix), 1),
                                                        Duration.ofSeconds(stage1Timeout))
                                        .map(resp -> extractAnswerRows(resp, 1))
                                        .onErrorResume(e -> {
                                                log.warn("기본채팅 1차 생성 실패 roomId={} requestId={} err={}", roomId, requestId,
                                                                AiMultiChatFailoverService.brief(e));
                                                return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                        })
                                        .flatMap(primaryRows -> {
                                                if (primaryRows.isEmpty()) {
                                                        // 실패: 예전엔 "1차 답변 생성이 지연되고 있습니다" 를 정상 답변(stage_complete/all_complete)로 내려
                                                        //  AI 메시지로 DB 에 저장하고 done=done 으로 끝냈다(실패가 성공으로 위장). 이제는 error 이벤트로 알리고
                                                        //  all_complete/영속화 없이 done(status=error) 로 종료한다 → 프론트가 재시도 안내를 띄운다.
                                                        stage1Failed.set(true);
                                                        safeSend(out, "error", Map.of("type", "error", "code", "AI_BASIC_STAGE1_FAILED",
                                                                        "message", "AI 답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.",
                                                                        "requestId", requestId));
                                                        return Mono.<List<Map<String, Object>>>empty();
                                                }
                                                initialAnswers.addAll(primaryRows);
                                                emitStage(out, 1, "primary", "FIRST_DRAFT", "answers", initialAnswers, true);

                                                if (!internalStagesEnabled) {
                                                        // 기본 채팅 정책: 1차(최종) 답변만 노출하고 종료. 내부 검증/피드백은 생성하지 않는다.
                                                        return Mono.<List<Map<String, Object>>>empty();
                                                }

                                                // 1차 답변(들)을 에이전트명과 함께 묶어 2·3차 프롬프트의 검토 대상으로 넣는다.
                                                String primaryContext = labeledAnswers(primaryRows);
                                                // 2차(verification): 1차를 사실성/누락/논리 관점에서 검증·지적 (재답변 금지)
                                                return aiFailover
                                                                .callMultiChat(roomId, requestId,
                                                                                stageBody(baseBody, verifyPrompt(question, primaryContext, regenSuffix), 2),
                                                                                Duration.ofSeconds(stageNTimeout))
                                                                .map(resp -> extractAnswerRows(resp, 2))
                                                                .onErrorResume(e -> {
                                                                        log.warn("기본채팅 2차 검증 실패 roomId={} requestId={} err={}", roomId, requestId,
                                                                                        AiMultiChatFailoverService.brief(e));
                                                                        return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                                                })
                                                                .flatMap(verifyRows -> {
                                                                        if (!verifyRows.isEmpty()) {
                                                                                validatedAnswers.addAll(verifyRows);
                                                                                emitStage(out, 2, "verification", "VALIDATION", "answers", validatedAnswers, false);
                                                                        }
                                                                        String verifyContext = labeledAnswers(verifyRows);
                                                                        // 3차(feedback): 1차·2차를 참고한 에이전트 간 상호 피드백(동의/반박/추가관점)
                                                                        return aiFailover
                                                                                        .callMultiChat(roomId, requestId,
                                                                                                        stageBody(baseBody, feedbackPrompt(question, primaryContext, verifyContext, regenSuffix), 3),
                                                                                                        Duration.ofSeconds(stageNTimeout))
                                                                                        .map(resp -> toFeedbackRows(extractAnswerRows(resp, 3)))
                                                                                        .onErrorResume(e -> {
                                                                                                log.warn("기본채팅 3차 피드백 실패 roomId={} requestId={} err={}", roomId, requestId,
                                                                                                                AiMultiChatFailoverService.brief(e));
                                                                                                return Mono.just(java.util.Collections.<Map<String, Object>>emptyList());
                                                                                        })
                                                                                        .doOnNext(fbRows -> {
                                                                                                if (!fbRows.isEmpty()) {
                                                                                                        peerFeedback.addAll(fbRows);
                                                                                                        emitStage(out, 3, "feedback", "PEER_FEEDBACK", "feedbacks", peerFeedback, false);
                                                                                                }
                                                                                        })
                                                                                        .map(fbRows -> initialAnswers);
                                                                });
                                        });

                        // 종료 처리(영속화 = JDBC 블로킹)는 reactor 이벤트 루프가 아닌 boundedElastic 에서 수행한다.
                        Disposable subscription = chain
                                        .publishOn(Schedulers.boundedElastic())
                                        .subscribe(
                                                        ignored -> { /* 단계별 emit은 위 체인에서 이미 수행됨 */ },
                                                        err -> {
                                                                log.error("기본채팅 오케스트레이션 오류 roomId={} requestId={} err={}", roomId, requestId, err.toString());
                                                                finishBasicStream(out, roomId, requestId, startedAt, initialAnswers, validatedAnswers, peerFeedback);
                                                                sink.complete();
                                                        },
                                                        () -> {
                                                                if (stage1Failed.get()) {
                                                                        long elapsed = System.currentTimeMillis() - startedAt;
                                                                        out.send("done", toJson(Map.of("type", "done", "status", "error",
                                                                                        "requestId", requestId, "elapsedMs", elapsed, "mode", "basic-orchestration")));
                                                                        log.warn("[AI-STREAM-RESULT] roomId={} requestId={} route=orchestrateBasicStream elapsedMs={} allComplete=false answers=0 reason=stage1-failed",
                                                                                        roomId, requestId, elapsed);
                                                                } else {
                                                                        finishBasicStream(out, roomId, requestId, startedAt, initialAnswers, validatedAnswers, peerFeedback);
                                                                }
                                                                sink.complete();
                                                        });
                        // 클라이언트 절단 시 체인을 dispose 하지 않는다: 1차 생성이 끝나면 finishBasicStream 이 영속화까지 완주하고,
                        //  sink.next 는 cancel 뒤 no-op 이라 전달만 멈춘다(relayRemoteStream 과 같은 정책 — 새로고침 시 답변 유실 방지).
                        sink.onDispose(() -> {
                                if (!subscription.isDisposed()) {
                                        log.info("[AI-STREAM] roomId={} requestId={} 클라이언트 연결 종료 — 기본 오케스트레이션은 영속화를 위해 완주시킨다",
                                                        roomId, requestId);
                                }
                        });
                }, FluxSink.OverflowStrategy.BUFFER);
        }

        // 누적된 1차/2차/3차를 all_complete(processSteps 포함)로 내려보내고 영속화한 뒤 done 을 보낸다.
        private void finishBasicStream(SseOut out, Long roomId, String requestId, long startedAt,
                        List<Map<String, Object>> initialAnswers,
                        List<Map<String, Object>> validatedAnswers,
                        List<Map<String, Object>> peerFeedback) {
                boolean allComplete = false;
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

                        Map<String, Object> allCompleteMap = new LinkedHashMap<>();
                        allCompleteMap.put("type", "all_complete");
                        allCompleteMap.put("mode", "basic");
                        allCompleteMap.put("learningMode", "basic");
                        allCompleteMap.put("answers", finalAnswers);
                        allCompleteMap.put("processSteps", processSteps);
                        allCompleteMap.put("status", "COMPLETED");
                        allCompleteMap.put("requestId", requestId);

                        String json = objectMapper.writeValueAsString(allCompleteMap);
                        out.send("all_complete", json);
                        allComplete = true;
                        persistStreamedAnswers(roomId, json);
                } catch (Exception e) {
                        log.warn("기본채팅 종료 처리 실패 roomId={} requestId={}: {}", roomId, requestId, e.getMessage());
                } finally {
                        long elapsed = System.currentTimeMillis() - startedAt;
                        out.send("done", toJson(Map.of("type", "done", "status", allComplete ? "done" : "error",
                                        "requestId", requestId, "elapsedMs", elapsed, "mode", "basic-orchestration")));
                        log.info("[AI-STREAM-RESULT] roomId={} requestId={} route=orchestrateBasicStream elapsedMs={} allComplete={} answers={}",
                                        roomId, requestId, elapsed, allComplete, initialAnswers.size());
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
        private void emitStage(SseOut out, int stage, String phase, String stageType, String payloadKey,
                        List<Map<String, Object>> rows, boolean visible) {
                Map<String, Object> data = new LinkedHashMap<>();
                data.put("type", "stage_complete");
                data.put("phase", phase);
                data.put("stage", stage);
                data.put("stageType", stageType);
                // visible/uiPhase: 기본 UI 노출 여부 메타데이터. 1차=ANSWER(노출), 2·3차=내부검증/피어피드백(숨김).
                data.put("visible", visible);
                data.put("uiPhase", visible ? "ANSWER" : (stage == 2 ? "INTERNAL_VALIDATION" : "PEER_FEEDBACK"));
                data.put(payloadKey, rows);
                safeSend(out, "stage_complete", data);
        }

        private void safeSend(SseOut out, String event, Map<String, Object> data) {
                try {
                        out.send(event, objectMapper.writeValueAsString(data));
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

        // terminal/파이프라인을 단일 SSE 이벤트 묶음으로 처리한다(기존 AI 스트림 미시작). 호출자가 Flux 로 감싼다.
        private void handleLearningMateRouted(SseOut out, IntentDTO.RouteResult route,
                        Long userId, ChatDTO.MultiChatRequest request) {
                try {
                        if (route.isPipeline()) {
                                Long materialId = request.getMaterialId();
                                if (materialId == null) {
                                        safeSend(out, "route_message", Map.of("type", "route_message",
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
                                        safeSend(out, "route_pipeline", data);
                                }
                        } else { // terminal: DIRECT_REPLY/BLOCK/CLARIFY
                                safeSend(out, "route_message", Map.of("type", "route_message",
                                                "routeAction", route.actionName(), "message", route.userMessage()));
                        }
                        safeSend(out, "all_complete", Map.of("type", "all_complete", "routed", true));
                } catch (Exception e) {
                        log.warn("[intent-router] learning_mate routed 처리 실패: {}", e.toString());
                } finally {
                        safeSend(out, "done", Map.of("type", "done", "status", "done", "routed", true));
                }
        }

        // 원격 FastAPI /api/ai/multi-chat/stream SSE를 브라우저로 중계 (다중 에이전트/토론/소크라테스/상황극).
        //  PRIMARY(ai07) stream → SECONDARY(EC2 :8000) stream → non-stream 폴백은 AiMultiChatFailoverService 가 담당하며
        //  block() 없이 리액티브 체인으로 컨트롤러까지 이어진다. 영속화(JDBC)는 boundedElastic 에서 수행한다.
        private Flux<ServerSentEvent<String>> relayRemoteStream(Long roomId, String requestId, Map<String, Object> requestBody,
                        ChatDTO.MultiChatRequest request, AgentChatRoom room) {
                final long nonStreamTimeout = resolveAiTimeoutSeconds(
                                firstNonBlank(request.getLearningMode(), room.getLearningMode()), request.getMode());
                // 성능 측정: Spring stream open → upstream 첫 이벤트 → 첫 agent_answer → all_complete 지연을 분리해 로깅한다.
                final long relayOpenAt = System.currentTimeMillis();
                final java.util.concurrent.atomic.AtomicBoolean firstSeen = new java.util.concurrent.atomic.AtomicBoolean(false);
                final java.util.concurrent.atomic.AtomicBoolean firstAnswerSeen = new java.util.concurrent.atomic.AtomicBoolean(false);
                final java.util.concurrent.atomic.AtomicBoolean persisted = new java.util.concurrent.atomic.AtomicBoolean(false);
                final java.util.concurrent.atomic.AtomicReference<String> turnIdRef = new java.util.concurrent.atomic.AtomicReference<>(null);
                // 취소(브라우저 절단/Stop/새 질문/모드·방 전환) 시점까지 받은 성공 답변 — 이미 사용자에게 보인 답변은 잃지 않는다.
                final List<String> receivedAnswers = java.util.Collections.synchronizedList(new java.util.ArrayList<>());

                // 리액티브 체인을 끊지 않는다(Flux.create/내부 subscribe 없음): MVC 가 이 Flux 를 구독하고, 브라우저가 끊기면 MVC cancel →
                //  이 체인 cancel → WebClient 구독 취소(업스트림 소켓 종료) → AI07 [SSE-CANCEL] 절단 감시가 추론을 멈춘다(§16).
                //  backpressure 도 WebClient 까지 그대로 전파된다(무한 버퍼 없음, §18). 영속화(JDBC)는 boundedElastic 에서 수행한다.
                return aiFailover
                                .streamMultiChat(roomId, requestId, requestBody, Duration.ofSeconds(nonStreamTimeout))
                                .publishOn(Schedulers.boundedElastic())
                                .doOnNext(ev -> {
                                        String event = ev.event() != null ? ev.event() : "message";
                                        if (firstSeen.compareAndSet(false, true)) {
                                                log.info("[CHAT PERF] roomId={} requestId={} first event='{}' after {}ms", roomId, requestId, event,
                                                                System.currentTimeMillis() - relayOpenAt);
                                        }
                                        if ("turn_start".equals(event) && ev.data() != null && turnIdRef.get() == null) {
                                                turnIdRef.set(extractString(ev.data(), "turnId"));
                                        }
                                        if ("agent_answer".equals(event) && ev.data() != null) {
                                                if (firstAnswerSeen.compareAndSet(false, true)) {
                                                        log.info("[CHAT PERF] roomId={} requestId={} first agent_answer after {}ms", roomId, requestId,
                                                                        System.currentTimeMillis() - relayOpenAt);
                                                }
                                                receivedAnswers.add(ev.data());
                                        }
                                        if ("all_complete".equals(event) && ev.data() != null) {
                                                log.info("[CHAT PERF] roomId={} requestId={} all_complete after {}ms", roomId, requestId,
                                                                System.currentTimeMillis() - relayOpenAt);
                                                // FastAPI 이벤트는 필드 변형 없이 그대로 중계하고, all_complete 만 별도 트랜잭션으로 영속화한다(멱등).
                                                if (persisted.compareAndSet(false, true)) {
                                                        persistStreamedAnswers(roomId, ev.data(), requestId);
                                                }
                                        }
                                })
                                .doOnCancel(() -> {
                                        // 취소 체인: 이미 받은 성공 답변만 영속화(all_complete 가 없으므로 partial). 실패/대기 중 답변은 저장하지 않는다.
                                        if (persisted.compareAndSet(false, true) && !receivedAnswers.isEmpty()) {
                                                List<String> snapshot = new java.util.ArrayList<>(receivedAnswers);
                                                log.info("[CHAT PERSIST] roomId={} requestId={} turnId={} 클라이언트 취소 — 수신 완료 답변 {}건만 영속화(partial)",
                                                                roomId, requestId, turnIdRef.get(), snapshot.size());
                                                Schedulers.boundedElastic().schedule(() ->
                                                                persistPartialAnswers(roomId, requestId, turnIdRef.get(), snapshot));
                                        }
                                });
        }

        private String extractString(String json, String key) {
                try {
                        Map<String, Object> m = objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
                        Object v = m.get(key);
                        return v != null ? String.valueOf(v) : null;
                } catch (Exception e) {
                        return null;
                }
        }

        // 취소 시점까지 받은 agent_answer 이벤트(JSON)들을 all_complete 와 같은 규칙으로 영속화한다(멱등 키 = eventId).
        private void persistPartialAnswers(Long roomId, String requestId, String turnId, List<String> agentAnswerJsons) {
                List<Map<String, Object>> answers = new java.util.ArrayList<>();
                for (String json : agentAnswerJsons) {
                        try {
                                answers.add(objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {}));
                        } catch (Exception e) {
                                log.warn("[CHAT PERSIST] roomId={} requestId={} partial 답변 파싱 실패(생략)", roomId, requestId);
                        }
                }
                Map<String, Object> synthetic = new LinkedHashMap<>();
                synthetic.put("type", "all_complete");
                synthetic.put("status", "CANCELLED");
                synthetic.put("requestId", requestId);
                synthetic.put("turnId", turnId);
                synthetic.put("answers", answers);
                persistAnswerRows(roomId, synthetic, requestId, "partial");
        }

        // 스트리밍 all_complete 결과(JSON)를 파싱해 AI 메시지 + processStepsJson을 영속화한다.
        private void persistStreamedAnswers(Long roomId, String allCompleteJson) {
                persistStreamedAnswers(roomId, allCompleteJson, null);
        }

        private void persistStreamedAnswers(Long roomId, String allCompleteJson, String requestId) {
                try {
                        Map<String, Object> resp = objectMapper.readValue(
                                        allCompleteJson, new TypeReference<Map<String, Object>>() {});
                        persistAnswerRows(roomId, resp, requestId, "all_complete");
                } catch (Exception e) {
                        // 화면엔 답변이 보였는데 DB 에는 없는 "조용한 유실" — 반드시 ERROR 로 남긴다.
                        log.error("[CHAT PERSIST] 스트리밍 결과 영속화 실패 roomId={} (화면 답변은 브라우저 캐시에만 존재): {}", roomId, e.toString(), e);
                }
        }

        /** 영속화 메타(AI07 SSE 계약). content 는 담지 않는다. */
        record AnswerMeta(String requestId, String turnId, String eventId, Integer agentIndex, String stage, String status,
                        String mode, String personalityKey, String knowledgeLevelKey) { }

        /**
         * AI07 answers[] 1건의 멱등 키. eventId 가 있으면 그대로, 없으면 안전한 composite(turnId:agentId:stage:displayOrder).
         * turnId 도 없으면(레거시 응답) requestId 기준 composite. 그것도 없으면 null(멱등 검사 불가 → 저장).
         */
        static String dedupKeyOf(Map<String, Object> answer, String turnId, String requestId, int index) {
                Object ev = answer.get("eventId");
                if (ev != null && !String.valueOf(ev).isBlank()) {
                        return String.valueOf(ev);
                }
                String scope = turnId != null && !turnId.isBlank() ? turnId : (requestId != null && !requestId.isBlank() ? requestId : null);
                if (scope == null) {
                        return null;
                }
                Object aid = answer.get("agentId");
                Object stage = answer.get("stage") != null ? answer.get("stage")
                                : (answer.get("stageType") != null ? answer.get("stageType") : answer.get("actType"));
                Object order = answer.get("displayOrder") != null ? answer.get("displayOrder")
                                : (answer.get("sequence") != null ? answer.get("sequence") : index);
                return scope + ":" + (aid != null ? aid : "-") + ":" + (stage != null ? stage : "-") + ":" + order;
        }

        /**
         * answers[] 를 AI 메시지로 영속화한다(stream all_complete / cancel partial / non-stream 공용).
         *  · 실패 답변(status FAILED/ERROR/CANCELLED/TIMEOUT)·빈 본문은 저장하지 않는다(실패를 성공으로 위장 금지, §23).
         *  · 멱등: eventId(또는 composite) 가 이미 있으면 건너뛴다(reload/reconnect/late event/재시도 중복 방지, §25).
         *  · identity: agentId → 이름 → null(가상 작성자 debate-consensus 등은 agent 없이 저장, 첫 교수 폴백 금지, §20/§22).
         */
        void persistAnswerRows(Long roomId, Map<String, Object> resp, String requestId, String source) {
                Object psObj = resp.get("processSteps");
                if (psObj == null) {
                        psObj = structuredProcessSteps(resp);
                }
                String processStepsJson;
                try {
                        processStepsJson = psObj != null ? objectMapper.writeValueAsString(psObj) : null;
                } catch (Exception e) {
                        processStepsJson = null;
                }
                Object ansObj = resp.get("answers");
                if (!(ansObj instanceof List)) {
                        log.warn("[CHAT PERSIST] roomId={} {} 에 answers 배열이 없어 AI 메시지 영속화 생략 keys={}", roomId, source, resp.keySet());
                        return;
                }
                @SuppressWarnings("unchecked")
                List<Map<String, Object>> answers = (List<Map<String, Object>>) ansObj;
                final String turnId = resp.get("turnId") != null ? String.valueOf(resp.get("turnId")) : null;
                final String rid = requestId != null ? requestId : (resp.get("requestId") != null ? String.valueOf(resp.get("requestId")) : null);
                final String mode = resp.get("learningMode") != null ? String.valueOf(resp.get("learningMode"))
                                : (resp.get("mode") != null ? String.valueOf(resp.get("mode")) : null);
                final String psJson = processStepsJson;

                int saved = 0, skippedDup = 0, skippedFailed = 0;
                for (int i = 0; i < answers.size(); i++) {
                        Map<String, Object> a = answers.get(i);
                        if (a == null) {
                                continue;
                        }
                        Object answerObj = a.get("answer") != null ? a.get("answer") : a.get("content");
                        String content = answerObj != null ? answerObj.toString() : "";
                        if (content.isBlank() || AgentProfileContract.isFailedAnswer(a)) {
                                skippedFailed++;
                                continue;
                        }
                        String dedupKey = dedupKeyOf(a, turnId, rid, i);
                        Map<String, Object> identity = AgentProfileContract.identityOf(a);
                        AnswerMeta meta = new AnswerMeta(rid, turnId, dedupKey, (Integer) identity.get("agentIndex"),
                                        str(a.get("stage") != null ? a.get("stage") : a.get("stageType")), str(identity.get("status")), mode,
                                        str(identity.get("personalityKey")), str(identity.get("knowledgeLevelKey")));
                        String agentName = String.valueOf(a.getOrDefault("agentName", "AI"));
                        Boolean stored = transactionTemplate.execute(status -> {
                                AgentChatRoom room = agentChatRoomRepository.findById(roomId).orElse(null);
                                if (room == null) {
                                        return Boolean.FALSE;
                                }
                                if (dedupKey != null && chatMessageRepository.existsByAgentChatRoomIdAndEventId(roomId, dedupKey)) {
                                        return null;
                                }
                                // 응답 identity 보존: agentId → 이름 → null(첫 번째 교수 폴백 금지 — 새로고침 후 작성자 뒤바뀜 방지).
                                Agent targetAgent = resolveResponseAgent(room.getAgents(), a.get("agentId"), agentName);
                                saveRoomMessage(room, targetAgent, content, "AI", psJson, meta);
                                return Boolean.TRUE;
                        });
                        if (stored == null) {
                                skippedDup++;
                        } else if (stored) {
                                saved++;
                        }
                }
                log.info("[CHAT PERSIST] roomId={} requestId={} turnId={} source={} saved={} skippedDuplicate={} skippedFailedOrEmpty={}",
                                roomId, rid, turnId, source, saved, skippedDup, skippedFailed);
        }

        private static String str(Object v) {
                return v != null ? String.valueOf(v) : null;
        }

        // 채팅방 기록 조회 — 소유자 검증(IDOR 방지) + created_at,id 정렬(같은 턴의 AI 답변 순서 고정)
        public List<ChatDTO.MessageResponse> getRoomChatHistory(Long userId, Long roomId) {
                AgentChatRoom room = agentChatRoomRepository.findById(roomId)
                                .orElseThrow(() -> new java.util.NoSuchElementException("해당 채팅방을 찾을 수 없습니다."));
                if (userId == null || room.getUser() == null || !room.getUser().getId().equals(userId)) {
                        throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
                }
                return chatMessageRepository.findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(roomId).stream()
                                .map(msg -> ChatDTO.MessageResponse.builder()
                                                .id(msg.getId())
                                                .content(msg.getContent())
                                                .sender(msg.getSender())
                                                .senderName(msg.getAgent() != null ? msg.getAgent().getName() : null)
                                                .agentId(msg.getAgent() != null ? msg.getAgent().getId() : null)
                                                .createdAt(msg.getCreatedAt())
                                                .processSteps(parseProcessSteps(msg.getProcessStepsJson()))
                                                .requestId(msg.getRequestId())
                                                .turnId(msg.getTurnId())
                                                .eventId(msg.getEventId())
                                                .agentIndex(msg.getAgentIndex())
                                                .stage(msg.getStage())
                                                .status(msg.getStatus())
                                                .mode(msg.getMode())
                                                .personalityKey(msg.getPersonalityKey())
                                                .knowledgeLevelKey(msg.getKnowledgeLevelKey())
                                                // 가상 작성자(debate-consensus/시스템)는 agent 가 없는 AI 행 — 프론트가 교수 카드가 아닌 시스템 작성자로 렌더.
                                                .authorKind("USER".equals(msg.getSender()) ? "USER" : (msg.getAgent() != null ? "AGENT" : "VIRTUAL"))
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

        // 재시도 멱등 판정: 방의 마지막 메시지가 최근 10분 내 같은 내용의 USER 메시지인가(= 답변 없이 끝난 턴의 재전송).
        private boolean isRetryOfUnansweredTurn(Long roomId, String message) {
                if (message == null) {
                        return false;
                }
                try {
                        return chatMessageRepository.findTopByAgentChatRoomIdOrderByCreatedAtDescIdDesc(roomId)
                                        .filter(last -> "USER".equals(last.getSender()))
                                        .filter(last -> message.trim().equals(String.valueOf(last.getContent()).trim()))
                                        .filter(last -> last.getCreatedAt() != null
                                                        && last.getCreatedAt().isAfter(java.time.LocalDateTime.now().minusMinutes(10)))
                                        .isPresent();
                } catch (Exception e) {
                        log.warn("[CHAT RETRY] 멱등 판정 실패 roomId={} — 기본 저장 진행: {}", roomId, e.toString());
                        return false;
                }
        }

        // 채팅 기록 저장 (processSteps 없는 경우)
        // ── Agent Identity 리졸버(STRICT TARGETING) ───────────────────────────────────
        //  · 요청 targetAgentId 는 방 agent 의 stable id(PK)로만 해석한다. 배열 index/표시명은 identity 가 아니다.
        //  · 못 찾으면 IllegalArgumentException(→ GlobalExceptionHandler 400). 첫 번째 교수 silent fallback 금지.
        //  · null/blank 는 "대상 미지정" = 기존 전체 멀티에이전트 협업 모드.
        static Agent resolveExplicitTargetAgent(List<Agent> roomAgents, String targetAgentId) {
                if (targetAgentId == null || targetAgentId.isBlank()) {
                        return null;
                }
                final String tid = targetAgentId.trim();
                List<Agent> agents = roomAgents != null ? roomAgents : java.util.Collections.emptyList();
                return agents.stream()
                                .filter(a -> a != null && a.getId() != null && String.valueOf(a.getId()).equals(tid))
                                .findFirst()
                                .orElseThrow(() -> new IllegalArgumentException(
                                                "TARGET_AGENT_NOT_FOUND: targetAgentId=" + tid + " 는 이 채팅방의 에이전트가 아닙니다. available="
                                                                + agents.stream().map(a -> String.valueOf(a.getId())).toList()));
        }

        //  응답(agent_answer/answers/messages)의 작성자 결정: agentId(문자/숫자 무관) → 이름 → null.
        //  null 이면 agent 없이 저장한다(다른 교수로 귀속시키지 않는다).
        static Agent resolveResponseAgent(List<Agent> roomAgents, Object agentId, String agentName) {
                List<Agent> agents = roomAgents != null ? roomAgents : java.util.Collections.emptyList();
                if (agentId != null) {
                        final String aid = String.valueOf(agentId).trim();
                        if (!aid.isEmpty() && !"null".equals(aid)) {
                                java.util.Optional<Agent> byId = agents.stream()
                                                .filter(a -> a != null && a.getId() != null && String.valueOf(a.getId()).equals(aid))
                                                .findFirst();
                                if (byId.isPresent()) {
                                        return byId.get();
                                }
                        }
                }
                if (agentName != null && !agentName.isBlank()) {
                        final String nm = agentName.trim();
                        java.util.Optional<Agent> byName = agents.stream()
                                        .filter(a -> a != null && a.getName() != null && a.getName().trim().equals(nm))
                                        .findFirst();
                        if (byName.isPresent()) {
                                return byName.get();
                        }
                }
                log.warn("[TARGET-AGENT] 응답 작성자 미해석 agentId={} agentName={} → agent 없이 저장(첫 교수 폴백 금지)", agentId, agentName);
                return null;
        }

        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender) {
                saveRoomMessage(room, agent, content, sender, null);
        }

        /**
         * ai07 로 보낼 previousAnswers 를 정리한다.
         *  · 마지막 항목이 이번 질문과 같은 USER 항목이면 제외한다(chatStream 은 USER 를 먼저 저장하므로 캐시 끝에 항상 이번 질문이 붙는다).
         *  · 최근 max 건만 남긴다(max ≤ 0 이면 전부 유지). 순서(오래된 → 최신)는 보존.
         */
        static List<Map<String, Object>> trimPreviousAnswers(List<Map<String, Object>> previousAnswers,
                        String currentMessage, int max) {
                if (previousAnswers == null || previousAnswers.isEmpty()) {
                        return previousAnswers == null ? java.util.Collections.emptyList() : previousAnswers;
                }
                List<Map<String, Object>> out = new java.util.ArrayList<>(previousAnswers);
                Map<String, Object> last = out.get(out.size() - 1);
                if (last != null && currentMessage != null
                                && "USER".equals(String.valueOf(last.get("role")))
                                && currentMessage.trim().equals(String.valueOf(last.get("answer")).trim())) {
                        out.remove(out.size() - 1);
                }
                if (max > 0 && out.size() > max) {
                        out = new java.util.ArrayList<>(out.subList(out.size() - max, out.size()));
                }
                return out;
        }

        // 채팅 기록 저장 (AI 메시지는 processStepsJson 함께 영속화)
        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender, String processStepsJson) {
                saveRoomMessage(room, agent, content, sender, processStepsJson, null);
        }

        private void saveRoomMessage(AgentChatRoom room, Agent agent, String content, String sender, String processStepsJson,
                        AnswerMeta meta) {
                ChatMessage.ChatMessageBuilder b = ChatMessage.builder()
                                .agentChatRoom(room)
                                .agent(agent)
                                .content(content)
                                .sender(sender)
                                .processStepsJson(processStepsJson);
                if (meta != null) {
                        b.requestId(meta.requestId()).turnId(meta.turnId()).eventId(meta.eventId()).agentIndex(meta.agentIndex())
                                        .stage(meta.stage()).status(meta.status()).mode(meta.mode())
                                        .personalityKey(meta.personalityKey()).knowledgeLevelKey(meta.knowledgeLevelKey());
                }
                ChatMessage message = b.build();
                chatMessageRepository.save(message);

                // Redis에도 캐싱
                redisChatService.savePersonalMessage(room.getId(), com.studybridge.api.dto.RedisChatMessage.builder()
                                .agentName("USER".equals(sender) ? "USER" : (agent != null ? agent.getName() : "AI"))
                                .answer(content)
                                .role("USER".equals(sender) ? "USER" : "ASSISTANT")
                                .agentId(agent != null ? agent.getId() : null)
                                .build());
        }

        private Map<String, Object> mapRequestAgent(
                        ChatDTO.RequestAgent agent,
                        String requestKnowledgeLevel,
                        String requestPersonality,
                        String requestPersonalityStrength) {
                String persona = nullToEmpty(agent.getPersona());
                String agentId = firstNonBlank(agent.getAgentId(), agent.getId());
                String agentKnowledgeLevel = normalizeKnowledgeLevel(firstNonBlank(
                                agent.getKnowledgeLevel(),
                                agent.getKnowledge_level(),
                                requestKnowledgeLevel,
                                "학사 수준"));
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
                // 에이전트별 canonical key + temperature(요청 agent의 명시값 우선, 없으면 성격에서 유도).
                agentMap.put("personalityStyle", firstNonBlank(agent.getPersonalityStyle(), personalityStyleKey(agentPersonality)));
                agentMap.put("temperature", personalityTemperature(agentPersonality, agent.getTemperature()));
                agentMap.put("personalityStrength", agentPersonalityStrength);
                agentMap.put("personality_strength", agentPersonalityStrength);
                agentMap.put("style", agentPersonality);
                agentMap.put("tone", agentPersonality);
                agentMap.put("knowledgeLevel", agentKnowledgeLevel);
                agentMap.put("knowledge_level", agentKnowledgeLevel);
                agentMap.put("knowledgeLevelLabel", knowledgeLevelLabel(agentKnowledgeLevel));
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

        private boolean envBool(String key, boolean defaultValue) {
                String v = System.getenv(key);
                if (v == null || v.isBlank()) {
                        return defaultValue;
                }
                String t = v.trim().toLowerCase();
                return t.equals("1") || t.equals("true") || t.equals("yes") || t.equals("on");
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

        /**
         * 방 에이전트 1명 → AI07 agents[] 항목. stream/non-stream/기본 오케스트레이션이 모두 같은 함수를 쓴다.
         *
         * <pre>
         *  identity : agentId(=id), agentSlot(1-based 순서), name(표시)
         *  persona  : personalityKey(6 canonical) / personalityLabel / personalityStyle(프론트 7키 호환) / personality(원문) / temperature
         *  knowledge: knowledgeLevelKey(5 canonical) / knowledgeLevelLabel / knowledgeLevel(INTRO..EXPERT 호환)
         *  unknown  : personalityKey/personalityStyle 을 비우고 원문만 전달(friendly/default 로 위장하지 않는다) + *Resolved=false
         * </pre>
         */
        static Map<String, Object> buildAgentPayload(Agent agent, int slot, String requestKnowledgeLevel, String requestPersonality,
                        String requestPersonalityStrength, String requestCustomInstruction, Double temperatureOverride) {
                String persona = nullToEmpty(agent.getPersona());
                AgentProfileContract.KnowledgeResolution knowledge = AgentProfileContract.resolveKnowledgeOrDefault(
                                extractPersonaTag(persona, "지식수준"), requestKnowledgeLevel);
                AgentProfileContract.PersonaResolution personaRes = AgentProfileContract.resolvePersona(
                                agent.getTone(), extractPersonaTag(persona, "성격"), requestPersonality);
                if ("missing".equals(personaRes.source())) {
                        // 방 생성 시 성격을 고르지 않은 레거시 에이전트 → 과거 기본값(전문적=logical) 유지(explicit default 로 취급).
                        personaRes = AgentProfileContract.resolvePersona("professional");
                }
                String agentPersonalityRaw = firstNonBlankStatic(agent.getTone(), extractPersonaTag(persona, "성격"), requestPersonality,
                                personaRes.label());
                String agentCustomInstruction = firstNonBlankStatic(stripPersonaTags(persona), requestCustomInstruction, agent.getGoal(), "");
                double temperature = AgentProfileContract.temperatureFor(personaRes, temperatureOverride);

                Map<String, Object> agentMap = new LinkedHashMap<>();
                agentMap.put("id", agent.getId());
                agentMap.put("agentId", agent.getId());
                agentMap.put("agentSlot", slot);
                agentMap.put("name", agent.getName());
                agentMap.put("role", agent.getRole());
                // agentPreset은 persona [프리셋: X] 태그에서 복원해 FastAPI 프롬프트로 전달
                agentMap.put("agentPreset", extractPersonaTag(persona, "프리셋"));
                agentMap.put("personality", agentPersonalityRaw);
                agentMap.put("personalityKey", personaRes.key());
                agentMap.put("personalityLabel", personaRes.label());
                agentMap.put("personalityStyle", personaRes.legacyStyle());
                agentMap.put("personalityResolved", personaRes.resolved());
                agentMap.put("temperature", temperature);
                agentMap.put("personalityStrength", requestPersonalityStrength);
                agentMap.put("personality_strength", requestPersonalityStrength);
                agentMap.put("style", agentPersonalityRaw);
                agentMap.put("tone", agentPersonalityRaw);
                agentMap.put("knowledgeLevelKey", knowledge.key());
                agentMap.put("knowledgeLevelLabel", knowledge.resolved() ? knowledge.enumLabel() : knowledge.label());
                agentMap.put("knowledgeLevel", knowledge.resolved() ? knowledge.enumValue() : knowledge.original());
                agentMap.put("knowledge_level", knowledge.resolved() ? knowledge.enumValue() : knowledge.original());
                agentMap.put("knowledgeLevelResolved", knowledge.resolved());
                agentMap.put("customInstruction", agentCustomInstruction);
                agentMap.put("custom_instruction", agentCustomInstruction);
                agentMap.put("persona", persona);
                agentMap.put("goal", agent.getGoal());
                return agentMap;
        }

        private static String firstNonBlankStatic(String... values) {
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

        // ── 성격(personality) 정규화 — 프론트 공통 7종과 동일 매핑 ──────────────────────
        // 임의 입력(정규 key/한글 라벨/레거시 라벨)을 canonical key로 통일하고 temperature를 유도한다.
        private static final Map<String, String> PERSONALITY_KEY_MAP = new HashMap<>();
        private static final Map<String, Double> PERSONALITY_TEMP = new HashMap<>();
        static {
                String[][] legacy = {
                        {"기본", "default"}, {"기본값", "default"}, {"차분하게", "default"}, {"calm", "default"},
                        {"전문적으로", "professional"}, {"전문적", "professional"}, {"professional", "professional"},
                        {"친근하게", "friendly"}, {"친근함", "friendly"}, {"friendly", "friendly"},
                        {"솔직하게", "honest"}, {"솔직함", "honest"}, {"정직하게", "honest"}, {"honest", "honest"},
                        {"유머러스하게", "unique"}, {"독특함", "unique"}, {"humorous", "unique"}, {"creative", "unique"},
                        {"효율적", "efficient"}, {"간결하게", "efficient"}, {"concise", "efficient"}, {"efficient", "efficient"},
                        {"냉철하게", "cynical"}, {"냉소적", "cynical"}, {"비판적으로", "cynical"}, {"엄격하게", "cynical"},
                        {"strict", "cynical"}, {"cold", "cynical"}, {"sardonic", "cynical"}, {"critical", "cynical"}, {"cynical", "cynical"},
                };
                for (String[] e : legacy) PERSONALITY_KEY_MAP.put(e[0], e[1]);
                PERSONALITY_TEMP.put("default", 0.5);
                PERSONALITY_TEMP.put("professional", 0.35);
                PERSONALITY_TEMP.put("friendly", 0.65);
                PERSONALITY_TEMP.put("honest", 0.45);
                PERSONALITY_TEMP.put("unique", 0.8);
                PERSONALITY_TEMP.put("efficient", 0.25);
                PERSONALITY_TEMP.put("cynical", 0.55);
        }

        private static String personalityStyleKey(String raw) {
                if (raw == null || raw.isBlank()) return "default";
                String v = raw.trim();
                if (PERSONALITY_TEMP.containsKey(v)) return v;
                String low = v.toLowerCase();
                if (PERSONALITY_TEMP.containsKey(low)) return low;
                String mapped = PERSONALITY_KEY_MAP.get(v);
                if (mapped == null) mapped = PERSONALITY_KEY_MAP.get(low);
                return mapped != null ? mapped : "default";
        }

        // 우선순위: 사용자가 명시 조절한 override → 성격 기본값 → 0.5. 0.0~1.2로 clamp.
        private static double personalityTemperature(String rawOrKey, Double override) {
                double t;
                if (override != null && Double.isFinite(override)) {
                        t = override;
                } else {
                        Double base = PERSONALITY_TEMP.get(personalityStyleKey(rawOrKey));
                        t = base != null ? base : 0.5;
                }
                return Math.min(1.2, Math.max(0.0, t));
        }

        /**
         * 학습자 수준(지식수준)을 표준 enum으로 통일한다: INTRO|BACHELOR|MASTER|DOCTOR|EXPERT.
         * 한국어("입문 수준"/"학사 수준"…), 영문(beginner/bachelor…), enum 입력을 모두 호환한다.
         * 빈 입력은 ""로 돌려 firstNonBlank 폴백 체인을 깨지 않는다. 알 수 없는 비공백 값은 BACHELOR로 본다.
         * ai07 FastAPI로는 항상 이 enum 값을 보내 수준별 라우팅이 일관되게 동작하도록 한다.
         */
        private static String normalizeKnowledgeLevel(String raw) {
                if (raw == null) {
                        return "";
                }
                String v = raw.trim();
                if (v.isEmpty()) {
                        return "";
                }
                String low = v.toLowerCase();
                if (v.contains("입문") || low.contains("intro") || low.contains("beginner") || low.contains("basic")) {
                        return "INTRO";
                }
                if (v.contains("학사") || v.contains("학부") || low.contains("bachelor") || low.contains("undergrad")) {
                        return "BACHELOR";
                }
                if (v.contains("석사") || low.contains("master")) {
                        return "MASTER";
                }
                if (v.contains("박사") || low.contains("doctor") || low.contains("phd") || low.contains("ph.d")) {
                        return "DOCTOR";
                }
                if (v.contains("전문가") || low.contains("expert")) {
                        return "EXPERT";
                }
                switch (v.toUpperCase()) {
                        case "INTRO":
                        case "BACHELOR":
                        case "MASTER":
                        case "DOCTOR":
                        case "EXPERT":
                                return v.toUpperCase();
                        default:
                                return "BACHELOR";
                }
        }

        /** enum 학습자 수준 → 한국어 라벨(프론트 표시/ai07 호환용). */
        private static String knowledgeLevelLabel(String enumValue) {
                if (enumValue == null) {
                        return "";
                }
                switch (enumValue.toUpperCase()) {
                        case "INTRO":    return "입문 수준";
                        case "BACHELOR": return "학사 수준";
                        case "MASTER":   return "석사 수준";
                        case "DOCTOR":   return "박사 수준";
                        case "EXPERT":   return "전문가 수준";
                        default:         return enumValue;
                }
        }

        private Boolean asBoolean(Object value) {
                if (value instanceof Boolean) {
                        return (Boolean) value;
                }
                if (value != null) {
                        String s = String.valueOf(value).trim();
                        if (s.equalsIgnoreCase("true")) return Boolean.TRUE;
                        if (s.equalsIgnoreCase("false")) return Boolean.FALSE;
                }
                return null;
        }

        @SuppressWarnings("unchecked")
        private List<Object> asObjectList(Object value) {
                return value instanceof List ? (List<Object>) value : null;
        }

        private String strOrNull(Object value) {
                return value == null ? null : String.valueOf(value);
        }

        /**
         * ai07 응답(message/answer map)에서 수준·길이·도구 metadata를 패스스루로 담아 AgentReply를 만든다.
         * metadata가 없으면 null로 두되, actualChars/knowledgeLevel은 최대한 채운다(EC2 측 확인용).
         */
        private ChatDTO.AgentReply buildReplyWithMeta(Long agentId, String agentName, String answer,
                        Map<String, Object> src, String fallbackLevel) {
                if (src == null) {
                        src = java.util.Collections.emptyMap();
                }
                String level = normalizeKnowledgeLevel(firstNonBlank(
                                strOrNull(src.get("knowledgeLevel")),
                                strOrNull(src.get("knowledge_level")),
                                fallbackLevel));
                Integer actual = asInteger(src.get("actualChars"));
                if (actual == null) {
                        actual = answer != null ? answer.length() : 0;
                }
                return ChatDTO.AgentReply.builder()
                                .agentId(agentId)
                                .agentName(agentName)
                                .answer(answer)
                                .knowledgeLevel(level.isEmpty() ? null : level)
                                .knowledgeLevelLabel(level.isEmpty() ? null : knowledgeLevelLabel(level))
                                .minChars(asInteger(src.get("minChars")))
                                .actualChars(actual)
                                .lengthSatisfied(asBoolean(src.get("lengthSatisfied")))
                                .toolsUsed(asObjectList(src.get("toolsUsed")))
                                .toolsFailed(asObjectList(src.get("toolsFailed")))
                                .qualityChecked(asBoolean(src.get("qualityChecked")))
                                .build();
        }

        /**
         * 모드 전용 응답(all_complete / non-stream JSON)에서 새로고침 후 복원에 필요한 구조화 payload 만 골라 processSteps 맵을 만든다.
         *  · 토론: debateStages(+final conclusion 단계), debateResult, debateStrength, topic, debateParticipants
         *  · 소크라테스: socraticSteps, questionIntensity/hintPolicy, sessionId
         *  · 상황극: simulationStages, choices, scenarioType/difficulty/choiceCount, sessionId
         * 구조화 필드가 하나도 없으면 null(기본 모드는 기존 processSteps 규칙 그대로).
         */
        static Map<String, Object> structuredProcessSteps(Map<String, Object> resp) {
                if (resp == null) {
                        return null;
                }
                List<?> debateStages = resp.get("debateStages") instanceof List<?> l && !l.isEmpty() ? l : null;
                List<?> socraticSteps = resp.get("socraticSteps") instanceof List<?> l && !l.isEmpty() ? l : null;
                List<?> simulationStages = resp.get("simulationStages") instanceof List<?> l && !l.isEmpty() ? l : null;
                if (debateStages == null && socraticSteps == null && simulationStages == null) {
                        return null;
                }
                Map<String, Object> ps = new LinkedHashMap<>();
                String mode = resp.get("learningMode") != null ? String.valueOf(resp.get("learningMode"))
                                : (resp.get("mode") != null ? String.valueOf(resp.get("mode")) : null);
                if (debateStages != null) {
                        ps.put("mode", mode != null ? mode : "debate");
                        ps.put("learningMode", mode != null ? mode : "debate");
                        ps.put("debateStages", debateStages);
                        Map<String, Object> cfg = new LinkedHashMap<>();
                        if (resp.get("debateConfig") instanceof Map<?, ?> dc) {
                                for (Map.Entry<?, ?> e : dc.entrySet()) {
                                        cfg.put(String.valueOf(e.getKey()), e.getValue());
                                }
                        }
                        if (resp.get("debateStrength") != null) {
                                cfg.putIfAbsent("debateStrength", resp.get("debateStrength"));
                        }
                        if (!cfg.isEmpty()) {
                                ps.put("debateConfig", cfg);
                        }
                        putIfPresent(ps, resp, "debateResult");
                        putIfPresent(ps, resp, "debateParticipants");
                        putIfPresent(ps, resp, "topic");
                } else if (socraticSteps != null) {
                        ps.put("mode", mode != null ? mode : "socratic");
                        ps.put("learningMode", mode != null ? mode : "socratic");
                        ps.put("socraticSteps", socraticSteps);
                        Map<String, Object> cfg = new LinkedHashMap<>();
                        if (resp.get("socraticConfig") instanceof Map<?, ?> sc) {
                                for (Map.Entry<?, ?> e : sc.entrySet()) {
                                        cfg.put(String.valueOf(e.getKey()), e.getValue());
                                }
                        }
                        if (resp.get("questionIntensity") != null) {
                                cfg.putIfAbsent("questionIntensity", resp.get("questionIntensity"));
                        }
                        if (resp.get("hintPolicy") != null) {
                                cfg.putIfAbsent("hintPolicy", resp.get("hintPolicy"));
                        }
                        if (!cfg.isEmpty()) {
                                ps.put("socraticConfig", cfg);
                        }
                } else {
                        ps.put("mode", mode != null ? mode : "simulation");
                        ps.put("learningMode", mode != null ? mode : "simulation");
                        ps.put("simulationStages", simulationStages);
                        Map<String, Object> cfg = new LinkedHashMap<>();
                        if (resp.get("simulationConfig") instanceof Map<?, ?> sc) {
                                for (Map.Entry<?, ?> e : sc.entrySet()) {
                                        cfg.put(String.valueOf(e.getKey()), e.getValue());
                                }
                        }
                        for (String k : new String[] {"scenarioType", "difficulty", "choiceCount"}) {
                                if (resp.get(k) != null) {
                                        cfg.putIfAbsent(k, resp.get(k));
                                }
                        }
                        if (!cfg.isEmpty()) {
                                ps.put("simulationConfig", cfg);
                        }
                        putIfPresent(ps, resp, "choices");
                }
                putIfPresent(ps, resp, "sessionId");
                putIfPresent(ps, resp, "turnIndex");
                return ps;
        }

        private static void putIfPresent(Map<String, Object> target, Map<String, Object> src, String key) {
                Object v = src.get(key);
                if (v != null) {
                        target.put(key, v);
                }
        }

        /** 방에 저장된 모드 전용 설정(mode_config_json) → Map. 없으면 빈 맵. */
        private Map<String, Object> parseRoomModeConfig(AgentChatRoom room) {
                String json = room != null ? room.getModeConfigJson() : null;
                if (json == null || json.isBlank()) return new LinkedHashMap<>();
                try {
                        Map<String, Object> m = objectMapper.readValue(json, new TypeReference<Map<String, Object>>() {});
                        return m != null ? m : new LinkedHashMap<>();
                } catch (Exception e) {
                        log.warn("[CHAT MODE] roomId={} mode_config_json 파싱 실패: {}", room.getId(), e.getMessage());
                        return new LinkedHashMap<>();
                }
        }

        @SuppressWarnings("unchecked")
        private static Map<String, Object> subMap(Map<String, Object> m, String key) {
                Object v = m == null ? null : m.get(key);
                return v instanceof Map ? (Map<String, Object>) v : null;
        }

        @SuppressWarnings("unchecked")
        private static Map<String, Object> asMap(Map<String, Object> m, String key) {
                Object v = m == null ? null : m.get(key);
                return v instanceof Map ? (Map<String, Object>) v : null;
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

        private static String nullToEmpty(String value) {
                return value == null ? "" : value;
        }

        private static String extractPersonaTag(String persona, String tagName) {
                if (persona == null || persona.isBlank()) {
                        return null;
                }
                Pattern pattern = Pattern.compile("\\[" + Pattern.quote(tagName) + ":\\s*([^\\]]+)\\]");
                Matcher matcher = pattern.matcher(persona);
                return matcher.find() ? matcher.group(1).trim() : null;
        }

        private static String stripPersonaTags(String persona) {
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
