package com.studybridge.api.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.dto.RedisChatMessage;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.IntentRouterService;
import com.studybridge.api.entity.GroupChatMessage;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.repository.GroupChatMessageRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@RestController
@RequestMapping("/api/groups")
@RequiredArgsConstructor
@Slf4j
public class GroupStudyStreamController {

    private final GroupChatMessageRepository groupChatMessageRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final UserRepository userRepository;
    private final WebClient fastApiWebClient;
    private final ObjectMapper objectMapper;
    private final IntentRouterService intentRouterService;

    @GetMapping(value = "/{groupId}/chats/history", produces = MediaType.APPLICATION_JSON_VALUE)
    public org.springframework.http.ResponseEntity<List<Map<String, Object>>> getChatHistory(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId) {
        
        boolean isMember = groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupId, userDetails.getId(), GroupStudyMemberStatus.JOINED);
        if (!isMember) {
            return org.springframework.http.ResponseEntity.status(403).build();
        }

        List<GroupChatMessage> historyList = groupChatMessageRepository.findTop100ByGroupStudyIdOrderByCreatedAtDesc(groupId);
        java.util.Collections.reverse(historyList);
        
        List<Map<String, Object>> response = historyList.stream().map(h -> {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("id", h.getId());
            map.put("senderName", h.getSenderName());
            map.put("senderId", h.getSenderId());
            map.put("content", h.getContent());
            map.put("isAi", "ASSISTANT".equals(h.getRole()));
            map.put("isAiQuery", "USER_AI".equals(h.getRole()));
            return map;
        }).toList();
        
