package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;
import java.util.Map;

@Getter
@Builder
public class AdminDashboardDTO {
    private long totalUserCount;
    private long todayNewUserCount;
    private long bannedUserCount;
    private Map<String, Long> majorDistribution;
}