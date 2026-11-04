package com.studybridge.api.security.stomp;

import java.security.Principal;

/**
 * STOMP CONNECT 때 JWT 로 인증한 사용자. 같은 WebSocket 세션의 이후 모든 프레임에 붙는다.
 * 이름은 userId 문자열이다(SimpUserRegistry 조회 키). 권한 판정은 이 값으로만 하고 payload 의 userId/senderId 는 쓰지 않는다.
 */
public record StompPrincipal(long userId, String email) implements Principal {

    @Override
    public String getName() {
        return String.valueOf(userId);
    }

    /** STOMP 핸들러 인자로 받은 Principal 을 꺼낸다. 인터셉터를 거치지 않은 메시지라면 거부한다. */
    public static StompPrincipal require(Principal principal) {
        if (principal instanceof StompPrincipal stompPrincipal) {
            return stompPrincipal;
        }
        throw StompAuthException.unauthorized(StompAuthException.NOT_AUTHENTICATED);
    }

    // 로그에 이메일이 남지 않게 한다.
    @Override
    public String toString() {
        return "StompPrincipal[userId=" + userId + "]";
    }
}
