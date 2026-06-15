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
        // 영속화된 1차/2차/3차 생성 과정 (AI 메시지에만 존재, 없으면 null)
        private Map<String, Object> processSteps;
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
        // 학습 진행 모드: basic / socratic / debate / simulation (미지정 시 FastAPI에서 basic으로 처리)
        private String learningMode;
        // 토론 모드 논제/구조 설정 (debate 모드에서만 사용, FastAPI로 그대로 패스스루)
        private Map<String, Object> debateConfig;
        // 소크라테스 모드 문답 설정 (socratic 모드에서만 사용, FastAPI로 그대로 패스스루)
        private Map<String, Object> socraticConfig;
        // 상황극 모드 설정 (simulation 모드에서만 사용, FastAPI로 그대로 패스스루)
        private Map<String, Object> simulationConfig;
        // 소크라테스 모드: 사용자가 방금 입력한 시도 답변 (오개념 분석용)
        private String userAttempt;
        // RAG 자료 ID (있으면 FastAPI가 PDF/RAG 검색을 수행)
        private Long materialId;
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
        // 기본채팅 다시 생성 제어 — 이전 답변 재사용 방지(cache 우회 + 변형 유도)
        private String messageId;          // 프론트가 부여한 이번 턴 고유 id
        private Integer regenerateAttempt; // 다시 생성 횟수 (없으면 1)
        private Boolean forceRegenerate;   // true면 cache 우회 + 변형 지시
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
        private String learningMode;
        private List<DiscussionMessage> messages;
        private String finalSynthesis;
        private List<AgentReply> replies;
        private List<Object> initialAnswers;
        private List<Object> peerFeedbacks;
        private List<Object> revisedAnswers;
        private String debateSummary;
        // 구조화 토론 단계 (채팅/마인드맵/history 공통) + 사용된 논제 설정 — FastAPI 패스스루
        private List<Map<String, Object>> debateStages;
        private Map<String, Object> debateConfig;
        // 구조화 소크라테스 단계 + 사용된 설정 — FastAPI 패스스루
        private List<Map<String, Object>> socraticSteps;
        private Map<String, Object> socraticConfig;
        // 구조화 상황극 단계 + 사용된 설정 — FastAPI 패스스루
        private List<Map<String, Object>> simulationStages;
        private Map<String, Object> simulationConfig;
        // 1차/2차/3차 생성 과정 (FastAPI processSteps를 그대로 패스스루, 없으면 null)
        private Map<String, Object> processSteps;
        // 단계별 구조 (provider/elapsedMs 포함) — FastAPI stages 패스스루, 없으면 null
        private List<Object> stages;
        // 성격 검증 요약 — FastAPI personalityValidationSummary 패스스루, 없으면 null
        private List<Object> personalityValidationSummary;
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
        // ── ai07 응답 metadata 패스스루 (없으면 null) — 프론트 확인/표시용, answer는 항상 유지 ──
        private String knowledgeLevel;       // INTRO|BACHELOR|MASTER|DOCTOR|EXPERT
        private String knowledgeLevelLabel;  // 입문/학사/석사/박사/전문가 수준
        private Integer minChars;
        private Integer actualChars;
        private Boolean lengthSatisfied;
        private java.util.List<Object> toolsUsed;
        private java.util.List<Object> toolsFailed;
        private Boolean qualityChecked;
    }
}
