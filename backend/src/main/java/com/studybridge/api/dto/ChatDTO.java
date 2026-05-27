package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.ToString;

import java.time.LocalDateTime;
import java.util.List;

public class ChatDTO {

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MessageResponse {
        private Long id;
        private String content;
        private String sender;
        private String senderName;
        private Long agentId;
        private LocalDateTime createdAt;
    }

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @ToString
    public static class MultiChatRequest {
        private String message;
        private Long agentId;
        private Long roomId;
        private String mode;
        private Integer rounds;
        private Boolean showFinalSynthesis;
        private List<RequestAgent> agents;
        private String personality;
        private String style;
        private String tone;
        private String knowledgeLevel;
        private String knowledge_level;
        private String customInstruction;
        private String custom_instruction;
        private String persona;
    }

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @ToString
    public static class RequestAgent {
        private String agentId;
        private String id;
        private String name;
        private String role;
        private String personality;
        private String style;
        private String tone;
        private String knowledgeLevel;
        private String knowledge_level;
        private String customInstruction;
        private String custom_instruction;
        private String persona;
    }

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MultiChatResponse {
        private String mode;
        private List<DiscussionMessage> messages;
        private String finalSynthesis;
        private List<AgentReply> replies;
    }

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class DiscussionMessage {
        private String id;
        private Integer round;
        private String agentId;
        private String agentName;
        private String role;
        private String personality;
        private String knowledgeLevel;
        private String speechType;
        private String targetAgentId;
        private String content;
    }

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AgentReply {
        private Long agentId;
        private String agentName;
        private String answer;
    }
}
