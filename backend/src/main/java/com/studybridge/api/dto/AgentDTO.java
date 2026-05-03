package com.studybridge.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;

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
    }

    @Getter
    @Setter
    public static class ChatRequest {
        @NotBlank(message = "메시지를 입력해주세요.")
        private String message;
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
