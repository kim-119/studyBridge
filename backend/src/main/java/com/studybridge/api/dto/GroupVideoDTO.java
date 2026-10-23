package com.studybridge.api.dto;

/**
 * 그룹 화상통화(OpenVidu) API 요청 본문. 응답은 계약 필드가 명시된 Map(JSON) 으로 낸다 — GroupVideoCallService 참고.
 */
public class GroupVideoDTO {

    private GroupVideoDTO() {}

    /**
     * POST /api/groups/{id}/video/token 본문(선택). 본문 없이 호출해도 기존처럼 동작한다.
     * @param clientInstanceId 탭/앱 인스턴스 식별자(웹=sessionStorage, 새로고침해도 유지). [A-Za-z0-9_-]{8,64}
     * @param deviceType       WEB | ANDROID | IOS (그 외 UNKNOWN)
     */
    public record TokenRequest(String clientInstanceId, String deviceType) {}
}
