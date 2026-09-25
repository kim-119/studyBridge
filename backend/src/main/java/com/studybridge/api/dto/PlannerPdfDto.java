package com.studybridge.api.dto;

import lombok.*;
import java.util.List;

/** Resolved, persisted planner content used exclusively by the PDF renderer. */
@Getter @Setter @Builder @NoArgsConstructor @AllArgsConstructor
public class PlannerPdfDto {
    private Long plannerId;
    private String title;
    private Integer year, month, day, roadmapWeek, roadmapDay;
    private String dayOfWeek, term, studyType, priority, goalTime, dDay, subject;
    private String objective, memo, deliverable, timeTableJson;
    private List<String> tasks, reviewQuestions;
}
