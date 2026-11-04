package com.studybridge.api.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.entity.GroupChatMessage;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupChatMessageRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.IntentRouterService;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * 그룹 AI 봇 SSE(POST /api/groups/{groupId}/chats/stream) + 이력(GET .../chats/history) 품질 게이트(Phase D):
 *  · 게이트 ON 거절(79)·hardFail·평가기 503 → SSE·DB 어디에도 초안 본문 0(사용자 질문 행만 저장).
 *  · 게이트 ON 승인(80) → 평가기 호출(GROUP_STUDY_MESSAGE, 참여자 제약) + 승인 본문만 quality_status=APPROVED 로 저장.
 *  · non-stream 폴백도 게이트를 거친다. 미승인 레거시 AI 답변은 이력에서 가리고 다음 추론 맥락에서도 뺀다.
 *  · 게이트 OFF: 이벤트 원문 그대로 중계·평가기 호출 0·이력 응답 형태 불변.
 * 그룹/사용자는 전부 mock(운영 그룹·E2E 픽스처 미사용), ai07 은 로컬 HttpServer 대역.
 */
class GroupChatQualityGateTest {

    static final String CANARY = "CANARY9G2B";
    static final long GROUP = 41L;
    static final long USER = 7L;
    static final ObjectMapper M = new ObjectMapper();

    ChatGateStubServer stub;
    volatile boolean streamBroken;
    GroupChatMessageRepository chats;
    final List<GroupChatMessage> saved = new CopyOnWriteArrayList<>();
    final List<GroupChatMessage> history = new ArrayList<>();

