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

        // 4. FastAPI 요청 페이로드 구성
        Map<String, Object> fastApiPayload = new LinkedHashMap<>();
        fastApiPayload.put("message", request.getMessage());
        fastApiPayload.put("mode", request.getMode() != null ? request.getMode() : "multi_agent_discussion");
        fastApiPayload.put("rounds", request.getRounds() != null ? request.getRounds() : 3);
        fastApiPayload.put("showFinalSynthesis", request.getShowFinalSynthesis() != null ? request.getShowFinalSynthesis() : true);
        fastApiPayload.put("previousAnswers", previousAnswers);
        fastApiPayload.put("targetAgentId", request.getTargetAgentId());

        // 에이전트 목록이 없으면 디폴트 3개 에이전트 구성
        List<Map<String, Object>> agentsList;
        if (request.getAgents() != null && !request.getAgents().isEmpty()) {
            agentsList = request.getAgents().stream()
                    .map(a -> {
                        Map<String, Object> map = new LinkedHashMap<>();
                        map.put("id", a.getId());
                        map.put("agentId", a.getAgentId());
                        map.put("name", a.getName());
                        map.put("role", a.getRole());
                        map.put("personality", a.getPersonality());
                        map.put("personalityStrength", a.getPersonalityStrength() != null ? a.getPersonalityStrength() : "extreme");
                        map.put("style", a.getStyle());
                        map.put("tone", a.getTone());
                        map.put("knowledgeLevel", a.getKnowledgeLevel() != null ? a.getKnowledgeLevel() : "학사 수준");
                        map.put("customInstruction", a.getCustomInstruction());
                        map.put("persona", a.getPersona());
                        return map;
                    })
                    .toList();
        } else {
            agentsList = List.of(
                    createAgentMap(1L, "SummaryAgent", "요약봇", "학습 내용을 요약하고 정리해 줍니다."),
                    createAgentMap(2L, "QuizAgent", "퀴즈봇", "학습 내용을 검토할 퀴즈를 출제합니다."),
                    createAgentMap(3L, "TavilyAgent", "검색봇", "추가적인 유용한 외부 정보와 문헌을 찾아 줍니다.")
            );
        }
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

                    // 1. 유저 질문 저장
                    redisChatService.saveMessage(groupId, RedisChatMessage.builder()
                            .agentName(displayName)
                            .answer(request.getMessage())
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

    private Map<String, Object> createAgentMap(Long id, String name, String role, String goal) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("id", id);
        map.put("agentId", id);
        map.put("name", name);
        map.put("role", role);
        map.put("personality", "전문적");
        map.put("personalityStrength", "extreme");
        map.put("style", "전문적");
        map.put("tone", "전문적");
        map.put("knowledgeLevel", "학사 수준");
        map.put("customInstruction", "");
        map.put("persona", "");
        map.put("goal", goal);
        return map;
    }
}
