package com.studybridge.api.entity;

/**
 * 공부 세션(timers) 종료 사유. 통계에서는 사유와 무관하게 서버 시각 기준 구간만 사용한다.
 *  · USER_STOP: 사용자가 종료 버튼/방 나가기 등으로 명시 종료(클라이언트 reason 문자열은 참고용 로그)
 *  · NEW_SESSION: 다른 컨텍스트(다른 그룹/개인)에서 새 세션을 시작하며 자동 종료
 *  · HEARTBEAT_TIMEOUT: heartbeat 가 끊겨 reaper 가 마지막 heartbeat 시각으로 종료(비정상 종료 fallback)
 *  · STALE_NO_HEARTBEAT: heartbeat 를 지원하지 않는 구 클라이언트 세션이 24시간 넘게 남아 CANCELLED 처리(공부시간 미상)
 */
public enum TimerEndReason {
    USER_STOP,
    NEW_SESSION,
    HEARTBEAT_TIMEOUT,
    STALE_NO_HEARTBEAT
}
