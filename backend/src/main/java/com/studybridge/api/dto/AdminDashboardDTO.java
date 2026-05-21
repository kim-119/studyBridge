package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;

@Getter
@Builder
public class AdminDashboardDTO {
    private long totalUserCount;
    private long todayNewUserCount;
    private long totalMaterialCount;
    private long totalTodoCount;
}