    static String streamBody() {
        return "event: turn_start\ndata: {\"turnId\":\"t1\",\"type\":\"turn_start\"}\n\n"
                + "event: agent_answer\ndata: {\"type\":\"agent_answer\",\"agentId\":1,\"agentIndex\":0,\"agentName\":\"AI 튜터\","
                + "\"eventId\":\"e1\",\"content\":\"" + CANARY + " 객체지향은 데이터와 동작을 객체로 묶는 방식입니다.\"}\n\n"
                + "event: all_complete\ndata: {\"type\":\"all_complete\",\"turnId\":\"t1\",\"answers\":[{\"agentId\":1,\"agentIndex\":0,"
                + "\"agentName\":\"AI 튜터\",\"answer\":\"" + CANARY + " 객체지향은 데이터와 동작을 객체로 묶는 방식입니다.\"}]}\n\n";
    }

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
        stub.sse("/api/ai/multi-chat/stream", n -> streamBroken ? null : streamBody());
        stub.json("/api/ai/multi-chat", n -> "{\"answers\":[{\"agentId\":1,\"agentName\":\"AI 튜터\",\"answer\":\"" + CANARY
                + " 폴백 답변: 캡슐화는 내부 상태를 숨기는 것입니다.\"}]}");
    }

    @AfterEach
    void down() {
        stub.close();
    }

    GroupStudyStreamController controller(boolean gateOn) {
        chats = mock(GroupChatMessageRepository.class);
        when(chats.save(any(GroupChatMessage.class))).thenAnswer(inv -> {
            saved.add(inv.getArgument(0));
            return inv.getArgument(0);
        });
        when(chats.findTop100ByGroupStudyIdOrderByCreatedAtDesc(GROUP)).thenAnswer(inv -> new ArrayList<>(history));
        GroupStudyRepository groups = mock(GroupStudyRepository.class);
        when(groups.findById(GROUP)).thenReturn(Optional.of(new GroupStudy()));
        GroupStudyMemberRepository members = mock(GroupStudyMemberRepository.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, USER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
        User member = User.builder().id(USER).email("m@x").password("p").build();
        member.setDisplayName("민수");
        GroupStudyMember gm = new GroupStudyMember();
        gm.setUser(member);
        when(members.findWithUserByGroupStudyIdAndStatus(GROUP, GroupStudyMemberStatus.JOINED)).thenReturn(List.of(gm));
        UserRepository users = mock(UserRepository.class);
        when(users.findById(USER)).thenReturn(Optional.of(member));
        IntentRouterService router = mock(IntentRouterService.class);
        when(router.route(anyString(), eq("group_study_chat"), anyMap()))
                .thenReturn(IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.PROCEED).build());
        GroupStudyStreamController c = new GroupStudyStreamController(chats, groups, members, users, stub.client(), M, router);
        c.setQualityStreamGate(stub.streamGate(gateOn));
        return c;
    }

    List<ServerSentEvent<String>> ask(GroupStudyStreamController c) {
        ChatDTO.MultiChatRequest req = ChatDTO.MultiChatRequest.builder().message("객체지향이 뭐야?").messageId("grp-req-0001").build();
        CustomUserDetails me = new CustomUserDetails(User.builder().id(USER).email("m@x").password("p").build());
        return c.streamGroupChat(me, GROUP, req, new MockHttpServletResponse()).collectList().block(Duration.ofSeconds(30));
    }

    static boolean leaks(List<ServerSentEvent<String>> out) {
        return out.stream().anyMatch(e -> e.data() != null && e.data().contains(CANARY));
    }

    List<GroupChatMessage> aiRows() {
        return saved.stream().filter(m -> "ASSISTANT".equals(m.getRole())).toList();
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/groups/{groupId}/chats/stream"})
    @Test
    void rejected79LeaksNothingToSseOrDb() {
        stub.policy = (n, in) -> ChatGateStubServer.out(79, "REJECTED", false);
        List<ServerSentEvent<String>> out = ask(controller(true));
        assertFalse(stub.evaluations.isEmpty(), "평가기가 호출돼야 한다");
        assertFalse(leaks(out), "거절 초안이 SSE 로 나감");
        assertTrue(out.stream().anyMatch(e -> "agent_error".equals(e.event()) && e.data().contains("QUALITY_REJECTED")));
        assertTrue(aiRows().isEmpty(), "거절 초안이 그룹 채팅 DB 에 저장됨");
        assertEquals(1, saved.size(), "사용자 질문(USER_AI) 행만 저장");
        assertEquals("USER_AI", saved.get(0).getRole());
        assertNull(saved.get(0).getQualityStatus());
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/groups/{groupId}/chats/stream"})
    @Test
    void approved80IsStreamedAndPersistedWithStatus() {
        stub.policy = (n, in) -> ChatGateStubServer.out(80, "APPROVED", false);
        List<ServerSentEvent<String>> out = ask(controller(true));
        JsonNode first = stub.evaluations.get(0);
        assertEquals("GROUP_STUDY_MESSAGE", first.get("taskType").asText());
        assertEquals("agent_message", first.get("outputKind").asText());
        assertTrue(ChatGateStubServer.proposedText(first).contains(CANARY), "화면에 보일 본문 전체를 평가");
        List<String> participants = new ArrayList<>();
        first.path("constraints").path("participants").forEach(p -> participants.add(p.asText()));
        assertTrue(participants.contains("민수") && participants.contains("AI 튜터"), "참여자 제약 = 멤버 + 봇");
        assertTrue(out.stream().anyMatch(e -> "agent_answer".equals(e.event()) && e.data().contains(CANARY)
                && e.data().contains("\"qualityStatus\":\"APPROVED\"") && e.data().contains("\"agentName\":\"AI 튜터\"")));
        assertTrue(out.stream().filter(e -> e.data() != null && !e.data().isBlank())
                .allMatch(e -> e.data().contains("\"qualityGateMode\":\"spring-v1\"")), "모든 본문 프레임은 게이트 표식");
        List<GroupChatMessage> ai = aiRows();
        assertEquals(1, ai.size());
        assertEquals("APPROVED", ai.get(0).getQualityStatus());
        assertTrue(ai.get(0).getContent().contains(CANARY), "승인된 원문 그대로 저장");
    }

    @Test
    void hardFailAndEvaluatorDownAreNotDisplayed() {
        for (String mode : List.of("hardFail", "down")) {
            saved.clear();
            stub.evaluations.clear();
            stub.policy = (n, in) -> "down".equals(mode) ? null : ChatGateStubServer.out(92, "REJECTED", true);
            List<ServerSentEvent<String>> out = ask(controller(true));
            assertFalse(leaks(out), mode);
            assertTrue(aiRows().isEmpty(), mode);
            if ("down".equals(mode)) {
                assertTrue(out.stream().anyMatch(e -> e.data() != null && e.data().contains("QUALITY_UNAVAILABLE")));
            }
        }
    }

    @Test
    void nonStreamFallbackIsGatedToo() {
        streamBroken = true;
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        List<ServerSentEvent<String>> out = ask(controller(true));
        assertEquals(1, stub.calls("/api/ai/multi-chat"), "스트림 실패 → non-stream 폴백 호출");
        assertFalse(stub.evaluations.isEmpty(), "폴백 응답도 평가");
        assertTrue(stub.evaluations.stream().anyMatch(in -> ChatGateStubServer.proposedText(in).contains("폴백 답변")));
        assertFalse(leaks(out), "폴백 초안 미노출");
        assertTrue(aiRows().isEmpty());
    }

    @Test
    void gateOffRelaysRawAndPersistsWithoutStatus() {
        List<ServerSentEvent<String>> out = ask(controller(false));
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertTrue(leaks(out), "게이트 OFF: 기존 그대로 중계");
        assertTrue(out.stream().noneMatch(e -> e.data() != null && e.data().contains("qualityGateMode")));
        List<GroupChatMessage> ai = aiRows();
        assertEquals(1, ai.size());
        assertNull(ai.get(0).getQualityStatus(), "게이트 OFF 에선 승인 표시를 붙이지 않는다");
    }

    GroupChatMessage row(long id, String role, String content, String status) {
        GroupChatMessage m = GroupChatMessage.builder().id(id).role(role).senderName("AI 튜터").senderId("1").content(content)
                .qualityStatus(status).build();
        m.setCreatedAt(LocalDateTime.now());
        return m;
    }

    @com.studybridge.api.ai.quality.GateEvidence({"GET /api/groups/{groupId}/chats/history"})
    @Test
    void historyRedactsUnapprovedAiRowsOnlyWhenGateOn() {
        // findTop100…Desc 는 최신순 — 컨트롤러가 뒤집는다.
        history.add(row(3, "ASSISTANT", "승인 답변", "APPROVED"));
        history.add(row(2, "ASSISTANT", CANARY + " 레거시 미검증 답변", null));
        history.add(row(1, "USER_AI", "질문", null));
        CustomUserDetails me = new CustomUserDetails(User.builder().id(USER).email("m@x").password("p").build());
        List<Map<String, Object>> on = controller(true).getChatHistory(me, GROUP).getBody();
        assertEquals("질문", on.get(0).get("content"));
        assertEquals(GroupStudyStreamController.QUALITY_REDACTED_TEXT, on.get(1).get("content"));
        assertEquals(Boolean.TRUE, on.get(1).get("qualityRedacted"));
        assertEquals("승인 답변", on.get(2).get("content"));
        assertEquals("APPROVED", on.get(2).get("qualityStatus"));
        assertFalse(on.toString().contains(CANARY), "게이트 ON: 미승인 AI 본문 0");

        List<Map<String, Object>> off = controller(false).getChatHistory(me, GROUP).getBody();
        assertTrue(off.get(1).get("content").toString().contains(CANARY), "게이트 OFF: 기존 그대로");
        assertEquals(List.of("id", "senderName", "senderId", "content", "isAi", "isAiQuery"), new ArrayList<>(off.get(1).keySet()),
                "게이트 OFF 응답 형태 불변");
    }

    @Test
    void learningMemoryDropsUnapprovedAiRowsWhenGateOn() {
        for (boolean on : List.of(true, false)) {
            history.clear();
            history.add(row(3, "ASSISTANT", "승인된 이전 답변", "APPROVED"));
            history.add(row(2, "ASSISTANT", CANARY + " 레거시 미검증 답변", null));
            history.add(row(1, "USER_AI", "이전 질문", null));
            stub.generationBodies.clear();
            ask(controller(on));
            JsonNode prev = stub.generationBodies.get(0).get("previousAnswers");
            assertEquals(on ? 2 : 3, prev.size(), "게이트 ON: 미승인 AI 답변은 다음 추론 맥락에서 제외");
            assertEquals(!on, prev.toString().contains(CANARY));
            assertTrue(prev.toString().contains("승인된 이전 답변"));
        }
    }
}
