package com.studybridge.api.controller;

import com.studybridge.api.dto.LearningMateDTO;
import com.studybridge.api.service.LearningMateService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * AI 학습메이트(질문 중심) 신규 endpoint. 기존 멀티에이전트 룸 채팅/SSE 컨트롤러와 분리(격리, 추가 전용).
 * 같은 질문을 4가지 모드로 다시 보기 + 빠른 조정을 단일 블로킹 호출로 제공한다.
 * 인증은 기존 SecurityConfig 적용(JWT 필요) — 별도 보안 변경 없음.
 */
@Slf4j
@RestController
@RequiredArgsConstructor
@RequestMapping("/api/learning-mate")
public class LearningMateController {

    private final LearningMateService learningMateService;

    @PostMapping("/chat")
    public ResponseEntity<LearningMateDTO.Response> chat(@RequestBody LearningMateDTO.Request request) {
        return ResponseEntity.ok(learningMateService.chat(request));
    }
}
