package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.ToString;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

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
        // 학습 진행 모드: basic / socratic / debate (미지정 시 FastAPI에서 basic으로 처리)
        private String learningMode;
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
        // 특정 에이전트 지칭 (@에이전트이름 또는 N번만 답해줘)
        private String targetAgentId;
        // 그룹스터디 AI 봇(요약/퀴즈/검색) 필드
        private String rawMessage;      // 슬래시 명령어 포함 원본 메시지 (서버 2차 파싱용)
        private String botType;         // summary_bot | quiz_bot | search_bot
        private String agentName;       // SummaryAgent | QuizAgent | TavilyAgent
        private String runMode;         // single | all_bots
        private Long studyRoomId;
        private String roomTitle;
        private Boolean stream;
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
        private String personalityStrength;
        private String personality_strength;
        private String style;
        private String tone;
        private String knowledgeLevel;
        private String knowledge_level;
        private String customInstruction;
        private String custom_instruction;
        private String persona;
        // 그룹스터디 AI 봇 식별 필드
        private String botType;
        private String displayName;
        private String modelProvider;
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
        // 1차/2차/3차 생성 과정 (FastAPI processSteps를 그대로 패스스루, 없으면 null)
        private Map<String, Object> processSteps;
        // 에러/타임아웃 시 프론트에 메시지 전달 (500 대신 200+errorMessage 반환)
        private String errorMessage;
        private String errorCode;
        private Boolean success;
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
        private String personalityStrength;
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
