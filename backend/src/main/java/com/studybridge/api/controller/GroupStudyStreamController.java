package com.studybridge.api.controller;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.RedisChatMessage;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.RedisChatService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

@RestController
@RequestMapping("/api/groups")
@RequiredArgsConstructor
@Slf4j
public class GroupStudyStreamController {

    private final RedisChatService redisChatService;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final UserRepository userRepository;
    private final WebClient fastApiWebClient;
    private final ObjectMapper objectMapper;

    @PostMapping(value = "/{groupId}/chats/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> streamGroupChat(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestBody ChatDTO.MultiChatRequest request) {

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

        // 3. Redis에서 최근 100개 대화 내역 조회 (시간순)
        List<RedisChatMessage> history = redisChatService.getRecentHistory(groupId);
        List<Map<String, Object>> previousAnswers = history.stream()
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

        // 4-4. agents 구성
        List<Map<String, Object>> agentsList;
        if ("all_bots".equalsIgnoreCase(runMode)) {
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
            // 정보 부족 시 안전 기본값: 3봇 전체 토론
            agentsList = List.of(
                    botAgentMap("search_bot"),
                    botAgentMap("summary_bot"),
                    botAgentMap("quiz_bot")
            );
        }

        final String effectiveMessage = message;

        // 4-5. FastAPI 요청 페이로드 구성 (group_study_ai 모드)
        Map<String, Object> fastApiPayload = new LinkedHashMap<>();
        fastApiPayload.put("message", effectiveMessage);
        fastApiPayload.put("mode", "group_study_ai");
        fastApiPayload.put("runMode", "all_bots".equalsIgnoreCase(runMode) ? "all_bots" : "single");
        fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 1);
        fastApiPayload.put("showFinalSynthesis", false);
        fastApiPayload.put("previousAnswers", previousAnswers);
        fastApiPayload.put("targetAgentId", request.getTargetAgentId());
        fastApiPayload.put("agents", agentsList);

        // 스트림 누적 상태 저장 객체
        Map<String, StringBuilder> agentReplies = new ConcurrentHashMap<>();

        // 5. FastAPI 동기 호출 및 데이터를 Flux 스트림으로 분할/지연 처리하여 SSE 에뮬레이션
        return fastApiWebClient.post()
                .uri("/api/ai/multi-chat")
                .bodyValue(fastApiPayload)
                .retrieve()
                .bodyToMono(JsonNode.class)
                .flatMapMany(responseNode -> {
                    List<String> chunks = new ArrayList<>();
                    JsonNode answersNode = responseNode.get("answers");
                    if (answersNode != null && answersNode.isArray()) {
                        for (JsonNode answerNode : answersNode) {
                            String agentName = answerNode.has("agentName") ? answerNode.get("agentName").asText() : "";
                            String answerText = answerNode.has("answer") ? answerNode.get("answer").asText() : "";

                            if (!agentName.isEmpty() && !answerText.isEmpty()) {
                                agentReplies.computeIfAbsent(agentName, k -> new StringBuilder()).append(answerText);

                                // 텍스트를 청크 단위로 분할하여 실시간 타이핑 느낌을 주도록 스트림 구성
                                int chunkSize = 4;
                                for (int i = 0; i < answerText.length(); i += chunkSize) {
                                    String sub = answerText.substring(i, Math.min(i + chunkSize, answerText.length()));
                                    try {
                                        Map<String, Object> chunkObj = new LinkedHashMap<>();
                                        chunkObj.put("agentName", agentName);
                                        chunkObj.put("botType", botTypeForAgent(agentName));
                                        chunkObj.put("displayName", displayNameForAgent(agentName));
                                        chunkObj.put("emoji", emojiForAgent(agentName));
                                        chunkObj.put("content", sub);
                                        chunkObj.put("done", false);
                                        chunks.add(objectMapper.writeValueAsString(chunkObj));
                                    } catch (Exception e) {
                                        log.error("Error creating stream chunk", e);
                                    }
                                }
                            }
                        }
                    }
                    try {
                        Map<String, Object> doneObj = new LinkedHashMap<>();
                        doneObj.put("done", true);
                        chunks.add(objectMapper.writeValueAsString(doneObj));
                    } catch (Exception e) {
                        log.error("Error creating done chunk", e);
                    }
                    return Flux.fromIterable(chunks);
                })
                .delayElements(java.time.Duration.ofMillis(10))
                .map(chunk -> ServerSentEvent.<String>builder()
                        .data(chunk)
                        .build())
                .doOnComplete(() -> {
                    log.info("SSE Stream completed for groupId={}. Persisting discussion to Redis.", groupId);

                    // 1. 유저 질문 저장 (슬래시 명령어 제거된 메시지)
                    redisChatService.saveMessage(groupId, RedisChatMessage.builder()
                            .agentName(displayName)
                            .answer(effectiveMessage)
                            .role("USER")
                            .build());

                    // 2. 완성된 에이전트 답변들 순차 저장
                    agentReplies.forEach((agentName, replyBuilder) -> {
                        String fullReply = replyBuilder.toString().trim();
                        if (!fullReply.isEmpty()) {
                            // 해당하는 agentId 매핑
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
                            redisChatService.saveMessage(groupId, RedisChatMessage.builder()
                                    .agentName(agentName)
                                    .answer(fullReply)
                                    .role("ASSISTANT")
                                    .agentId(matchedAgentId)
                                    .build());
                        }
                    });
                })
                .doOnError(err -> log.error("Error during FastAPI chat streaming for groupId={}", groupId, err))
                .onErrorResume(err -> Flux.just(
                        ServerSentEvent.<String>builder()
                                .event("error")
                                .data("{\"errorMessage\":\"AI 스트리밍 대화 중 오류가 발생했습니다. 다시 시도해 주세요.\"}")
                                .build()
                ));
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
}
