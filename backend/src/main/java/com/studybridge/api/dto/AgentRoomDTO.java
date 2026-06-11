package com.studybridge.api.dto;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Size;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;

import java.util.List;

public class AgentRoomDTO {

    @Getter
    @Setter
    public static class CreateRequest {
        @NotBlank(message = "채팅방 이름은 필수입니다.")
        @Size(min = 1, max = 100)
        private String roomName;

        // 학습 진행 모드 (basic/socratic/debate/simulation). 미지정 시 basic.
        private String learningMode;

        // 모드별 설정 (토론/소크라테스/상황극). 현재는 per-message로 FastAPI에 전달되며, 방 단위 영속화는 미지원.
        private java.util.Map<String, Object> debateConfig;
        private java.util.Map<String, Object> socraticConfig;
        private java.util.Map<String, Object> simulationConfig;

        // 검증 상한은 10명(PREMIUM/ROOT 대비). 실제 플랜별 제한은 Service.resolveAgentLimit에서 적용한다.
        @NotEmpty(message = "최소 1명 이상의 에이전트를 생성해야 합니다.")
        @Size(max = 10, message = "에이전트는 최대 10명까지만 생성할 수 있습니다.")
        @Valid
        private List<AgentDTO.CreateRequest> agents;
    }

    @Getter
    @Setter
    @Builder
    public static class Response {
        private Long roomId;
        private String roomName;
        // 방에 저장된 학습 진행 모드 (프론트 selectAgent에서 라디오 상태 복원에 사용)
        private String learningMode;
        private List<AgentDTO.Response> agents;
        private String createdAt;
    }
}
