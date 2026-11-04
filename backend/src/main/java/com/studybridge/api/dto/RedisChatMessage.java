package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class RedisChatMessage implements Serializable {
    private static final long serialVersionUID = 1L;

    private String agentName;  // 에이전트 이름 또는 사용자명 ("USER" 등)
    private String answer;     // 대화 내용
    private String role;       // "USER" 또는 "ASSISTANT"
    private Long agentId;      // 에이전트 ID (선택사항)
    private String qualityStatus; // Spring 품질 게이트 판정(APPROVED) — null 은 미검증(게이트 OFF/레거시). ai07 로 보내지 않음
}
