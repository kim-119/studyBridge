package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.service.GroupStudyQuizSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;

import java.time.LocalDateTime;

@Controller
@RequiredArgsConstructor
@Slf4j
public class GroupStudySocketController {

    private final SimpMessagingTemplate messagingTemplate;
    private final GroupStudyQuizSessionService quizSessionService;

    @MessageMapping("/group/{groupId}/chat")
    public void broadcastGroupChat(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.ChatPayload payload) {

        log.info("Received chat on websocket. groupId={}, sender={}, text={}", groupId, payload.getSenderName(),
                payload.getContent());
        payload.setTimestamp(LocalDateTime.now().toString());

        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/chat", payload);
    }

    @MessageMapping("/group/{groupId}/quiz/start")
    public void startQuiz(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.QuizStartPayload payload) {

        log.info("Group member triggered quiz play. groupId={}, quizId={}, userId={}", groupId,
                payload.getQuizId(), payload.getUserId());
        try {
            quizSessionService.startQuiz(groupId, payload.getQuizId(), payload.getUserId());
        } catch (Exception e) {
            log.warn("Quiz start rejected. groupId={}, quizId={}, userId={}, reason={}", groupId, payload.getQuizId(),
                    payload.getUserId(), e.getMessage(), e);
            // 실패를 조용히 삼키지 않고 프론트에 명확한 에러를 알려, placeholder/0초 화면 대신 에러를 표시하게 한다.
            messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/error",
                    GroupStudySocketDTO.QuizErrorPayload.builder()
                            .quizId(payload.getQuizId())
                            .userId(payload.getUserId())
                            .message(resolveQuizStartError(e))
                            .occurredAt(LocalDateTime.now())
                            .build());
        }
    }

    private String resolveQuizStartError(Exception e) {
        String msg = e.getMessage();
        if (e instanceof IllegalStateException && msg != null && msg.contains("문제가 없")) {
            return "이 퀴즈에는 문제가 없습니다. PDF 자료 기반 퀴즈를 다시 생성한 뒤 시작해주세요.";
        }
        if (e instanceof SecurityException) {
            return "그룹 멤버만 퀴즈를 시작할 수 있습니다.";
        }
        if (msg != null && !msg.isBlank()) {
            return "퀴즈를 시작하지 못했습니다: " + msg;
        }
        return "퀴즈를 시작하지 못했습니다. 잠시 후 다시 시도해주세요.";
    }

    @MessageMapping("/group/{groupId}/quiz/submit")
    public void submitAnswer(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.AnswerSubmitPayload payload) {

        try {
            quizSessionService.submitAnswer(groupId, payload);
        } catch (Exception e) {
            log.warn("Quiz answer rejected. groupId={}, userId={}, questionId={}, reason={}", groupId,
                    payload.getUserId(), payload.getQuestionId(), e.getMessage());
        }
    }
}
