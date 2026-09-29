package com.studybridge.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

public class AgentDTO {

    @Getter
    @Setter
    public static class CreateRequest {
        @NotBlank(message = "이름은 필수 입력값입니다.")
        @Size(min = 1, max = 30)
        private String name;

        @NotBlank(message = "역할은 필수 입력값입니다.")
        @Size(min = 1, max = 50)
        private String role;

        @NotBlank(message = "페르소나는 필수 입력값입니다.")
        @Size(min = 5, max = 1000)
        private String persona;

        @Size(max = 100)
        private String tone;

        @Size(max = 200)
        private String goal;

        // 에이전트 역할/성격 프리셋 (learningMode와 별개): expert_professor 등
        private String agentPreset;
        private String personality;
        private String personalityStrength;
        private String personality_strength;
        private String knowledgeLevel;
        private String knowledge_level;
        private String customInstruction;
        private String custom_instruction;
    }

    @Getter
    @Setter
    @Builder
    public static class Response {
        private Long id;
        private String name;
        private String role;
        private String persona;
        private String tone;
        private String goal;
        // 페르소나 태그에서 복원된 프리셋/성격/지식수준 (프론트 복원용)
        private String agentPreset;
        private String personality;
        private String knowledgeLevel;
        private String customInstruction;
    }

    @Getter
    @Setter
    @ToString
    public static class ChatRequest {
        @NotBlank(message = "메시지를 입력해주세요.")
        private String message;
        private Long agentId;
        private Long roomId;
        private String personality;
        private String personalityStrength;
        private String personality_strength;
        private String style;
        private String tone;
        private String knowledgeLevel;
        private String knowledge_level;
        private String customInstruction;
        private String custom_instruction;
        private String persona;
    }

    @Getter
    @Setter
    @Builder
    public static class ChatResponse {
        private Long agentId;
        private String agentName;
        private String role;
        private String answer;
    }
}
