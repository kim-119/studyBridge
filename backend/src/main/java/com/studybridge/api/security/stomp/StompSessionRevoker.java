package com.studybridge.api.security.stomp;

import jakarta.annotation.PreDestroy;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.simp.user.SimpSession;
import org.springframework.messaging.simp.user.SimpSubscription;
import org.springframework.messaging.simp.user.SimpUser;
import org.springframework.messaging.simp.user.SimpUserRegistry;
import org.springframework.messaging.support.MessageBuilder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.event.TransactionPhase;
import org.springframework.transaction.event.TransactionalEventListener;

import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

/**
 * 접근권이 사라진 사용자의 열린 STOMP 세션을 닫는다. 구독은 SUBSCRIBE 시점에만 검사되므로, 탈퇴·강퇴 뒤에도
 * 이미 열린 구독으로 채팅·퀴즈를 계속 받는 것을 막는다(재연결·재구독은 인터셉터가 거부).
 *
 * <ol>
 *   <li>탈퇴·강퇴: 그룹 members 토픽에 {@code PARTICIPANT_LEFT}/{@code PARTICIPANT_KICKED} 를 보낸다 — 기존 웹·Android 가
 *       이미 이 이벤트로 본인이면 방을 닫고, 다른 사람이면 화상 타일·참여자 목록에서 지운다.</li>
 *   <li>{@value #DEFAULT_CLOSE_DELAY_MS}ms 뒤 그 그룹을 구독한 그 사용자의 세션에 ERROR(FORBIDDEN, MEMBERSHIP_REVOKED) 를
 *       보낸다. Spring 은 ERROR 전송 후 세션을 닫는다. 지연은 위 이벤트가 먼저 도착하게 하기 위함이다.</li>
 * </ol>
 * 서비스 트랜잭션이 커밋된 뒤에만 실행한다(롤백된 강퇴로 세션을 끊지 않는다).
 */
@Component
@Slf4j
public class StompSessionRevoker {

    static final long DEFAULT_CLOSE_DELAY_MS = 1000;

    private final SimpUserRegistry userRegistry;
    private final MessageChannel clientOutboundChannel;
    private final SimpMessagingTemplate messagingTemplate;
    private final ScheduledExecutorService scheduler;
    private volatile long closeDelayMs = DEFAULT_CLOSE_DELAY_MS;

    public StompSessionRevoker(SimpUserRegistry userRegistry,
                               @Qualifier("clientOutboundChannel") MessageChannel clientOutboundChannel,
                               SimpMessagingTemplate messagingTemplate) {
        this.userRegistry = userRegistry;
        this.clientOutboundChannel = clientOutboundChannel;
        this.messagingTemplate = messagingTemplate;
        this.scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "stomp-revoker");
            thread.setDaemon(true);
            return thread;
        });
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onGroupAccessRevoked(GroupAccessRevokedEvent event) {
        long groupId = event.groupId();
        Long userId = event.userId();
        if (userId != null && event.reason() != GroupAccessRevokedEvent.Reason.GROUP_DELETED) {
            Map<String, Object> notice = new LinkedHashMap<>();
            notice.put("type", event.reason() == GroupAccessRevokedEvent.Reason.KICKED ? "PARTICIPANT_KICKED" : "PARTICIPANT_LEFT");
            notice.put("groupId", groupId);
            notice.put("targetUserId", userId);
            notice.put("occurredAt", LocalDateTime.now().toString());
            try {
                messagingTemplate.convertAndSend("/topic/group/" + groupId + "/members", notice);
            } catch (Exception e) {
                log.warn("[stomp-auth] members notice failed groupId={} userId={} reason={}", groupId, userId, e.getMessage());
            }
        }
        scheduler.schedule(() -> closeGroupSessions(groupId, userId), closeDelayMs, TimeUnit.MILLISECONDS);
    }

    @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
    public void onUserAccessRevoked(UserAccessRevokedEvent event) {
        SimpUser user = userRegistry.getUser(String.valueOf(event.userId()));
        Set<String> sessionIds = user == null ? Set.of()
                : user.getSessions().stream().map(SimpSession::getId).collect(Collectors.toSet());
        sessionIds.forEach(id -> sendError(id, StompAuthException.ACCOUNT_REVOKED));
        log.info("[stomp-auth] account revoked userId={} closedSessions={}", event.userId(), sessionIds.size());
    }

    /** 그 그룹 토픽을 구독한 세션(userId 가 null 이면 모든 사용자)에 ERROR 를 보내 닫는다. 닫은 세션 수를 돌려준다. */
    int closeGroupSessions(long groupId, Long userId) {
        String prefix = StompDestinationPolicy.groupTopicPrefix(groupId);
        String userName = userId == null ? null : String.valueOf(userId);
        Set<String> sessionIds;
        try {
            sessionIds = userRegistry.findSubscriptions(subscription -> isTarget(subscription, prefix, userName))
                    .stream()
                    .map(subscription -> subscription.getSession().getId())
                    .collect(Collectors.toSet());
        } catch (Exception e) {
            log.warn("[stomp-auth] revoke lookup failed groupId={} userId={} reason={}", groupId, userId, e.getMessage());
            return 0;
        }
        sessionIds.forEach(id -> sendError(id, StompAuthException.MEMBERSHIP_REVOKED));
        log.info("[stomp-auth] group access revoked groupId={} userId={} closedSessions={}",
                groupId, userId == null ? "*" : userId, sessionIds.size());
        return sessionIds.size();
    }

    private static boolean isTarget(SimpSubscription subscription, String prefix, String userName) {
        String destination = subscription.getDestination();
        if (destination == null || !destination.startsWith(prefix)) {
            return false;
        }
        return userName == null || userName.equals(subscription.getSession().getUser().getName());
    }

    private void sendError(String sessionId, String reason) {
        StompHeaderAccessor accessor = StompHeaderAccessor.create(StompCommand.ERROR);
        accessor.setMessage(StompAuthException.FORBIDDEN);
        accessor.setNativeHeader(StompAuthErrorHandler.REASON_HEADER, reason);
        accessor.setSessionId(sessionId);
        accessor.setLeaveMutable(true);
        byte[] body = (StompAuthException.FORBIDDEN + " " + reason).getBytes(StandardCharsets.UTF_8);
        try {
            clientOutboundChannel.send(MessageBuilder.createMessage(body, accessor.getMessageHeaders()));
        } catch (Exception e) {
            log.warn("[stomp-auth] session close failed session={} reason={}", sessionId, e.getMessage());
        }
    }

    void setCloseDelayMs(long closeDelayMs) {
        this.closeDelayMs = Math.max(0, closeDelayMs);
    }

    @PreDestroy
    void shutdown() {
        scheduler.shutdownNow();
    }
}
