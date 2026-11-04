package com.studybridge.api.security.stomp;

/**
 * 그룹 실시간 채널 접근권이 사라졌다(탈퇴·강퇴·그룹 삭제). 커밋 뒤 {@link StompSessionRevoker} 가 그 사용자의
 * 해당 그룹 구독 세션을 닫는다. userId 가 null 이면 그룹 전체(그룹 삭제).
 */
public record GroupAccessRevokedEvent(long groupId, Long userId, Reason reason) {

    public enum Reason {
        LEFT,
        KICKED,
        GROUP_DELETED
    }

    public static GroupAccessRevokedEvent left(long groupId, long userId) {
        return new GroupAccessRevokedEvent(groupId, userId, Reason.LEFT);
    }

    public static GroupAccessRevokedEvent kicked(long groupId, long userId) {
        return new GroupAccessRevokedEvent(groupId, userId, Reason.KICKED);
    }

    public static GroupAccessRevokedEvent groupDeleted(long groupId) {
        return new GroupAccessRevokedEvent(groupId, null, Reason.GROUP_DELETED);
    }
}
