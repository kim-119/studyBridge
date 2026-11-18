package com.studybridge.api.dto;

import com.studybridge.api.entity.TimerEndReason;
import com.studybridge.api.entity.TimerStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

public class TimerDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class StartRequest {
        private LocalDateTime startTime; // (하위 호환) 서버는 무시하고 서버 시각을 사용한다
        private Long groupStudyId; // 선택 연동할 그룹스터디 ID
        // true: 클라이언트가 30초 heartbeat 를 보낸다 → 서버 reaper 가 timeout 시 마지막 heartbeat 시각으로 종료해 준다.
        // false/미전송(구 클라이언트): heartbeat 없음 → timeout 정리 대상이 아님(24h 좀비 정리만).
        private boolean supportsHeartbeat;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class EndRequest {
        private LocalDateTime endTime;    // (하위 호환) 서버는 무시
        private Long durationSeconds;     // (하위 호환) 서버는 무시 — duration 은 서버 시각 endTime-startTime
        private String reason;            // 참고용 로그(예: ROOM_LEAVE, PAGE_HIDE, USER_STOP)
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long userId;
        private Long groupStudyId; // 연동된 그룹스터디 ID
        private LocalDateTime startTime;
        private LocalDateTime endTime;
        private Long durationSeconds;
        private TimerStatus status;
        private LocalDateTime lastHeartbeatAt;      // 이 시각까지 출석 원장에 크레딧됨
        private TimerEndReason endReason;
        private Integer heartbeatIntervalSeconds;   // 클라이언트 권장 heartbeat 간격(30)
        private Boolean resumed;                    // true = 기존 활성 세션 재사용(멱등 START)
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }

    // --- 추가된 DTO ---

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class TodayStudyTimeResponse {
        private Long userId;
        private Long todaySeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class WeeklyStudyTimeResponse {
        private Long userId;
        private Long totalSeconds; // 총 공부 시간 (초)
        private Long averageSeconds; // 평균 공부 시간 (초)
        private Integer attendanceDays; // 출석일 수 추가
        private List<DailyStudyTime> dailyStats; // data 필드명을 dailyStats로 변경
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class DailyStudyTime {
        private String date; // 날짜 추가 (YYYY-MM-DD)
        private String day; // 요일 (MONDAY, TUESDAY...)
        private Long seconds; // 해당 요일의 학습 시간 (초)
    }
}
