package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/** 학습 추천(사용자 플래너 Task / 로드맵 Node / 문서 기반) API DTO. */
public class LearningRecommendationDTO {

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Item {
        private Long id;
        private String sourceKind;          // USER_PLANNER | ROADMAP_PLANNER | DOCUMENT
        private String type;
        private String title;
        private String reason;
        private List<Map<String, String>> evidence;   // [{type, id, label}]
        private boolean verificationRequired;
        private String verificationNote;
        private Map<String, Object> score;  // 로드맵 노드 순위 근거(eligibility, components, usedWeights, weightsValidated=false)
        private String generator;           // RULE | AI
        private String modelProvider;
        private String modelName;
        private String status;              // GENERATED | ACCEPTED | REJECTED | COMPLETED
        private Long plannerId;
        private Long materialId;
        private String targetKey;
        private Long acceptedPlannerId;
        private int presentedCount;
        private LocalDateTime createdAt;
        private LocalDateTime decidedAt;
        private LocalDateTime completedAt;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ListResponse {
        /** USER_PLANNER_TASK | ROADMAP_NODE | DOCUMENT */
        private String mode;
        /** OK | EMPTY | NO_DATA | ALL_COMPLETED */
        private String status;
        private String note;
        private Long plannerId;
        private Long materialId;
        private List<Item> items;
        /** 추천 근거 요약(체크리스트 진행·목차 확인·퀴즈 유무·그래프 노드 수 등). */
        private Map<String, Object> context;
        private boolean aiUsed;
        private int aiDiscarded;
        private String requestId;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AcceptRequest {
        /** 등록할 날짜(없으면 내일). */
        private LocalDate plannerDate;
        /** verificationRequired 추천은 사용자가 확인 필요 사항을 인지했다고 명시해야 승인된다. */
        private boolean acknowledgeVerification;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Metrics {
        private long presented;     // N_presented (DISCARDED 제외)
        private long accepted;      // N_accepted (ACCEPTED + COMPLETED)
        private long rejected;
        private long completed;
        private long discarded;     // AI 후보 중 EC2 검증 탈락
        private Double acceptanceRate;   // N_accepted / N_presented
        private Double completionRate;   // N_completed / N_accepted
        private Double duplicateRate;    // 재제시 횟수 / 총 제시 횟수
        private long aiCandidates;
        private Double hallucinationRate;   // 근거·목차·노드 불일치 탈락 / AI 후보
        private Double evidenceMatchRate;   // 검증 통과 AI 후보 / AI 후보
        private Map<String, Long> byType;
        private String note;
    }
}
