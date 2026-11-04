package com.studybridge.api.security.stomp;

/** 계정 정지(일시·영구)로 그 사용자의 모든 STOMP 세션을 닫는다. 재연결은 CONNECT 의 계정 상태 검사에서 거부된다. */
public record UserAccessRevokedEvent(long userId) {
}
