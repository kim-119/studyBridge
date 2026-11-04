package com.studybridge.api.security.stomp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.config.WebSocketConfig;
import com.studybridge.api.controller.GroupStudySocketController;
import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.entity.GroupChatMessage;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupChatMessageRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import com.studybridge.api.service.GroupStudyQuizSessionService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringBootConfiguration;
import org.springframework.boot.autoconfigure.ImportAutoConfiguration;
import org.springframework.boot.autoconfigure.context.PropertyPlaceholderAutoConfiguration;
import org.springframework.boot.autoconfigure.jackson.JacksonAutoConfiguration;
import org.springframework.boot.autoconfigure.web.servlet.DispatcherServletAutoConfiguration;
import org.springframework.boot.autoconfigure.web.servlet.ServletWebServerFactoryAutoConfiguration;
import org.springframework.boot.autoconfigure.web.servlet.WebMvcAutoConfiguration;
import org.springframework.boot.autoconfigure.websocket.servlet.WebSocketMessagingAutoConfiguration;
import org.springframework.boot.autoconfigure.websocket.servlet.WebSocketServletAutoConfiguration;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.context.annotation.Import;
import org.springframework.messaging.simp.user.SimpUserRegistry;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.after;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 실제 내장 Tomcat + SockJS raw WebSocket + simple broker 위에서 공격자 프레임을 그대로 보내 검증한다.
 * (저장소·퀴즈 서비스는 mock — 검증 대상은 STOMP 인증·인가 경계다.)
 *
 * 그룹 100: ALICE(11)·BOB(12) 멤버 / 그룹 200: MALLORY(13) 멤버 / BANNED(14) 정지 계정.
 */
@SpringBootTest(
        classes = StompSecurityIntegrationTest.TestApp.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "jwt.secret=stomp-integration-test-secret-0123456789-abcdefghijklmnop",
                "jwt.expiration-ms=600000"
        })
@ExtendWith(OutputCaptureExtension.class)
class StompSecurityIntegrationTest {

    static final long GROUP_A = 100L;
    static final long GROUP_B = 200L;
    static final long ALICE = 11L;
    static final long BOB = 12L;
    static final long MALLORY = 13L;
    static final long BANNED = 14L;
    static final Duration WAIT = Duration.ofSeconds(3);
    static final Duration QUIET = Duration.ofMillis(700);

    @SpringBootConfiguration
    @ImportAutoConfiguration({
            PropertyPlaceholderAutoConfiguration.class,
            JacksonAutoConfiguration.class,
            ServletWebServerFactoryAutoConfiguration.class,
            DispatcherServletAutoConfiguration.class,
            WebMvcAutoConfiguration.class,
            WebSocketServletAutoConfiguration.class,
            WebSocketMessagingAutoConfiguration.class
    })
    @Import({WebSocketConfig.class, StompAuthChannelInterceptor.class, StompAuthErrorHandler.class,
            StompSessionRevoker.class, GroupStudySocketController.class, JwtTokenProvider.class})
    static class TestApp {
    }

    @LocalServerPort
    int port;

    @Autowired JwtTokenProvider jwt;
    @Autowired ObjectMapper objectMapper;
    @Autowired ApplicationEventPublisher events;
    @Autowired SimpUserRegistry userRegistry;
    @Autowired StompSessionRevoker revoker;

    @MockBean UserDetailsService userDetailsService;
    @MockBean ExhibitSessionService exhibitSessionService;
    @MockBean UserRepository userRepository;
    @MockBean GroupStudyMemberRepository memberRepository;
    @MockBean GroupStudyRepository groupStudyRepository;
    @MockBean GroupChatMessageRepository chatRepository;
    @MockBean GroupStudyQuizSessionService quizSessionService;

    /** "groupId:userId" — 테스트 중 강퇴를 흉내 내려고 바꿀 수 있는 멤버십. */
    final Set<String> memberships = ConcurrentHashMap.newKeySet();
    RawStompClient alice;
    RawStompClient bob;

