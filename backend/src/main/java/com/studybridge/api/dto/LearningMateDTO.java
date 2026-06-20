package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.List;
import java.util.Map;

/**
 * AI 학습메이트(질문 중심) 요청/응답 DTO.
 *
 * <p>같은 질문을 4가지 학습 방식(explain/socratic/debate/roleplay)으로 다시 보기 + 빠른 조정(quickAction)을
 * 지원한다. 기존 멀티에이전트 룸 채팅(ChatDTO.MultiChatRequest)과 분리된 신규/격리 DTO이며, 답변 생성은
 * 기존과 동일한 FastAPI /api/ai/multi-chat 흐름으로 연결된다(외부 LLM 미사용, Ollama-only 유지).
 *
 * <p>용어: 사용자에게는 "지식수준"이 아니라 "학습자 수준(learnerLevel)"으로 표시한다. 백엔드 호환을 위해
 * 내부적으로 knowledgeLevel 로 매핑하되 라벨은 학습자 수준이다.
 */
public class LearningMateDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    public static class Request {
        private String question;             // 사용자의 원 질문
        private String mode;                 // explain | socratic | debate | roleplay
        private Persona persona;
        private String previousQuestion;     // "더 쉽게"/"소크라테스식으로" 후속 요청 시 기존 질문 유지용
        private String rewriteInstruction;   // 재생성 지시(직접 지정 시)
        private String quickAction;          // easier | deeper | add_example | code_example | short_summary
        private Map<String, Object> advancedOptions; // 모드별 고급 설정(선택)
    }

    @Getter
    @Setter
    @NoArgsConstructor
    public static class Persona {
        private String name;                 // 학습메이트 이름(기본: 돌리)
        private String tone;                 // 공통 7종 key: default|professional|friendly|honest|unique|efficient|cynical (레거시 라벨도 허용)
        private String personalityStyle;     // 정규 성격 key(tone보다 우선)
        private Double temperature;          // 사용자 조절 temperature(0.0~1.2, 없으면 성격 기본값)
        private String learnerLevel;         // beginner | undergraduate | advanced | expert (UI 라벨: 학습자 수준)
        private String customInstruction;    // 추가 요청
    }

    @Getter
    @Builder
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Response {
        private String question;
        private String answer;
        private String mode;
        private String modeLabel;
        private String tone;
        private String toneLabel;
        private String learnerLevel;
        private String learnerLevelLabel;
        private String summaryLabel;         // "기본 설명 · 친근한 말투 · 입문자 맞춤"
        private List<String> availableModes;
        private List<String> availableQuickActions;
        // 상태 전파(프론트 에러/폴백 처리용, additive)
        private Boolean success;
        private String errorCode;
        private String message;
        private String quickActionApplied;
    }
}
