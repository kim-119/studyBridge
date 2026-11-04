package com.studybridge.api.security.stomp;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;

/**
 * 그룹스터디 STOMP 인바운드 게이트(clientInboundChannel).
 *
 * <ol>
 *   <li>CONNECT: {@code Authorization: Bearer <JWT>} 필수. 서명·만료·체험 계정 기기 슬롯·계정 상태를 확인하고
 *       {@link StompPrincipal} 을 세션 사용자로 지정한다. 실패하면 ERROR 프레임 후 연결 종료.</li>
 *   <li>SUBSCRIBE: 허용 목록({@link StompDestinationPolicy}) 의 그룹 토픽만, 그 그룹의 JOINED 멤버만.
 *       거부된 구독은 등록하지 않고 버린다(연결 유지 — 구버전 Android 재연결 폭주 방지, {@code authorizeSubscribe} 참고).</li>
 *   <li>SEND: {@code /pub/group/{id}/(chat|quiz/start|quiz/submit)} 만, 그 그룹의 JOINED 멤버만.
 *       payload 에 userId/senderId 가 있으면 인증 사용자와 같아야 한다(다르면 사칭 시도로 거부). 컨트롤러는 Principal 만 쓴다.</li>
 * </ol>
 * 멤버 여부는 매 프레임 RDS 로 확인한다(탈퇴·강퇴 직후 재연결·재구독 차단). 거부 로그에는 본문·토큰을 남기지 않는다.
 */
@Component
@Slf4j
public class StompAuthChannelInterceptor implements ChannelInterceptor {

    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtTokenProvider jwtTokenProvider;
    private final ExhibitSessionService exhibitSessionService;
    private final UserRepository userRepository;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final ObjectMapper objectMapper;