    @BeforeEach
    void setUp() {
        reset(userRepository, memberRepository, groupStudyRepository, chatRepository, quizSessionService, exhibitSessionService);
        revoker.setCloseDelayMs(200);
        memberships.clear();
        memberships.addAll(Set.of(GROUP_A + ":" + ALICE, GROUP_A + ":" + BOB, GROUP_B + ":" + MALLORY));
        stubUser(ALICE, "alice@studybridge.test", "앨리스", "ACTIVE");
        stubUser(BOB, "bob@studybridge.test", "밥", "ACTIVE");
        stubUser(MALLORY, "mallory@studybridge.test", "말로리", "ACTIVE");
        stubUser(BANNED, "banned@studybridge.test", "정지", "BANNED");
        when(memberRepository.existsByGroupStudyIdAndUserIdAndStatus(anyLong(), anyLong(), eq(GroupStudyMemberStatus.JOINED)))
                .thenAnswer(inv -> memberships.contains(inv.getArgument(0) + ":" + inv.getArgument(1)));
        when(exhibitSessionService.allowsAccess(any(), any(), any())).thenReturn(true);
        when(groupStudyRepository.findById(anyLong()))
                .thenAnswer(inv -> Optional.of(GroupStudy.builder().id(inv.getArgument(0)).title("g").build()));
    }

    @AfterEach
    void tearDown() {
        if (alice != null) alice.close();
        if (bob != null) bob.close();
    }

    private void stubUser(long id, String email, String name, String status) {
        when(userRepository.findById(id)).thenReturn(Optional.of(
                User.builder().id(id).email(email).password("x").displayName(name).status(status).role("USER").build()));
    }

    private String tokenOf(long userId) {
        return jwt.createToken(userId, emailOf(userId));
    }

    private static String emailOf(long userId) {
        return switch ((int) userId) {
            case 11 -> "alice@studybridge.test";
            case 12 -> "bob@studybridge.test";
            case 13 -> "mallory@studybridge.test";
            case 14 -> "banned@studybridge.test";
            default -> "nobody@studybridge.test";
        };
    }

    private RawStompClient connected(long userId) throws InterruptedException {
        RawStompClient client = RawStompClient.open(port).connect("Bearer " + tokenOf(userId));
        RawStompClient.Frame frame = client.next(WAIT);
        assertThat(frame).as("CONNECTED for user %s", userId).isNotNull();
        assertThat(frame.command()).isEqualTo("CONNECTED");
        return client;
    }

    private void subscribeAndWait(RawStompClient client, long userId, String id, String destination) {
        client.subscribe(id, destination);
        await().atMost(WAIT).until(() -> !userRegistry.findSubscriptions(s ->
                destination.equals(s.getDestination()) && String.valueOf(userId).equals(s.getSession().getUser().getName())).isEmpty());
        try {
            Thread.sleep(150); // 브로커 구독 등록(clientInbound 실행기)이 끝날 시간
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * 인증된 세션의 무단 구독: ERROR 없이 버려지고(연결 유지), 구독이 등록되지 않으며, 그 목적지의 메시지를 받지 못한다.
     * 양성 대조: 같은 그룹 멤버(BOB)는 같은 메시지를 받는다.
     */
    private void assertSubscriptionDropped(RawStompClient client, long userId, String destination) throws Exception {
        client.subscribe("denied", destination);
        assertThat(client.nextOf("ERROR", QUIET)).as("no ERROR for a dropped SUBSCRIBE").isNull();
        assertThat(client.isOpen()).isTrue();
        assertThat(userRegistry.findSubscriptions(s -> String.valueOf(userId).equals(s.getSession().getUser().getName())
                && destination.equals(s.getDestination()))).as("subscription must not be registered").isEmpty();

        try (RawStompClient control = connected(BOB); RawStompClient sender = connected(ALICE)) {
            subscribeAndWait(control, BOB, "ctl", "/topic/group/" + GROUP_A + "/chat");
            String marker = "probe-" + System.nanoTime();
            sender.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"content\":\"" + marker + "\"}");
            assertThat(control.nextOf("MESSAGE", WAIT)).as("positive control receives").isNotNull();
            assertThat(client.nextOf("MESSAGE", QUIET)).as("dropped subscription receives nothing").isNull();
        }
    }

    private static void assertRejected(RawStompClient client, String code, String reason) throws InterruptedException {
        RawStompClient.Frame frame = client.nextOf("ERROR", WAIT);
        assertThat(frame).as("ERROR frame").isNotNull();
        assertThat(frame.header("message")).isEqualTo(code);
        assertThat(frame.header("sb-reason")).isEqualTo(reason);
        assertThat(client.awaitClosed(WAIT)).as("server closes the session after ERROR").isTrue();
    }

    // ── CONNECT 인증 ──────────────────────────────────────────────────────────

    @Test
    void connect_withoutToken_isRejected() throws Exception {
        try (RawStompClient client = RawStompClient.open(port).connect(null)) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_MISSING");
        }
    }