        return org.springframework.http.ResponseEntity.ok(response);
    }

    @PostMapping(value = "/{groupId}/chats/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> streamGroupChat(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestBody ChatDTO.MultiChatRequest request,
            HttpServletResponse response) {

        // SSE 버퍼링 방지 헤더(Nginx/프록시/브라우저). Content-Type은 produces로 text/event-stream.
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-cache, no-transform");

        log.info("SSE Chat Stream requested for groupId={}, userId={}", groupId, userDetails.getId());

        // 1. 해당 그룹스터디방의 정식 멤버인지 검증
        boolean isMember = groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupId, userDetails.getId(), GroupStudyMemberStatus.JOINED);
        if (!isMember) {
            log.warn("Access Denied: User {} is not a member of group {}", userDetails.getId(), groupId);
            return Flux.error(new AccessDeniedException("해당 그룹스터디방의 정식 멤버만 이용 가능합니다."));
        }

        // 2. 사용자 정보 조회 (이름 획득용)
        User user = userRepository.findById(userDetails.getId())
                .orElseThrow(() -> new NoSuchElementException("사용자를 찾을 수 없습니다."));
        String displayName = user.getDisplayName() != null ? user.getDisplayName() : "사용자";

        // 3. DB에서 최근 100개 대화 내역 조회 (시간순 정렬)
        List<GroupChatMessage> historyList = groupChatMessageRepository.findTop100ByGroupStudyIdOrderByCreatedAtDesc(groupId);
        java.util.Collections.reverse(historyList);
        List<Map<String, Object>> previousAnswers = historyList.stream()
                .map(h -> {
                    Map<String, Object> map = new LinkedHashMap<>();
                    map.put("agentName", h.getSenderName());
                    map.put("answer", h.getContent());
                    map.put("role", h.getRole());
                    map.put("agentId", h.getSenderId());
                    return map;
                })
                .toList();

        // 4. 그룹스터디 AI 봇 정리 — 슬래시 명령어 2차 파싱 + 일정봇 방어 + runMode별 agents 구성
        String message = request.getMessage() != null ? request.getMessage().trim() : "";
        String rawMessage = request.getRawMessage() != null ? request.getRawMessage().trim() : message;
        String botType = request.getBotType();
        String runMode = request.getRunMode();

        // 4-1. 서버측 2차 슬래시 파싱 (rawMessage 우선)
        SlashResult slash = parseSlashCommand(rawMessage);
        if (slash.unsupported) {
            return Flux.just(errorEvent(
                    "지원하지 않는 AI 봇입니다. 사용 가능 명령어: /요약봇, /퀴즈봇, /검색봇"));
        }
        if (slash.matched) {
            botType = slash.botType;
            runMode = "single";
            message = slash.message;
        }

        // 4-2. 일정봇 계열 방어 (schedule_bot/calendar_bot/todo_bot, ScheduleAgent 등)
        if (isForbiddenBot(botType, request.getAgentName())) {
            return Flux.just(errorEvent(
                    "지원하지 않는 AI 봇입니다. 사용 가능: /요약봇, /퀴즈봇, /검색봇"));
        }
        if (request.getAgents() != null) {
            for (ChatDTO.RequestAgent a : request.getAgents()) {
                if (isForbiddenBot(a.getBotType(), a.getName())) {
                    return Flux.just(errorEvent("지원하지 않는 AI 봇입니다."));
                }
            }
        }

        // 4-3. message가 비어있으면 안내
        if (message.isEmpty()) {
            return Flux.just(errorEvent(emptyMessageGuide(botType)));
        }

        // ── Intent Router 게이트 (surface=group_study_chat) ─────────────────────────
        // terminal이면 단일 라우팅 이벤트로 종료, WARN이면 notice를 스트림 앞에 붙이고 기존 그룹 AI 흐름 진행.
        // 라우터 비활성/실패면 PROCEED → 아래 기존 로직 그대로(무손상).
        IntentDTO.RouteResult route = intentRouterService.route(
                message, "group_study_chat", Map.of("groupId", groupId));
        if (route.isTerminal()) {
            return Flux.just(routeEvent(route.actionName(), route.userMessage()));
        }
        if (route.isPipeline()) {
            // 그룹 채팅엔 자료(materialId) 컨텍스트가 없어 기준이 모호 → 되묻기로 안전 처리.
            return Flux.just(routeEvent("CLARIFY", "어떤 자료를 기준으로 만들까요? 자료를 먼저 선택해 주세요."));
        }
        final ServerSentEvent<String> warnNotice = route.isWarn()
                ? routeEvent("WARN", route.userMessage()) : null;

        // 4-4. 실행 모드 분기
        //  - 슬래시 명령어(/요약봇·/퀴즈봇·/검색봇)가 매칭되면 무조건 group_study_ai 봇 모드.
        //  - 그 외에 프론트가 토론 모드(debate/토론 ...)를
        //    요청하면 FastAPI debate 파이프라인을 타게 한다. (group_study_ai로 덮어쓰지 않는다.)
        String requestedMode = request.getMode() != null ? request.getMode().trim() : "";
        final boolean isDebateMode = !slash.matched && isDebateRequest(request.getLearningMode(), requestedMode);
        // 소크라테스: learningMode 또는 mode 기준. 슬래시/토론/상황극이 아닌 경우만.
        final boolean isSocraticMode = !slash.matched && !isDebateMode
                && (isSocraticRequest(request.getLearningMode()) || isSocraticRequest(requestedMode));
        // 상황극: debate/socratic/basic과 섞지 않고 별도 simulation 파이프라인으로 보낸다.
        final boolean isSimulationMode = !slash.matched && !isDebateMode && !isSocraticMode
                && (isSimulationRequest(request.getLearningMode()) || isSimulationRequest(requestedMode));
        // 검증/협업: ai07 multi-chat/stream의 1차→검증→상호피드백 구조를 그대로 사용한다.
        final boolean isCollabMode = !slash.matched && !isDebateMode && !isSocraticMode && !isSimulationMode
                && (isCollaborationRequest(request.getLearningMode()) || isCollaborationRequest(requestedMode));
        final String collabMode = !isCollabMode ? null
                : (isValidationValue(request.getLearningMode()) || isValidationValue(requestedMode)
                        ? "validation" : "collaboration");

        // 4-5. agents 구성
        // 사용자가 그룹스터디 AI 봇을 직접 설정해 보냈는지 여부 (슬래시 봇 명령이 아닐 때만).
        //  설정 봇이 있으면 하드코딩 3봇(요약/퀴즈/검색)으로 덮어쓰지 않고 사용자 봇을 그대로 사용한다.
        final boolean hasCustomGroupAgents = !slash.matched
                && !isDebateMode && !isSocraticMode && !isSimulationMode
                && request.getAgents() != null && !request.getAgents().isEmpty();
        List<Map<String, Object>> agentsList;
        if (isDebateMode || isSocraticMode || isSimulationMode) {
            // 토론/소크라테스/상황극: 봇 3종으로 덮어쓰지 않는다.
            //  사용자가 만든 에이전트가 있으면 그대로, 없으면 기본 에이전트 3명을 만든다. (역할 고정은 FastAPI가 수행)
            agentsList = buildDebateAgents(request.getAgents());
        } else if (hasCustomGroupAgents) {
            // 사용자 설정 봇(이름/성격/지식수준/요구사항)을 그대로 FastAPI 멀티에이전트로 전달한다.
            agentsList = buildCustomGroupAgents(request.getAgents());
        } else if (isCollabMode) {
            // 검증/협업인데 사용자 봇이 없으면 기본 3봇으로 협업/검증을 진행한다(하드코딩 봇으로 '덮어쓰는' 케이스 아님).
            agentsList = List.of(
                    botAgentMap("search_bot"),
                    botAgentMap("summary_bot"),
                    botAgentMap("quiz_bot")
            );
        } else if ("all_bots".equalsIgnoreCase(runMode)) {
            // 전체 토론: 검색봇 → 요약봇 → 퀴즈봇 순서
            agentsList = List.of(
                    botAgentMap("search_bot"),
                    botAgentMap("summary_bot"),
                    botAgentMap("quiz_bot")
            );
        } else if (botType != null && BOT_REGISTRY.containsKey(botType)) {
            // single: 선택한 봇 1개
            agentsList = List.of(botAgentMap(botType));
        } else {
            // 사용자의 요청에 따라 다중 에이전트를 없애고, 일반 AI 튜터 1명으로 단순화
            Map<String, Object> aiTutor = new LinkedHashMap<>();
            aiTutor.put("id", 1);
            aiTutor.put("agentId", 1);
            aiTutor.put("name", "AI 튜터");
            aiTutor.put("role", "학습 도우미");
            aiTutor.put("personality", "친절_설명형");
            aiTutor.put("knowledgeLevel", "학사");
            agentsList = List.of(aiTutor);
        }

        final String effectiveMessage = message;

        // 4-6. FastAPI 요청 페이로드 구성
        Map<String, Object> fastApiPayload = new LinkedHashMap<>();
        fastApiPayload.put("message", effectiveMessage);
        if (isDebateMode) {
            // 토론 모드: mode=debate, 봇 전용 runMode/showFinalSynthesis는 보내지 않는다.
            fastApiPayload.put("mode", "debate");
            fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 3);
        } else if (isSocraticMode) {
            // 소크라테스 모드: mode=socratic + socraticConfig/userAttempt 패스스루.
            fastApiPayload.put("mode", "socratic");
            fastApiPayload.put("learningMode", "socratic");
            fastApiPayload.put("rounds", 1);
            fastApiPayload.put("socraticConfig", request.getSocraticConfig());
            fastApiPayload.put("userAttempt", firstNonBlank(request.getUserAttempt(), effectiveMessage));
        } else if (isSimulationMode) {
            // 상황극 모드: mode=simulation + simulationConfig 패스스루.
            fastApiPayload.put("mode", "simulation");
            fastApiPayload.put("learningMode", "simulation");
            fastApiPayload.put("rounds", 1);
            fastApiPayload.put("simulationConfig", request.getSimulationConfig());
        } else if (isCollabMode) {
            // 검증/협업: ai07이 FIRST_ANSWER → VALIDATION → PEER_FEEDBACK 구조로 응답한다. 사용자 봇은 그대로 유지.
            fastApiPayload.put("mode", collabMode);          // validation | collaboration
            fastApiPayload.put("learningMode", collabMode);
            fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 3);
            fastApiPayload.put("showFinalSynthesis", false);
        } else if (hasCustomGroupAgents) {
            // 사용자 설정 봇: 일반 멀티에이전트 토론 경로로 보내 persona/지식수준/요구사항이 반영되게 한다.
            fastApiPayload.put("mode", "multi_agent_discussion");
            fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 1);
            fastApiPayload.put("showFinalSynthesis", false);
        } else if (botType != null && BOT_REGISTRY.containsKey(botType)) {
            fastApiPayload.put("mode", "group_study_ai");
            fastApiPayload.put("runMode", "single");
            fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 1);
            fastApiPayload.put("showFinalSynthesis", false);
        } else {
            // 일반 AI 튜터 단일 응답
            fastApiPayload.put("mode", "default");
            fastApiPayload.put("rounds", 1);
            fastApiPayload.put("showFinalSynthesis", false);
        }
        fastApiPayload.put("previousAnswers", previousAnswers);
        fastApiPayload.put("targetAgentId", request.getTargetAgentId());
        fastApiPayload.put("agents", agentsList);
        log.info("[GROUP CHAT ROUTE] requestedMode='{}' learningMode='{}' resolved mode={} fastapiLearningMode={} isDebate={} isCollab={} customAgents={} agents.size={}",
                requestedMode, request.getLearningMode(), fastApiPayload.get("mode"),
                fastApiPayload.get("learningMode"), isDebateMode, isCollabMode, hasCustomGroupAgents, agentsList.size());
        // 사용자가 그룹스터디에서 설정한 봇의 성격/지식수준이 FastAPI 페이로드까지 도달하는지 검증용 로그.
        // 질문 본문/비밀값은 출력하지 않고 설정값만 남긴다(브라우저 요청 body 와 1:1 비교용). ChatService [AGENT i] 패턴과 동일.
        for (int i = 0; i < agentsList.size(); i++) {
            Map<String, Object> a = agentsList.get(i);
            log.info("[GROUP AGENT {}] name={} personality={} knowledgeLevel={} customInstructionPresent={}",
                    i + 1, a.get("name"), a.get("personality"), a.get("knowledgeLevel"),
                    a.get("customInstruction") != null && !String.valueOf(a.get("customInstruction")).isBlank());
        }

        // 스트림 누적 상태 저장 객체
        Map<String, StringBuilder> agentReplies = new ConcurrentHashMap<>();

        // 5. FastAPI SSE를 그대로 중계한다. agent_answer/debate_section/... 이벤트가 도착하는 즉시 프론트로 전달된다.
        Flux<ServerSentEvent<String>> upstream = fastApiWebClient.post()
                .uri("/api/ai/multi-chat/stream")
                .bodyValue(fastApiPayload)
                .retrieve()
                .bodyToFlux(new org.springframework.core.ParameterizedTypeReference<ServerSentEvent<String>>() {})
                .map(ev -> {
                    String event = ev.event() != null ? ev.event() : "message";
                    String data = ev.data() != null ? ev.data() : "{}";
                    accumulateFastApiStreamEvent(event, data, agentReplies);
                    return ServerSentEvent.<String>builder()
                            .event(event)
                            .data(data)
                            .build();
                })
                .doOnComplete(() -> {
                    log.info("SSE Stream completed for groupId={}. Persisting discussion to DB.", groupId);
                    persistGroupStreamMessages(groupId, displayName, effectiveMessage, agentsList, agentReplies, String.valueOf(userDetails.getId()));
                })
                .doOnError(err -> log.error("Error during FastAPI chat streaming for groupId={}", groupId, err))
                .onErrorResume(err -> fastApiWebClient.post()
                        .uri("/api/ai/multi-chat")
                        .bodyValue(fastApiPayload)
                        .retrieve()
                        .bodyToMono(String.class)
                        .map(data -> {
                            String body = data != null ? data : "{}";
                            accumulateFastApiStreamEvent("all_complete", body, agentReplies);
                            persistGroupStreamMessages(groupId, displayName, effectiveMessage, agentsList, agentReplies, String.valueOf(userDetails.getId()));
                            return ServerSentEvent.<String>builder()
                                    .event("all_complete")
                                    .data(body)
                                    .build();
                        })
                        .flux()
                        .onErrorResume(fallbackErr -> Flux.just(
                                ServerSentEvent.<String>builder()
                                        .event("error")
                                        .data("{\"errorMessage\":\"AI 스트리밍 대화 중 오류가 발생했습니다. 다시 시도해 주세요.\"}")
                                        .build()
                        )))
                // cache(): upstream(원격 HTTP)을 1회만 구독하고, 하트비트 종료 신호용으로 재사용한다.
                .cache();

        // keep-alive 하트비트(SSE 주석 ':hb'). upstream 완료 시 takeUntilOther로 함께 종료된다.
        Flux<ServerSentEvent<String>> heartbeat = Flux.interval(Duration.ofSeconds(heartbeatSeconds()))
                .map(i -> ServerSentEvent.<String>builder().comment("hb").build());

        Flux<ServerSentEvent<String>> stream = upstream.mergeWith(heartbeat).takeUntilOther(upstream.then());
        // WARN: 경고 notice를 스트림 맨 앞에 1회 붙인다(기존 토큰 흐름과 중복되지 않음).
        return warnNotice != null ? Flux.concat(Flux.just(warnNotice), stream) : stream;
    }

    // SSE 하트비트 간격(초). 하드코딩 금지 — env AI_SSE_HEARTBEAT_SECONDS, 기본 12초.
    private long heartbeatSeconds() {
        try {
            String v = System.getenv("AI_SSE_HEARTBEAT_SECONDS");
            if (v != null && !v.isBlank()) {
                long parsed = Long.parseLong(v.trim());
                if (parsed > 0) {
                    return parsed;
                }
            }
        } catch (NumberFormatException ignored) {
        }
        return 12L;
    }


    private void persistGroupStreamMessages(Long groupId, String displayName, String effectiveMessage,
                                            List<Map<String, Object>> agentsList,
                                            Map<String, StringBuilder> agentReplies, String userId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId).orElse(null);
        if (groupStudy == null) return;

        groupChatMessageRepository.save(GroupChatMessage.builder()
                .groupStudy(groupStudy)
                .senderName(displayName)
                .senderId(userId)
                .content(effectiveMessage)
                .role("USER_AI")
                .build());

        agentReplies.forEach((agentName, replyBuilder) -> {
            String fullReply = replyBuilder.toString().trim();
            if (!fullReply.isEmpty()) {
                Long matchedAgentId = null;
                for (Map<String, Object> a : agentsList) {
                    if (agentName.equals(a.get("name"))) {
                        Object rawId = a.get("id");
                        if (rawId instanceof Number) {
                            matchedAgentId = ((Number) rawId).longValue();
                        }
                        break;
                    }
                }
                groupChatMessageRepository.save(GroupChatMessage.builder()
                        .groupStudy(groupStudy)
                        .senderName(agentName)
                        .senderId(matchedAgentId != null ? String.valueOf(matchedAgentId) : "AI_SYSTEM")
                        .content(fullReply)
                        .role("ASSISTANT")
                        .build());
            }
        });
    }

    private void accumulateFastApiStreamEvent(String event, String data, Map<String, StringBuilder> agentReplies) {
        if (data == null || data.isBlank()) return;
        try {
            JsonNode node = objectMapper.readTree(data);
            if ("agent_answer".equals(event)) {
                String name = node.has("agentName") ? node.get("agentName").asText() : "AI";
                String content = node.has("content") ? node.get("content").asText() : (node.has("answer") ? node.get("answer").asText() : "");
                if (!content.isBlank()) agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
                return;
            }
            if ("debate_section".equals(event) || "socratic_step".equals(event) || "simulation_stage".equals(event)) {
                String name = node.has("agentName") && !node.get("agentName").isNull()
                        ? node.get("agentName").asText()
                        : (node.has("role") ? node.get("role").asText() : event);
                String content = node.has("content") ? node.get("content").asText()
                        : (node.has("feedback") ? node.get("feedback").asText() : "");
                if (!content.isBlank()) agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
                return;
            }
            if ("all_complete".equals(event) && agentReplies.isEmpty()) {
                JsonNode answers = node.get("answers");
                if (answers != null && answers.isArray()) {
                    for (JsonNode answer : answers) {
                        String name = answer.has("agentName") ? answer.get("agentName").asText() : "AI";
                        String content = answer.has("answer") ? answer.get("answer").asText() : "";
                        if (!content.isBlank()) agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
                    }
                }
            }
        } catch (Exception e) {
            log.debug("FastAPI stream event 누적 생략 event={}: {}", event, e.getMessage());
        }
    }

    // ── 그룹스터디 AI 봇 레지스트리 (요약/퀴즈/검색 3종) ──────────────────────────
    //  일정봇(schedule_bot/calendar_bot/todo_bot)은 절대 등록하지 않는다.

    private record BotDef(Long id, String botType, String agentName, String displayName,
                          String emoji, String modelProvider, String goal) {}

    private static final Map<String, BotDef> BOT_REGISTRY = Map.of(
            "summary_bot", new BotDef(1L, "summary_bot", "SummaryAgent", "요약봇", "📝",
                    "qwen_ollama", "스터디 내용과 학습 자료를 핵심 개념, 키워드, 시험 포인트 중심으로 정리합니다."),
            "quiz_bot", new BotDef(2L, "quiz_bot", "QuizAgent", "퀴즈봇", "🧩",
                    "openai_gpt", "학습 내용을 바탕으로 퀴즈를 만들고 정답과 해설까지 제공합니다."),
            "search_bot", new BotDef(3L, "search_bot", "TavilyAgent", "검색봇", "🔎",
                    "openai_gpt_tavily", "웹 검색과 출처 기반 분석으로 최신 학습 정보를 보강합니다.")
    );

    // 슬래시 명령어 → botType
    private static final Map<String, String> SLASH_TO_BOT = Map.of(
            "/요약봇", "summary_bot",
            "/퀴즈봇", "quiz_bot",
            "/검색봇", "search_bot"
    );

    // 절대 허용하지 않는 봇
    private static final Set<String> FORBIDDEN_BOT_TYPES = Set.of("schedule_bot", "calendar_bot", "todo_bot");
    private static final Set<String> FORBIDDEN_AGENT_NAMES = Set.of("ScheduleAgent", "CalendarAgent", "TodoAgent");

    private static final class SlashResult {
        boolean matched;
        boolean unsupported;
        String botType;
        String message;
    }

    /** rawMessage의 슬래시 명령어를 2차 파싱한다. */
    private SlashResult parseSlashCommand(String rawMessage) {
        SlashResult r = new SlashResult();
        r.message = rawMessage != null ? rawMessage.trim() : "";
        if (r.message.isEmpty() || !r.message.startsWith("/")) {
            return r; // 명령어 없음
        }
        for (Map.Entry<String, String> e : SLASH_TO_BOT.entrySet()) {
            if (r.message.startsWith(e.getKey())) {
                r.matched = true;
                r.botType = e.getValue();
                r.message = r.message.substring(e.getKey().length()).trim();
                return r;
            }
        }
        // 지원하지 않는 슬래시 명령어 (/일정봇 등)
        r.unsupported = true;
        return r;
    }

    private boolean isForbiddenBot(String botType, String agentName) {
        if (botType != null && FORBIDDEN_BOT_TYPES.contains(botType.trim())) return true;
        return agentName != null && FORBIDDEN_AGENT_NAMES.contains(agentName.trim());
    }

    private String emptyMessageGuide(String botType) {
        if ("quiz_bot".equals(botType)) return "퀴즈로 만들 내용을 입력해주세요.";
        if ("search_bot".equals(botType)) return "검색할 주제를 입력해주세요.";
        if ("summary_bot".equals(botType)) return "요약할 내용을 입력해주세요.";
        return "질문 내용을 입력해주세요.";
    }

    /** botType → FastAPI agent payload */
    private Map<String, Object> botAgentMap(String botType) {
        BotDef def = BOT_REGISTRY.get(botType);
        if (def == null) def = BOT_REGISTRY.get("summary_bot");
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", def.id());
        map.put("agentId", def.id());
        map.put("name", def.agentName());
        map.put("botType", def.botType());
        map.put("displayName", def.displayName());
        map.put("modelProvider", def.modelProvider());
        map.put("role", def.displayName());
        map.put("personality", "전문적");
        map.put("personalityStrength", "extreme");
        map.put("style", "전문적");
        map.put("tone", "전문적");
        map.put("knowledgeLevel", "학사 수준");
        map.put("customInstruction", "");
        map.put("persona", "");
        map.put("goal", def.goal());
        return map;
    }

    // ── 토론(debate) 모드 헬퍼 ────────────────────────────────────────────────

    // 토론 모드로 간주하는 mode 값 (대소문자 무시 + 한글)
    private static final Set<String> DEBATE_MODE_ALIASES = Set.of("debate");
    private static final Set<String> DEBATE_MODE_ALIASES_KO = Set.of("토론", "토론 모드");

    /** request.mode/learningMode가 토론 계열인지 판별한다. */
    private boolean isDebateRequest(String... modes) {
        if (modes == null) return false;
        for (String mode : modes) {
            if (mode == null) continue;
            String m = mode.trim();
            if (m.isEmpty()) continue;
            if (DEBATE_MODE_ALIASES.contains(m.toLowerCase()) || DEBATE_MODE_ALIASES_KO.contains(m)) {
                return true;
            }
        }
        return false;
    }

    // 소크라테스로 간주하는 값 (한글 별칭 포함).
    private static final Set<String> SOCRATIC_MODE_ALIASES = Set.of("socratic", "소크라테스", "소크라테스 모드");
    private static final Set<String> SIMULATION_MODE_ALIASES = Set.of(
            "simulation", "상황극", "상황극 모드", "시뮬레이션", "시뮬레이션 모드");

    /** mode/learningMode가 소크라테스 계열인지 판별한다. */
    private boolean isSocraticRequest(String mode) {
        if (mode == null) return false;
        String m = mode.trim();
        if (m.isEmpty()) return false;
        return SOCRATIC_MODE_ALIASES.contains(m.toLowerCase()) || SOCRATIC_MODE_ALIASES.contains(m);
    }

    private boolean isSimulationRequest(String mode) {
        if (mode == null) return false;
        String m = mode.trim();
        if (m.isEmpty()) return false;
        return SIMULATION_MODE_ALIASES.contains(m.toLowerCase()) || SIMULATION_MODE_ALIASES.contains(m);
    }

    // 검증/협업 모드 별칭. 둘 다 ai07 multi-chat/stream(1차→검증→상호피드백)으로 relay된다.
    private static final Set<String> VALIDATION_MODE_ALIASES = Set.of("validation", "검증", "검증 모드");
    private static final Set<String> COLLABORATION_MODE_ALIASES = Set.of(
            "collaboration", "collaborative", "협업", "협업 모드");

    /** mode/learningMode가 검증 계열인지 판별한다. */
    private boolean isValidationValue(String mode) {
        if (mode == null) return false;
        String m = mode.trim();
        if (m.isEmpty()) return false;
        return VALIDATION_MODE_ALIASES.contains(m.toLowerCase()) || VALIDATION_MODE_ALIASES.contains(m);
    }

    /** mode/learningMode가 검증 또는 협업 계열인지 판별한다(둘 다 relay 대상). */
    private boolean isCollaborationRequest(String mode) {
        if (mode == null) return false;
        String m = mode.trim();
        if (m.isEmpty()) return false;
        String lower = m.toLowerCase();
        return VALIDATION_MODE_ALIASES.contains(lower) || VALIDATION_MODE_ALIASES.contains(m)
                || COLLABORATION_MODE_ALIASES.contains(lower) || COLLABORATION_MODE_ALIASES.contains(m);
    }

    /**
     * 토론 모드 agents 구성.
     *  1) 사용자가 만든 토론 에이전트가 있으면 그대로 FastAPI 형식으로 넘긴다.
     *  2) 없으면 토론용 기본 에이전트 3명(정의/예시/비판)을 만든다.
     * 봇 3종(요약/퀴즈/검색)은 절대 기본값으로 쓰지 않는다.
     */
    private List<Map<String, Object>> buildDebateAgents(List<ChatDTO.RequestAgent> reqAgents) {
        if (reqAgents != null && !reqAgents.isEmpty()) {
            List<Map<String, Object>> out = new ArrayList<>();
            int idx = 1;
            for (ChatDTO.RequestAgent a : reqAgents) {
                out.add(debateAgentMap(a, idx++));
            }
            return out;
        }
        // 토론용 기본 에이전트 3명
        return List.of(
                defaultDebateAgent(1, "정의·원리 토론자", "논리적",
                        "이 주제의 핵심 정의와 원리를 명확히 세우고, 개념의 본질을 기준으로 주장한다."),
                defaultDebateAgent(2, "예시·응용 토론자", "친근한",
                        "실제 사용 예시와 응용 사례를 들어 개념이 왜 중요한지 설득한다."),
                defaultDebateAgent(3, "오개념·비판 토론자", "비판적",
                        "사람들이 흔히 틀리는 오개념과 한계, 반례를 지적하며 다른 토론자의 주장을 비판적으로 검토한다.")
        );
    }

    private Map<String, Object> defaultDebateAgent(int idx, String name, String personality, String instruction) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", -idx);
        m.put("agentId", -idx);
        m.put("name", name);
        m.put("role", "debater");
        m.put("personality", personality);
        m.put("personalityStrength", "moderate");
        m.put("knowledgeLevel", "학사");
        m.put("customInstruction", instruction);
        return m;
    }

    private Map<String, Object> debateAgentMap(ChatDTO.RequestAgent a, int idx) {
        Map<String, Object> m = new LinkedHashMap<>();
        Long id = parseLongOrNull(a.getAgentId() != null ? a.getAgentId() : a.getId());
        m.put("id", id != null ? id : -idx);
        m.put("agentId", id != null ? id : -idx);
        m.put("name", firstNonBlank(a.getName(), "토론자 " + idx));
        m.put("role", firstNonBlank(a.getRole(), "debater"));
        m.put("personality", firstNonBlank(a.getPersonality(), a.getStyle(), a.getTone(), "논리적"));
        m.put("personalityStrength", firstNonBlank(a.getPersonalityStrength(), a.getPersonality_strength(), "moderate"));
        m.put("style", a.getStyle());
        m.put("tone", a.getTone());
        m.put("knowledgeLevel", firstNonBlank(a.getKnowledgeLevel(), a.getKnowledge_level(), "학사"));
        m.put("customInstruction", firstNonBlank(a.getCustomInstruction(), a.getCustom_instruction(), ""));
        m.put("persona", a.getPersona());
        return m;
    }

    /**
     * 사용자가 그룹스터디에서 직접 설정한 AI 봇을 FastAPI 멀티에이전트 형식으로 변환한다.
     *  이름/성격/지식수준/요구사항(customInstruction)을 유실 없이 전달하며, 하드코딩 기본봇으로 덮어쓰지 않는다.
     */
    private List<Map<String, Object>> buildCustomGroupAgents(List<ChatDTO.RequestAgent> reqAgents) {
        List<Map<String, Object>> out = new ArrayList<>();
        int idx = 1;
        for (ChatDTO.RequestAgent a : reqAgents) {
            Map<String, Object> m = new LinkedHashMap<>();
            Long id = parseLongOrNull(a.getAgentId() != null ? a.getAgentId() : a.getId());
            m.put("id", id != null ? id : idx);
            m.put("agentId", id != null ? id : idx);
            m.put("name", firstNonBlank(a.getName(), "AI 도우미 " + idx));
            m.put("role", firstNonBlank(a.getRole(), "AI 학습 도우미"));
            m.put("personality", firstNonBlank(a.getPersonality(), a.getStyle(), a.getTone(), "전문적"));
            m.put("personalityStrength",
                    firstNonBlank(a.getPersonalityStrength(), a.getPersonality_strength(), "moderate"));
            m.put("style", a.getStyle());
            m.put("tone", a.getTone());
            m.put("knowledgeLevel", firstNonBlank(a.getKnowledgeLevel(), a.getKnowledge_level(), "학사 수준"));
            m.put("customInstruction", firstNonBlank(a.getCustomInstruction(), a.getCustom_instruction(), ""));
            m.put("persona", a.getPersona());
            out.add(m);
            idx++;
        }
        return out;
    }

    /**
     * FastAPI debate 응답(initialAnswers/peerFeedbacks/revisedAnswers/debateSummary)을
     * debate_section SSE 청크로 변환해 chunks에 추가한다.
     * revisedAnswers(없으면 initialAnswers)는 Redis 영속화를 위해 agentReplies에 누적한다.
     */
    private void buildDebateSectionChunks(JsonNode responseNode, List<String> chunks,
                                          Map<String, StringBuilder> agentReplies) {
        JsonNode stages = responseNode.get("debateStages");
        JsonNode debateConfig = responseNode.get("debateConfig");

        // 1) 구조화 토론(debateStages)이 있으면 단계별 debate_section 이벤트로 전송한다.
        //    stageType/stageTitle/side/role/agentIndex/agentName/content/debateConfig를 유실하지 않는다.
        if (stages != null && stages.isArray() && stages.size() > 0) {
            for (JsonNode stage : stages) {
                chunks.add(debateStageChunk(stage, debateConfig));
                // 영속화용: 본문이 있는 단계를 에이전트(또는 단계 제목)별로 누적
                String name = stage.has("agentName") && !stage.get("agentName").isNull()
                        ? stage.get("agentName").asText()
                        : (stage.has("stageTitle") ? stage.get("stageTitle").asText() : "토론");
                String content = stage.has("content") ? stage.get("content").asText() : "";
                if (!content.isEmpty()) {
                    agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
                }
            }
            log.info("토론 SSE 단계 생성(debateStages): stages={}", stages.size());
            return;
        }

        // 2) 하위 호환: debateStages가 없을 때만 변환. "1차 의견/서로 피드백/보완 답변/토론 정리" 라벨 금지.
        chunks.add(debateSectionChunk("openings", "입론", responseNode.get("initialAnswers"), null));
        chunks.add(debateSectionChunk("rebuttals", "반박", responseNode.get("peerFeedbacks"), null));

        JsonNode revised = responseNode.get("revisedAnswers");
        chunks.add(debateSectionChunk("closings", "최종 변론", revised, null));

        String summary = (responseNode.has("debateSummary") && !responseNode.get("debateSummary").isNull())
                ? responseNode.get("debateSummary").asText() : "";
        chunks.add(debateSectionChunk("judgement", "판정", null, summary));

        JsonNode persistTarget = (revised != null && revised.isArray() && revised.size() > 0)
                ? revised : responseNode.get("initialAnswers");
        if (persistTarget != null && persistTarget.isArray()) {
            for (JsonNode r : persistTarget) {
                String name = r.has("displayName") ? r.get("displayName").asText()
                        : (r.has("agentName") ? r.get("agentName").asText() : "토론자");
                String ans = r.has("answer") ? r.get("answer").asText() : "";
                if (!ans.isEmpty()) {
                    agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(ans);
                }
            }
        }
        log.info("토론 SSE 섹션 생성(legacy): openings={} rebuttals={} closings={} judgement={}",
                nodeSize(responseNode.get("initialAnswers")), nodeSize(responseNode.get("peerFeedbacks")),
                nodeSize(revised), !summary.isEmpty());
    }

    /**
     * FastAPI 소크라테스 응답(socraticSteps)을 socratic_step SSE 청크로 변환해 chunks에 추가한다.
     * 본문이 있는 단계를 에이전트별로 누적해 Redis 영속화에 사용한다.
     */
    private void buildSocraticStepChunks(JsonNode responseNode, List<String> chunks,
                                         Map<String, StringBuilder> agentReplies) {
        JsonNode steps = responseNode.get("socraticSteps");
        JsonNode socraticConfig = responseNode.get("socraticConfig");
        if (steps == null || !steps.isArray() || steps.size() == 0) {
            // 하위 호환: socraticSteps가 없으면 answers[0]를 SUMMARY 단일 단계로 변환.
            JsonNode answers = responseNode.get("answers");
            String fallback = (answers != null && answers.isArray() && answers.size() > 0
                    && answers.get(0).has("answer")) ? answers.get(0).get("answer").asText() : "";
            chunks.add(socraticStepChunk("SUMMARY", "정리 및 다음 학습 방향", 3, "정리자", "정리자",
                    null, null, fallback, fallback, socraticConfig));
            if (!fallback.isEmpty()) {
                agentReplies.computeIfAbsent("정리자", k -> new StringBuilder()).append(fallback);
            }
            return;
        }
        for (JsonNode s : steps) {
            chunks.add(socraticStepChunkFromNode(s, socraticConfig));
            String name = s.has("agentName") && !s.get("agentName").isNull()
                    ? s.get("agentName").asText()
                    : (s.has("role") ? s.get("role").asText() : "튜터");
            String content = s.has("content") ? s.get("content").asText() : "";
            if (!content.isEmpty()) {
                agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
            }
        }
        log.info("소크라테스 SSE 단계 생성: steps={}", steps.size());
    }

    private String socraticStepChunkFromNode(JsonNode s, JsonNode socraticConfig) {
        return socraticStepChunk(
                s.has("stageType") ? s.get("stageType").asText() : "",
                s.has("stageTitle") ? s.get("stageTitle").asText() : "",
                s.has("agentIndex") && !s.get("agentIndex").isNull() ? s.get("agentIndex").asInt() : null,
                s.has("agentName") && !s.get("agentName").isNull() ? s.get("agentName").asText() : null,
                s.has("role") && !s.get("role").isNull() ? s.get("role").asText() : null,
                s.has("question") && !s.get("question").isNull() ? s.get("question").asText() : null,
                s.has("hint") && !s.get("hint").isNull() ? s.get("hint").asText() : null,
                s.has("content") ? s.get("content").asText() : "",
                s.has("feedback") && !s.get("feedback").isNull() ? s.get("feedback").asText() : null,
                socraticConfig);
    }

    /** 단일 socratic_step 청크 JSON 문자열 생성. */
    private String socraticStepChunk(String stageType, String stageTitle, Integer agentIndex,
                                     String agentName, String role, String question, String hint,
                                     String content, String feedback, JsonNode socraticConfig) {
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("type", "socratic_step");
            obj.put("stageType", stageType);
            obj.put("stageTitle", stageTitle);
            if (agentIndex != null) obj.put("agentIndex", agentIndex);
            if (agentName != null) obj.put("agentName", agentName);
            if (role != null) obj.put("role", role);
            if (question != null) obj.put("question", question);
            if (hint != null) obj.put("hint", hint);
            if (feedback != null) obj.put("feedback", feedback);
            obj.put("content", content);
            obj.put("directAnswerSuppressed", !"SUMMARY".equals(stageType));
            if (socraticConfig != null && !socraticConfig.isNull()) {
                obj.put("socraticConfig", socraticConfig);
            }
            obj.put("done", false);
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.error("socratic 단계 청크 생성 실패: stageType={}", stageType, e);
            return "{\"type\":\"socratic_step\",\"stageType\":\"" + stageType + "\",\"content\":\"\"}";
        }
    }


    /**
     * FastAPI 상황극 응답(simulationStages)을 simulation_stage SSE 청크로 변환한다.
     * requestId가 없는 그룹 SSE 경로에서는 stageType+agentIndex+contentHash 기준으로 중복을 제거한다.
     */
    private void buildSimulationStageChunks(JsonNode responseNode, List<String> chunks,
                                            Map<String, StringBuilder> agentReplies) {
        JsonNode stages = responseNode.get("simulationStages");
        JsonNode simulationConfig = responseNode.get("simulationConfig");
        Set<String> seen = new HashSet<>();
        if (stages == null || !stages.isArray() || stages.size() == 0) {
            JsonNode answers = responseNode.get("answers");
            String fallback = (answers != null && answers.isArray() && answers.size() > 0
                    && answers.get(0).has("answer")) ? answers.get(0).get("answer").asText() : "";
            chunks.add(simulationStageChunk("SUMMARY", "상황극 요약", 3, "결과 해석자", "결과 해석자",
                    fallback, null, simulationConfig));
            if (!fallback.isEmpty()) {
                agentReplies.computeIfAbsent("결과 해석자", k -> new StringBuilder()).append(fallback);
            }
            return;
        }
        for (JsonNode s : stages) {
            String stageType = s.has("stageType") ? s.get("stageType").asText() : "";
            int agentIndex = s.has("agentIndex") && !s.get("agentIndex").isNull() ? s.get("agentIndex").asInt() : 0;
            String content = s.has("content") ? s.get("content").asText() : "";
            String key = stageType + "::" + agentIndex + "::" + Integer.toHexString(content.hashCode());
            if (!seen.add(key)) continue;
            chunks.add(simulationStageChunkFromNode(s, simulationConfig));
            String name = s.has("agentName") && !s.get("agentName").isNull()
                    ? s.get("agentName").asText()
                    : (s.has("role") ? s.get("role").asText() : "상황극");
            if (!content.isEmpty()) {
                agentReplies.computeIfAbsent(name, k -> new StringBuilder()).append(content);
            }
        }
        log.info("상황극 SSE 단계 생성: stages={}", stages.size());
    }

    private String simulationStageChunkFromNode(JsonNode s, JsonNode simulationConfig) {
        try {
            Map<String, Object> obj = objectMapper.convertValue(s, Map.class);
            obj.put("type", "simulation_stage");
            if (simulationConfig != null && !simulationConfig.isNull()) {
                obj.put("simulationConfig", simulationConfig);
            }
            obj.put("done", false);
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.error("simulation 단계 청크 생성 실패", e);
            return "{\"type\":\"simulation_stage\",\"stageType\":\"\",\"content\":\"\"}";
        }
    }

    private String simulationStageChunk(String stageType, String stageTitle, Integer agentIndex,
                                        String agentName, String role, String content,
                                        Object choices, JsonNode simulationConfig) {
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("type", "simulation_stage");
            obj.put("stageType", stageType);
            obj.put("stageTitle", stageTitle);
            if (agentIndex != null) obj.put("agentIndex", agentIndex);
            if (agentName != null) obj.put("agentName", agentName);
            if (role != null) obj.put("role", role);
            obj.put("content", content);
            if (choices != null) obj.put("choices", choices);
            if (simulationConfig != null && !simulationConfig.isNull()) {
                obj.put("simulationConfig", simulationConfig);
            }
            obj.put("done", false);
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.error("simulation fallback 청크 생성 실패", e);
            return "{\"type\":\"simulation_stage\",\"stageType\":\"SUMMARY\",\"content\":\"\"}";
        }
    }

    /** 구조화 토론 단일 단계를 debate_section 이벤트 JSON으로 변환한다. */
    private String debateStageChunk(JsonNode stage, JsonNode debateConfig) {
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("type", "debate_section");
            obj.put("stageType", stage.has("stageType") ? stage.get("stageType").asText() : "");
            obj.put("stageTitle", stage.has("stageTitle") ? stage.get("stageTitle").asText() : "");
            obj.put("side", stage.has("side") ? stage.get("side").asText() : "");
            obj.put("role", stage.has("role") ? stage.get("role").asText() : "");
            if (stage.has("agentIndex") && !stage.get("agentIndex").isNull()) {
                obj.put("agentIndex", stage.get("agentIndex").asInt());
            }
            if (stage.has("agentName") && !stage.get("agentName").isNull()) {
                obj.put("agentName", stage.get("agentName").asText());
            }
            obj.put("content", stage.has("content") ? stage.get("content").asText() : "");
            if (debateConfig != null && !debateConfig.isNull()) {
                obj.put("debateConfig", debateConfig);
            }
            obj.put("done", false);
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.error("debate 단계 청크 생성 실패", e);
            return "{\"type\":\"debate_section\",\"stageType\":\"\",\"content\":\"\"}";
        }
    }

    /** 단일 debate_section 청크 JSON 문자열 생성. items 또는 content 중 하나를 담는다. */
    private String debateSectionChunk(String section, String title, JsonNode items, String content) {
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("type", "debate_section");
            obj.put("section", section);
            obj.put("title", title);
            if (items != null && items.isArray()) {
                obj.put("items", items);
            } else if (items == null && content == null) {
                obj.put("items", List.of());
            }
            if (content != null) {
                obj.put("content", content);
            }
            obj.put("done", false);
            return objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            log.error("debate 섹션 청크 생성 실패: section={}", section, e);
            return "{\"type\":\"debate_section\",\"section\":\"" + section + "\",\"items\":[]}";
        }
    }

    private int nodeSize(JsonNode node) {
        return (node != null && node.isArray()) ? node.size() : 0;
    }

    private Long parseLongOrNull(String s) {
        if (s == null || s.isBlank()) return null;
        try {
            return Long.parseLong(s.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private String firstNonBlank(String... values) {
        if (values == null) return "";
        for (String v : values) {
            if (v != null && !v.isBlank()) return v;
        }
        return "";
    }

    // agentName(TavilyAgent/SearchAgent 모두 검색봇) → BotDef
    private BotDef botDefForAgent(String agentName) {
        if (agentName == null) return null;
        String n = agentName.trim();
        if ("SearchAgent".equals(n)) n = "TavilyAgent";
        for (BotDef def : BOT_REGISTRY.values()) {
            if (def.agentName().equals(n)) return def;
        }
        return null;
    }

    private String botTypeForAgent(String agentName) {
        BotDef def = botDefForAgent(agentName);
        return def != null ? def.botType() : null;
    }

    private String displayNameForAgent(String agentName) {
        BotDef def = botDefForAgent(agentName);
        return def != null ? def.displayName() : agentName;
    }

    private String emojiForAgent(String agentName) {
        BotDef def = botDefForAgent(agentName);
        return def != null ? def.emoji() : "";
    }

    /** error 이벤트 SSE 생성 */
    private ServerSentEvent<String> errorEvent(String message) {
        String json;
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("message", message);
            obj.put("errorMessage", message);
            json = objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            json = "{\"message\":\"응답 생성 중 오류가 발생했습니다.\"}";
        }
        return ServerSentEvent.<String>builder()
                .event("error")
                .data(json)
                .build();
    }

    /** Intent Router 라우팅 이벤트 SSE 생성. WARN은 route_notice, 그 외 terminal은 route_message. */
    private ServerSentEvent<String> routeEvent(String routeAction, String message) {
        String json;
        try {
            Map<String, Object> obj = new LinkedHashMap<>();
            obj.put("type", "WARN".equals(routeAction) ? "route_notice" : "route_message");
            obj.put("routeAction", routeAction);
            obj.put("message", message);
            json = objectMapper.writeValueAsString(obj);
        } catch (Exception e) {
            json = "{\"type\":\"route_message\",\"message\":\"\"}";
        }
        String eventName = "WARN".equals(routeAction) ? "route_notice" : "route_message";
        return ServerSentEvent.<String>builder()
                .event(eventName)
                .data(json)
                .build();
    }
}