    public StompAuthChannelInterceptor(JwtTokenProvider jwtTokenProvider,
                                       ExhibitSessionService exhibitSessionService,
                                       UserRepository userRepository,
                                       GroupStudyMemberRepository groupStudyMemberRepository,
                                       ObjectMapper objectMapper) {
        this.jwtTokenProvider = jwtTokenProvider;
        this.exhibitSessionService = exhibitSessionService;
        this.userRepository = userRepository;
        this.groupStudyMemberRepository = groupStudyMemberRepository;
        this.objectMapper = objectMapper;
    }

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor accessor = MessageHeaderAccessor.getAccessor(message, StompHeaderAccessor.class);
        if (accessor == null || accessor.getCommand() == null) {
            return message; // heartbeat 등 STOMP 명령이 없는 프레임
        }
        StompCommand command = accessor.getCommand();
        try {
            switch (command) {
                case CONNECT, STOMP -> authenticate(accessor);
                case SUBSCRIBE -> {
                    if (!authorizeSubscribe(accessor)) {
                        return null; // 구독을 등록하지 않는다(브로커에 전달하지 않음). 연결은 유지.
                    }
                }
                case SEND -> authorizeSend(accessor, message);
                case UNSUBSCRIBE, DISCONNECT -> {
                    // 구독 해제·연결 종료는 누구에게나 허용한다.
                }
                default -> requirePrincipal(accessor); // ACK/NACK/BEGIN/COMMIT/ABORT
            }
        } catch (StompAuthException denied) {
            logDenied(command, accessor, denied);
            throw denied;
        }
        return message;
    }

    private void authenticate(StompHeaderAccessor accessor) {
        String token = resolveBearerToken(accessor);
        if (token == null) {
            throw StompAuthException.unauthorized(StompAuthException.TOKEN_MISSING);
        }
        // 서명 불일치(위조)·만료·형식 오류는 모두 false.
        if (!jwtTokenProvider.validateToken(token)) {
            throw StompAuthException.unauthorized(StompAuthException.TOKEN_INVALID);
        }
        JwtTokenProvider.TokenClaims claims = jwtTokenProvider.getTokenClaims(token);
        if (claims.userId() == null || !StringUtils.hasText(claims.email())) {
            throw StompAuthException.unauthorized(StompAuthException.TOKEN_INVALID);
        }
        // 체험 계정은 기기 슬롯이 살아 있어야 한다(REST JwtAuthenticationFilter 와 같은 규칙). 일반 사용자는 항상 true.
        if (!exhibitSessionService.allowsAccess(claims.email(), claims.userId(), claims.sessionId())) {
            throw StompAuthException.unauthorized(StompAuthException.SESSION_EXPIRED);
        }
        User user = userRepository.findById(claims.userId())
                .filter(found -> found.getEmail() != null && found.getEmail().equalsIgnoreCase(claims.email()))
                .orElseThrow(() -> StompAuthException.unauthorized(StompAuthException.USER_NOT_FOUND));
        if (isInactive(user)) {
            throw StompAuthException.forbidden(StompAuthException.USER_INACTIVE);
        }

        accessor.setUser(new StompPrincipal(user.getId(), user.getEmail()));
        log.info("[stomp-auth] CONNECT accepted userId={} session={}", user.getId(), accessor.getSessionId());
    }

    /**
     * 인증된 세션의 무단 구독은 ERROR 로 끊지 않고 버린다(false). 이미 배포된 Android 앱(1.8 이하)은 CONNECTED 마다
     * 재시도 횟수를 0 으로 되돌리므로, 구독 거부로 연결을 끊으면 약 1초 간격으로 끝없이 재연결한다(격리 E2E 실측).
     * 구독이 등록되지 않으므로 수신 차단 효과는 같다. 인증 전 SUBSCRIBE 는 ERROR(UNAUTHORIZED).
     */
    private boolean authorizeSubscribe(StompHeaderAccessor accessor) {
        StompPrincipal principal = requirePrincipal(accessor);
        try {
            StompDestinationPolicy.GroupDestination destination = StompDestinationPolicy
                    .subscribable(accessor.getDestination())
                    .orElseThrow(() -> StompAuthException.forbidden(StompAuthException.DESTINATION_NOT_ALLOWED));
            requireGroupMember(principal, destination.groupId());
            return true;
        } catch (StompAuthException denied) {
            logDenied(StompCommand.SUBSCRIBE, accessor, denied);
            return false;
        }
    }

    private void authorizeSend(StompHeaderAccessor accessor, Message<?> message) {
        StompPrincipal principal = requirePrincipal(accessor);
        StompDestinationPolicy.GroupDestination destination = StompDestinationPolicy
                .sendable(accessor.getDestination())
                .orElseThrow(() -> StompAuthException.forbidden(StompAuthException.DESTINATION_NOT_ALLOWED));
        requireGroupMember(principal, destination.groupId());
        requireClaimedIdentityMatches(principal, destination.channel(), message.getPayload());
    }

    private StompPrincipal requirePrincipal(StompHeaderAccessor accessor) {
        if (accessor.getUser() instanceof StompPrincipal principal) {
            return principal;
        }
        throw StompAuthException.unauthorized(StompAuthException.NOT_AUTHENTICATED);
    }

    private void requireGroupMember(StompPrincipal principal, long groupId) {
        boolean member = groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupId, principal.userId(), GroupStudyMemberStatus.JOINED);
        if (!member) {
            throw StompAuthException.forbidden(StompAuthException.NOT_GROUP_MEMBER);
        }
    }

    /**
     * 기존 웹·Android 클라이언트는 payload 에 자기 userId(채팅은 senderId)를 계속 보낸다 — 값이 인증 사용자와 같으면 통과.
     * 다른 값이면 사칭 시도이므로 메시지를 처리하지 않는다. 비어 있으면(신규 클라이언트) 통과. 실제 식별은 컨트롤러가 Principal 로 한다.
     */
    private void requireClaimedIdentityMatches(StompPrincipal principal, String channel, Object payload) {
        String field = "chat".equals(channel) ? "senderId" : "userId";
        JsonNode body = readJsonObject(payload);
        JsonNode claimed = body.get(field);
        if (claimed == null || claimed.isNull()) {
            return;
        }
        if (!claimed.isValueNode() || !String.valueOf(principal.userId()).equals(claimed.asText().trim())) {
            throw StompAuthException.forbidden(StompAuthException.IDENTITY_MISMATCH);
        }
    }

    private JsonNode readJsonObject(Object payload) {
        if (!(payload instanceof byte[] bytes) || bytes.length == 0) {
            throw StompAuthException.forbidden(StompAuthException.MALFORMED_PAYLOAD);
        }
        try {
            JsonNode node = objectMapper.readTree(bytes);
            if (node == null || !node.isObject()) {
                throw StompAuthException.forbidden(StompAuthException.MALFORMED_PAYLOAD);
            }
            return node;
        } catch (java.io.IOException e) {
            throw StompAuthException.forbidden(StompAuthException.MALFORMED_PAYLOAD);
        }
    }

    // UserService 로그인·리프레시와 같은 기준: 영구 정지, 또는 정지 만료 전의 일시 정지.
    private static boolean isInactive(User user) {
        if ("BANNED".equals(user.getStatus())) {
            return true;
        }
        return "SUSPENDED".equals(user.getStatus())
                && user.getSuspensionEndDate() != null
                && user.getSuspensionEndDate().isAfter(LocalDateTime.now());
    }

    private static String resolveBearerToken(StompHeaderAccessor accessor) {
        String header = accessor.getFirstNativeHeader("Authorization");
        if (header == null) {
            header = accessor.getFirstNativeHeader("authorization");
        }
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = header.substring(BEARER_PREFIX.length()).trim();
        return token.isEmpty() ? null : token;
    }

    private static void logDenied(StompCommand command, StompHeaderAccessor accessor, StompAuthException denied) {
        Object user = accessor.getUser() instanceof StompPrincipal principal ? principal.userId() : "-";
        log.warn("[stomp-auth] DENY command={} code={} reason={} userId={} session={} destination={}",
                command, denied.getCode(), denied.getReason(), user, accessor.getSessionId(),
                sanitizeDestination(accessor.getDestination()));
    }

    // 목적지는 클라이언트가 정한 문자열이라 로그 주입(개행)·과도한 길이를 막는다.
    static String sanitizeDestination(String destination) {
        if (destination == null) {
            return "-";
        }
        String cleaned = destination.replaceAll("[\\r\\n\\t]", "_");
        return cleaned.length() > 120 ? cleaned.substring(0, 120) + "…" : cleaned;
    }
}
