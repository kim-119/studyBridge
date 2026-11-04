package com.studybridge.api.security.stomp;

import org.springframework.messaging.Message;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.MessageHeaderAccessor;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.messaging.StompSubProtocolErrorHandler;

import java.nio.charset.StandardCharsets;

/**
 * 클라이언트 프레임 처리 실패를 ERROR 프레임으로 바꾼다. Spring 은 ERROR 를 보낸 뒤 그 WebSocket 세션을 닫는다.
 *
 * <ul>
 *   <li>인증·인가 거부: {@code message} 헤더 = {@code UNAUTHORIZED} 또는 {@code FORBIDDEN}, {@code sb-reason} 헤더 = 세부 사유.</li>
 *   <li>그 밖의 실패: {@code message} = {@code BAD_REQUEST}. 내부 예외 메시지(채널 이름 등)는 내보내지 않는다.</li>
 * </ul>
 */
@Component
public class StompAuthErrorHandler extends StompSubProtocolErrorHandler {

    public static final String REASON_HEADER = "sb-reason";
    static final String BAD_REQUEST = "BAD_REQUEST";

    @Override
    public Message<byte[]> handleClientMessageProcessingError(Message<byte[]> clientMessage, Throwable ex) {
        StompHeaderAccessor errorAccessor = StompHeaderAccessor.create(StompCommand.ERROR);
        StompAuthException denied = findAuthException(ex);
        String body;
        if (denied != null) {
            errorAccessor.setMessage(denied.getCode());
            errorAccessor.setNativeHeader(REASON_HEADER, denied.getReason());
            body = denied.getCode() + " " + denied.getReason();
        } else {
            errorAccessor.setMessage(BAD_REQUEST);
            body = BAD_REQUEST;
        }
        errorAccessor.setLeaveMutable(true);

        StompHeaderAccessor clientAccessor = clientMessage == null ? null
                : MessageHeaderAccessor.getAccessor(clientMessage, StompHeaderAccessor.class);
        return handleInternal(errorAccessor, body.getBytes(StandardCharsets.UTF_8), ex, clientAccessor);
    }

    static StompAuthException findAuthException(Throwable ex) {
        Throwable current = ex;
        for (int depth = 0; current != null && depth < 8; depth++) {
            if (current instanceof StompAuthException denied) {
                return denied;
            }
            current = current.getCause();
        }
        return null;
    }
}
