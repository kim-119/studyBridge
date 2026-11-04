package com.studybridge.api.security.stomp;

import org.springframework.messaging.MessagingException;

/**
 * STOMP 인증·인가 거부. CONNECT·SEND 거부와 서버의 세션 차단(강퇴·탈퇴·정지)은 ERROR 프레임(message 헤더 = code,
 * sb-reason 헤더 = reason)으로 전달되고 연결은 서버가 닫는다. 인증된 세션의 무단 SUBSCRIBE 는 ERROR 없이 버린다.
 *
 * <p>code 는 클라이언트 동작 계약이다.
 * <ul>
 *   <li>{@link #UNAUTHORIZED}: 토큰 없음·위조·만료. 액세스 토큰을 갱신한 뒤 다시 연결한다.</li>
 *   <li>{@link #FORBIDDEN}: 그룹 멤버 아님·허용되지 않은 목적지·다른 사용자 사칭·정지 계정. 재연결해도 같으므로 멈춘다.</li>
 * </ul>
 * 메시지에는 code·reason 만 담는다(토큰·채팅 본문 등 사용자 값은 넣지 않는다 — Spring 이 이 메시지를 로그에 남긴다).
 */
public class StompAuthException extends MessagingException {

    public static final String UNAUTHORIZED = "UNAUTHORIZED";
    public static final String FORBIDDEN = "FORBIDDEN";

    public static final String TOKEN_MISSING = "TOKEN_MISSING";
    public static final String TOKEN_INVALID = "TOKEN_INVALID";
    public static final String SESSION_EXPIRED = "SESSION_EXPIRED";
    public static final String USER_NOT_FOUND = "USER_NOT_FOUND";
    public static final String USER_INACTIVE = "USER_INACTIVE";
    public static final String NOT_AUTHENTICATED = "NOT_AUTHENTICATED";
    public static final String DESTINATION_NOT_ALLOWED = "DESTINATION_NOT_ALLOWED";
    public static final String NOT_GROUP_MEMBER = "NOT_GROUP_MEMBER";
    public static final String IDENTITY_MISMATCH = "IDENTITY_MISMATCH";
    public static final String MALFORMED_PAYLOAD = "MALFORMED_PAYLOAD";
    public static final String MEMBERSHIP_REVOKED = "MEMBERSHIP_REVOKED";
    public static final String ACCOUNT_REVOKED = "ACCOUNT_REVOKED";

    private final String code;
    private final String reason;

    public StompAuthException(String code, String reason) {
        super(code + " " + reason);
        this.code = code;
        this.reason = reason;
    }

    public static StompAuthException unauthorized(String reason) {
        return new StompAuthException(UNAUTHORIZED, reason);
    }

    public static StompAuthException forbidden(String reason) {
        return new StompAuthException(FORBIDDEN, reason);
    }

    public String getCode() {
        return code;
    }

    public String getReason() {
        return reason;
    }
}