    @Test
    void connect_withEmptyOrNonBearerHeader_isRejected() throws Exception {
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer ")) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_MISSING");
        }
        try (RawStompClient client = RawStompClient.open(port).connect("Basic " + tokenOf(ALICE))) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_MISSING");
        }
    }

    @Test
    void connect_withTokenSignedByAnotherKey_isRejected() throws Exception {
        JwtTokenProvider attacker = new JwtTokenProvider(userDetailsService);
        ReflectionTestUtils.setField(attacker, "secretKeyString", "attacker-chosen-secret-0123456789-abcdefghijklmnop");
        ReflectionTestUtils.setField(attacker, "tokenValidityInMilliseconds", 600_000L);
        ReflectionTestUtils.invokeMethod(attacker, "init");
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + attacker.createToken(ALICE, "alice@studybridge.test"))) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_INVALID");
        }
    }

    @Test
    void connect_withTamperedClaims_isRejected() throws Exception {
        // MALLORY 의 정상 토큰에서 payload 의 userId 만 ALICE 로 바꾼다(서명은 그대로).
        String[] parts = tokenOf(MALLORY).split("\\.");
        String payload = new String(Base64.getUrlDecoder().decode(parts[1]), StandardCharsets.UTF_8)
                .replace("\"userId\":" + MALLORY, "\"userId\":" + ALICE)
                .replace("mallory@", "alice@");
        String forged = parts[0] + "." + Base64.getUrlEncoder().withoutPadding()
                .encodeToString(payload.getBytes(StandardCharsets.UTF_8)) + "." + parts[2];
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + forged)) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_INVALID");
        }
    }

    @Test
    void connect_withExpiredToken_isRejected() throws Exception {
        JwtTokenProvider expiredIssuer = new JwtTokenProvider(userDetailsService);
        ReflectionTestUtils.setField(expiredIssuer, "secretKeyString", "stomp-integration-test-secret-0123456789-abcdefghijklmnop");
        ReflectionTestUtils.setField(expiredIssuer, "tokenValidityInMilliseconds", -60_000L);
        ReflectionTestUtils.invokeMethod(expiredIssuer, "init");
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + expiredIssuer.createToken(ALICE, "alice@studybridge.test"))) {
            assertRejected(client, "UNAUTHORIZED", "TOKEN_INVALID");
        }
    }

    @Test
    void connect_tokenWhoseEmailDoesNotMatchUser_isRejected() throws Exception {
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + jwt.createToken(ALICE, "someone-else@studybridge.test"))) {
            assertRejected(client, "UNAUTHORIZED", "USER_NOT_FOUND");
        }
    }

    @Test
    void connect_bannedUser_isForbidden() throws Exception {
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + tokenOf(BANNED))) {
            assertRejected(client, "FORBIDDEN", "USER_INACTIVE");
        }
    }

    @Test
    void connect_exhibitAccountWithoutLiveSlot_isRejected() throws Exception {
        when(exhibitSessionService.allowsAccess(eq("alice@studybridge.test"), eq(ALICE), any())).thenReturn(false);
        try (RawStompClient client = RawStompClient.open(port).connect("Bearer " + tokenOf(ALICE))) {
            assertRejected(client, "UNAUTHORIZED", "SESSION_EXPIRED");
        }
    }

    @Test
    void frames_beforeConnect_areRejected() throws Exception {
        try (RawStompClient client = RawStompClient.open(port)) {
            client.subscribe("s1", "/topic/group/" + GROUP_A + "/chat");
            assertRejected(client, "UNAUTHORIZED", "NOT_AUTHENTICATED");
        }
        try (RawStompClient client = RawStompClient.open(port)) {
            client.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"senderId\":\"11\",\"content\":\"x\"}");
            assertRejected(client, "UNAUTHORIZED", "NOT_AUTHENTICATED");
        }
        verify(chatRepository, never()).save(any());
    }

    // ── SUBSCRIBE 인가 ────────────────────────────────────────────────────────

    @Test
    void subscribe_otherGroupsTopic_isDropped_andReceivesNothing() throws Exception {
        try (RawStompClient mallory = connected(MALLORY)) {
            assertSubscriptionDropped(mallory, MALLORY, "/topic/group/" + GROUP_A + "/chat");
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "/topic/group/*/chat",
            "/topic/group/**",
            "/topic/**",
            "/topic/group/{id}/chat",
            "/topic/group/0100/chat",
            "/topic/group/100/chat/extra",
            "/topic/group/100/unknown",
            "/queue/anything",
            "/user/queue/errors",
            "/pub/group/100/chat"
    })
    void subscribe_wildcardOrUnknownDestination_isDropped(String destination) throws Exception {
        try (RawStompClient client = connected(MALLORY)) {
            assertSubscriptionDropped(client, MALLORY, destination);
        }
    }

    // ── SEND 인가 ─────────────────────────────────────────────────────────────

    @Test
    void send_directlyToBrokerTopic_isForbidden_andNotBroadcast() throws Exception {
        bob = connected(BOB);
        subscribeAndWait(bob, BOB, "m", "/topic/group/" + GROUP_A + "/members");
        try (RawStompClient attacker = connected(ALICE)) {
            // 이전에는 브로커가 그대로 방송했다 → 받은 클라이언트는 "본인 강퇴" 로 방을 닫았다.
            attacker.sendJson("/topic/group/" + GROUP_A + "/members", "{\"type\":\"PARTICIPANT_KICKED\",\"targetUserId\":" + BOB + "}");
            assertRejected(attacker, "FORBIDDEN", "DESTINATION_NOT_ALLOWED");
        }
        assertThat(bob.nextOf("MESSAGE", QUIET)).as("forged kick must not reach BOB").isNull();
    }

    @Test
    void send_chatToOtherGroup_isForbidden() throws Exception {
        try (RawStompClient mallory = connected(MALLORY)) {
            mallory.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"content\":\"침입\"}");
            assertRejected(mallory, "FORBIDDEN", "NOT_GROUP_MEMBER");
        }
        verify(chatRepository, after(300).never()).save(any());
    }

    @Test
    void send_chatImpersonatingAnotherUser_isForbidden() throws Exception {
        try (RawStompClient bobConn = connected(BOB)) {
            bobConn.sendJson("/pub/group/" + GROUP_A + "/chat",
                    "{\"senderId\":\"" + ALICE + "\",\"senderName\":\"앨리스\",\"content\":\"나 앨리스야\"}");
            assertRejected(bobConn, "FORBIDDEN", "IDENTITY_MISMATCH");
        }
        verify(chatRepository, after(300).never()).save(any());
    }

    @Test
    void send_malformedPayload_isRejected() throws Exception {
        try (RawStompClient client = connected(ALICE)) {
            client.sendJson("/pub/group/" + GROUP_A + "/chat", "not-json");
            assertRejected(client, "FORBIDDEN", "MALFORMED_PAYLOAD");
        }
    }

    @Test
    void send_chat_isAttributedToAuthenticatedUser_notToPayload(CapturedOutput output) throws Exception {
        bob = connected(BOB);
        subscribeAndWait(bob, BOB, "c", "/topic/group/" + GROUP_A + "/chat");
        alice = connected(ALICE);
        // 기존 클라이언트처럼 자기 senderId 를 보내고, senderName 은 'System' 으로 위장한다.
        String secret = "비밀본문-" + System.nanoTime();
        alice.sendJson("/pub/group/" + GROUP_A + "/chat",
                "{\"senderId\":" + ALICE + ",\"senderName\":\"System\",\"content\":\"" + secret + "\"}");

        RawStompClient.Frame message = bob.nextOf("MESSAGE", WAIT);
        assertThat(message).isNotNull();
        JsonNode body = objectMapper.readTree(message.body());
        assertThat(body.get("senderId").asText()).isEqualTo(String.valueOf(ALICE));
        assertThat(body.get("senderName").asText()).isEqualTo("앨리스");
        assertThat(body.get("content").asText()).isEqualTo(secret);

        ArgumentCaptor<GroupChatMessage> saved = ArgumentCaptor.forClass(GroupChatMessage.class);
        verify(chatRepository, timeout(2000)).save(saved.capture());
        assertThat(saved.getValue().getSenderId()).isEqualTo(String.valueOf(ALICE));
        assertThat(saved.getValue().getSenderName()).isEqualTo("앨리스");

        // 채팅 본문은 로그에 남지 않는다(길이만).
        assertThat(output.getAll()).doesNotContain(secret).contains("Group chat relayed. groupId=" + GROUP_A);
    }

    @Test
    void send_chatWithoutSenderId_newClientStyle_isAccepted() throws Exception {
        alice = connected(ALICE);
        subscribeAndWait(alice, ALICE, "c", "/topic/group/" + GROUP_A + "/chat");
        alice.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"content\":\"hi\"}");
        RawStompClient.Frame message = alice.nextOf("MESSAGE", WAIT);
        assertThat(message).isNotNull();
        assertThat(objectMapper.readTree(message.body()).get("senderId").asText()).isEqualTo(String.valueOf(ALICE));
    }

    @Test
    void quizSubmit_forAnotherUser_isForbidden() throws Exception {
        try (RawStompClient client = connected(ALICE)) {
            client.sendJson("/pub/group/" + GROUP_A + "/quiz/submit",
                    "{\"userId\":" + BOB + ",\"questionId\":5,\"submittedAnswer\":1,\"timeTakenSeconds\":3}");
            assertRejected(client, "FORBIDDEN", "IDENTITY_MISMATCH");
        }
        verify(quizSessionService, after(300).never()).submitAnswer(anyLong(), any());
    }

    @Test
    void quizSubmit_usesAuthenticatedUser() throws Exception {
        alice = connected(ALICE);
        alice.sendJson("/pub/group/" + GROUP_A + "/quiz/submit",
                "{\"userId\":\"" + ALICE + "\",\"questionId\":5,\"submittedAnswer\":1,\"timeTakenSeconds\":3}");
        ArgumentCaptor<GroupStudySocketDTO.AnswerSubmitPayload> captor = ArgumentCaptor.forClass(GroupStudySocketDTO.AnswerSubmitPayload.class);
        verify(quizSessionService, timeout(2000)).submitAnswer(eq(GROUP_A), captor.capture());
        assertThat(captor.getValue().getUserId()).isEqualTo(ALICE);
        assertThat(captor.getValue().getQuestionId()).isEqualTo(5L);
    }

    @Test
    void quizStart_forAnotherUser_isForbidden_andOwnStartUsesPrincipal() throws Exception {
        try (RawStompClient client = connected(ALICE)) {
            client.sendJson("/pub/group/" + GROUP_A + "/quiz/start", "{\"quizId\":7,\"userId\":" + BOB + "}");
            assertRejected(client, "FORBIDDEN", "IDENTITY_MISMATCH");
        }
        verify(quizSessionService, after(300).never()).startQuiz(anyLong(), anyLong(), anyLong());

        alice = connected(ALICE);
        alice.sendJson("/pub/group/" + GROUP_A + "/quiz/start", "{\"quizId\":7}");
        verify(quizSessionService, timeout(2000)).startQuiz(GROUP_A, 7L, ALICE);
    }

    @Test
    void quizStart_byNonMember_isForbidden() throws Exception {
        try (RawStompClient mallory = connected(MALLORY)) {
            mallory.sendJson("/pub/group/" + GROUP_A + "/quiz/start", "{\"quizId\":7,\"userId\":" + MALLORY + "}");
            assertRejected(mallory, "FORBIDDEN", "NOT_GROUP_MEMBER");
        }
        verify(quizSessionService, after(300).never()).startQuiz(anyLong(), anyLong(), anyLong());
    }

    // ── 탈퇴·강퇴·정지 후 차단 ────────────────────────────────────────────────

    @Test
    void kickedMember_isNotified_disconnected_andCannotResubscribe() throws Exception {
        alice = connected(ALICE);
        subscribeAndWait(alice, ALICE, "c", "/topic/group/" + GROUP_A + "/chat");
        subscribeAndWait(alice, ALICE, "m", "/topic/group/" + GROUP_A + "/members");
        bob = connected(BOB);
        subscribeAndWait(bob, BOB, "c", "/topic/group/" + GROUP_A + "/chat");
        subscribeAndWait(bob, BOB, "m", "/topic/group/" + GROUP_A + "/members");

        memberships.remove(GROUP_A + ":" + BOB); // 강퇴 커밋
        events.publishEvent(GroupAccessRevokedEvent.kicked(GROUP_A, BOB));

        RawStompClient.Frame notice = bob.nextOf("MESSAGE", WAIT);
        assertThat(notice).isNotNull();
        JsonNode event = objectMapper.readTree(notice.body());
        assertThat(event.get("type").asText()).isEqualTo("PARTICIPANT_KICKED");
        assertThat(event.get("targetUserId").asLong()).isEqualTo(BOB);
        assertRejected(bob, "FORBIDDEN", "MEMBERSHIP_REVOKED");

        // 남은 멤버는 연결이 유지되고 채팅이 계속 된다.
        assertThat(alice.nextOf("MESSAGE", WAIT)).as("ALICE also sees the kick notice").isNotNull();
        alice.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"content\":\"still here\"}");
        assertThat(alice.nextOf("MESSAGE", WAIT)).isNotNull();
        assertThat(alice.isOpen()).isTrue();

        // 재접속: 토큰이 유효하므로 CONNECT 는 되지만 그 그룹 구독은 등록되지 않고, 전송은 거부된다.
        try (RawStompClient again = connected(BOB)) {
            again.subscribe("c", "/topic/group/" + GROUP_A + "/chat");
            assertThat(again.nextOf("ERROR", QUIET)).isNull();
            alice.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"content\":\"after kick\"}");
            assertThat(alice.nextOf("MESSAGE", WAIT)).as("ALICE still receives").isNotNull();
            assertThat(again.nextOf("MESSAGE", QUIET)).as("kicked BOB receives nothing after resubscribe").isNull();
            assertThat(userRegistry.findSubscriptions(sub -> String.valueOf(BOB).equals(sub.getSession().getUser().getName())))
                    .isEmpty();
        }
        try (RawStompClient again = connected(BOB)) {
            again.sendJson("/pub/group/" + GROUP_A + "/chat", "{\"senderId\":" + BOB + ",\"content\":\"let me in\"}");
            assertRejected(again, "FORBIDDEN", "NOT_GROUP_MEMBER");
        }
    }

    @Test
    void leftMember_sessionIsClosed_otherGroupsSessionsUntouched() throws Exception {
        memberships.add(GROUP_B + ":" + BOB);
        bob = connected(BOB);
        subscribeAndWait(bob, BOB, "c", "/topic/group/" + GROUP_A + "/chat");
        try (RawStompClient bobOtherRoom = connected(BOB)) {
            subscribeAndWait(bobOtherRoom, BOB, "c2", "/topic/group/" + GROUP_B + "/chat");

            memberships.remove(GROUP_A + ":" + BOB);
            events.publishEvent(GroupAccessRevokedEvent.left(GROUP_A, BOB));

            assertRejected(bob, "FORBIDDEN", "MEMBERSHIP_REVOKED");
            assertThat(bobOtherRoom.nextOf("ERROR", QUIET)).as("group B session stays open").isNull();
            assertThat(bobOtherRoom.isOpen()).isTrue();
        }
    }

    @Test
    void deletedGroup_closesEverySubscriber() throws Exception {
        alice = connected(ALICE);
        subscribeAndWait(alice, ALICE, "c", "/topic/group/" + GROUP_A + "/chat");
        bob = connected(BOB);
        subscribeAndWait(bob, BOB, "c", "/topic/group/" + GROUP_A + "/chat");

        memberships.removeIf(m -> m.startsWith(GROUP_A + ":"));
        events.publishEvent(GroupAccessRevokedEvent.groupDeleted(GROUP_A));

        assertRejected(alice, "FORBIDDEN", "MEMBERSHIP_REVOKED");
        assertRejected(bob, "FORBIDDEN", "MEMBERSHIP_REVOKED");
    }

    @Test
    void suspendedOrBannedUser_allSessionsClosed_andReconnectRejected() throws Exception {
        alice = connected(ALICE);
        subscribeAndWait(alice, ALICE, "c", "/topic/group/" + GROUP_A + "/chat");

        stubUser(ALICE, "alice@studybridge.test", "앨리스", "BANNED");
        events.publishEvent(new UserAccessRevokedEvent(ALICE));
        assertRejected(alice, "FORBIDDEN", "ACCOUNT_REVOKED");

        stubUser(ALICE, "alice@studybridge.test", "앨리스", "SUSPENDED");
        User suspended = userRepository.findById(ALICE).orElseThrow();
        suspended.setSuspensionEndDate(LocalDateTime.now().plusDays(3));
        try (RawStompClient again = RawStompClient.open(port).connect("Bearer " + tokenOf(ALICE))) {
            assertRejected(again, "FORBIDDEN", "USER_INACTIVE");
        }
    }

    // ── 정상 흐름 회귀 ────────────────────────────────────────────────────────

    @Test
    void member_canSubscribeAllRoomTopics_likeWebAndAndroidClients() throws Exception {
        alice = connected(ALICE);
        String[] channels = {"chat", "members", "quiz/session", "quiz/question", "quiz/next", "quiz/timer",
                "quiz/submitted", "quiz/reveal", "quiz/scoreboard", "quiz/end", "quiz/error"};
        for (int i = 0; i < channels.length; i++) {
            subscribeAndWait(alice, ALICE, "s" + i, "/topic/group/" + GROUP_A + "/" + channels[i]);
        }
        assertThat(alice.nextOf("ERROR", QUIET)).isNull();
        assertThat(alice.isOpen()).isTrue();
    }
}
