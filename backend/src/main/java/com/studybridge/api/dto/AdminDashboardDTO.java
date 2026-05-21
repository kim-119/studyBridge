package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;
import java.util.Map;

@Getter
@Builder
public class AdminDashboardDTO {
    private long totalUserCount;
    private long todayNewUserCount;
    private long totalMaterialCount;
    private long totalTodoCount;

    // 추가된 고급 통계
    private long subscribedUserCount;
    private long bannedUserCount;
    private Map<String, Long> majorDistribution;
}