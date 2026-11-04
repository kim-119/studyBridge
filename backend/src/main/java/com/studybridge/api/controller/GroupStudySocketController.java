package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.security.stomp.StompPrincipal;
import com.studybridge.api.service.GroupStudyQuizSessionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;

import com.studybridge.api.entity.GroupChatMessage;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupChatMessageRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;

import java.security.Principal;
import java.time.LocalDateTime;

/**
 * 그룹스터디 STOMP 핸들러. 보낸 사람은 항상 CONNECT 때 JWT 로 인증한 {@link StompPrincipal} 이다.
 * payload 의 userId/senderId/senderName 은 식별·권한에 쓰지 않는다(인터셉터가 다른 사용자 ID 를 담은 프레임은 이미 거부했다).
 * 채팅 본문은 운영 로그에 남기지 않는다(길이만 기록).
 */
@Controller
@RequiredArgsConstructor
@Slf4j
public class GroupStudySocketController {

    static final int MAX_CHAT_LENGTH = 5000;

    private final SimpMessagingTemplate messagingTemplate;
    private final GroupStudyQuizSessionService quizSessionService;
    private final GroupChatMessageRepository groupChatMessageRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final UserRepository userRepository;

    @MessageMapping("/group/{groupId}/chat")
    public void broadcastGroupChat(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.ChatPayload payload,
            Principal principal) {

        StompPrincipal sender = StompPrincipal.require(principal);
        String content = payload == null ? null : payload.getContent();
        if (content == null || content.isBlank()) {
            log.info("Group chat ignored (empty). groupId={}, senderId={}", groupId, sender.userId());
            return;
        }
        if (content.length() > MAX_CHAT_LENGTH) {
            log.warn("Group chat rejected (too long). groupId={}, senderId={}, length={}", groupId, sender.userId(), content.length());
            return;
        }

        GroupStudy groupStudy = groupStudyRepository.findById(groupId).orElse(null);
        if (groupStudy == null) {
            log.warn("Group chat ignored (group not found). groupId={}, senderId={}", groupId, sender.userId());
            return;
        }

        GroupStudySocketDTO.ChatPayload outbound = new GroupStudySocketDTO.ChatPayload(
                String.valueOf(sender.userId()),
                resolveSenderName(sender.userId()),
                content,
                LocalDateTime.now().toString());

        groupChatMessageRepository.save(GroupChatMessage.builder()
                .groupStudy(groupStudy)
                .senderName(outbound.getSenderName())
                .senderId(outbound.getSenderId())
                .content(content)
                .role("USER")
                .build());

        log.info("Group chat relayed. groupId={}, senderId={}, length={}", groupId, sender.userId(), content.length());
        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/chat", outbound);
    }

    @MessageMapping("/group/{groupId}/quiz/start")
    public void startQuiz(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.QuizStartPayload payload,
            Principal principal) {

        Long userId = StompPrincipal.require(principal).userId();
        Long quizId = payload == null ? null : payload.getQuizId();
        log.info("Group member triggered quiz play. groupId={}, quizId={}, userId={}", groupId, quizId, userId);
        try {
            quizSessionService.startQuiz(groupId, quizId, userId);
        } catch (Exception e) {
            log.warn("Quiz start rejected. groupId={}, quizId={}, userId={}, reason={}", groupId, quizId,
                    userId, e.getMessage(), e);
            // 실패를 조용히 삼키지 않고 프론트에 명확한 에러를 알려, placeholder/0초 화면 대신 에러를 표시하게 한다.
            messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/error",
                    GroupStudySocketDTO.QuizErrorPayload.builder()
                            .quizId(quizId)
                            .userId(userId)
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
            @Payload GroupStudySocketDTO.AnswerSubmitPayload payload,
            Principal principal) {

        Long userId = StompPrincipal.require(principal).userId();
        if (payload == null) {
            log.warn("Quiz answer rejected (empty payload). groupId={}, userId={}", groupId, userId);
            return;
        }
        // 채점·저장 대상은 인증 사용자다. (payload.userId 는 인터셉터에서 같은 값임을 확인했거나 비어 있다.)
        payload.setUserId(userId);
        try {
            quizSessionService.submitAnswer(groupId, payload);
        } catch (Exception e) {
            log.warn("Quiz answer rejected. groupId={}, userId={}, questionId={}, reason={}", groupId,
                    userId, payload.getQuestionId(), e.getMessage());
        }
    }

    // 웹 StudyRoom 의 표시 이름 규칙(displayName → User_{id})과 같다. 클라이언트가 보낸 senderName 은 쓰지 않는다.
    private String resolveSenderName(long userId) {
        return userRepository.findById(userId)
                .map(User::getDisplayName)
                .filter(name -> name != null && !name.isBlank())
                .orElse("User_" + userId);
    }
}
