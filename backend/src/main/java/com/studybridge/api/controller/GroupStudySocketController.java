package com.studybridge.api.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyQuiz;
import com.studybridge.api.entity.GroupStudyQuizQuestion;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizQuestionRepository;
import com.studybridge.api.repository.GroupStudyQuizRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.DestinationVariable;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.messaging.handler.annotation.Payload;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Controller;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

@Controller
@RequiredArgsConstructor
@Slf4j
public class GroupStudySocketController {

    private final SimpMessagingTemplate messagingTemplate;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final GroupStudyQuizRepository groupStudyQuizRepository;
    private final GroupStudyQuizQuestionRepository groupStudyQuizQuestionRepository;
    private final ObjectMapper objectMapper;

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

        if (payload.getUserId() == null || !groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupId, payload.getUserId(), GroupStudyMemberStatus.JOINED)) {
            log.warn("Rejected quiz start from non-joined member. groupId={}, userId={}", groupId, payload.getUserId());
            return;
        }

        GroupStudyQuiz quiz = groupStudyQuizRepository.findById(payload.getQuizId())
                .orElse(null);

        if (quiz == null) {
            log.warn("Quiz not found with ID: {}", payload.getQuizId());
            return;
        }

        if (!quiz.getGroupStudy().getId().equals(groupId)) {
            log.warn("Rejected quiz start for quiz from another group. requestGroupId={}, quizId={}, quizGroupId={}",
                    groupId, quiz.getId(), quiz.getGroupStudy().getId());
            return;
        }

        List<GroupStudyQuizQuestion> questions = groupStudyQuizQuestionRepository.findByQuizId(payload.getQuizId());

        if (!questions.isEmpty()) {
            sendQuestion(groupId, quiz, questions, 0);
        }
    }

    @MessageMapping("/group/{groupId}/quiz/submit")
    @Transactional
    public void submitAnswer(
            @DestinationVariable Long groupId,
            @Payload GroupStudySocketDTO.AnswerSubmitPayload payload) {

        log.info("User submitted answer. groupId={}, userId={}, questionId={}, submitted={}",
                groupId, payload.getUserId(), payload.getQuestionId(), payload.getSubmittedAnswer());

        GroupStudyQuizQuestion question = groupStudyQuizQuestionRepository.findById(payload.getQuestionId())
                .orElse(null);

        if (question == null)
            return;

        GroupStudyQuiz quiz = question.getQuiz();

        boolean isCorrect = question.getCorrectAnswer().equals(payload.getSubmittedAnswer());
        int pointsEarned = 0;

        if (isCorrect) {
            pointsEarned = quiz.getRewardPoints();

            int timeLeft = question.getTimeLimitSeconds() - payload.getTimeTakenSeconds();
            if (timeLeft > 0) {
                pointsEarned += (timeLeft / 2);
            }

            GroupStudyMember member = groupStudyMemberRepository.findByGroupStudyIdAndUserIdAndStatus(
                    groupId, payload.getUserId(), GroupStudyMemberStatus.JOINED).orElse(null);

            if (member != null) {
                member.setPoints(member.getPoints() + pointsEarned);
                groupStudyMemberRepository.save(member);
                log.info("Correct! Added points={} to userId={}. Total points={}", pointsEarned, payload.getUserId(),
                        member.getPoints());
            }
        }

        GroupStudySocketDTO.GradingPayload gradingResult = GroupStudySocketDTO.GradingPayload.builder()
                .questionId(payload.getQuestionId())
                .isCorrect(isCorrect)
                .pointsEarned(pointsEarned)
                .correctAnswer(question.getCorrectAnswer())
                .build();

        List<GroupStudyMember> activeMembers = groupStudyMemberRepository.findByGroupStudyIdAndStatus(groupId,
                GroupStudyMemberStatus.JOINED);
        List<GroupStudySocketDTO.ScoreboardEntry> scoreboard = activeMembers.stream()
                .map(m -> new GroupStudySocketDTO.ScoreboardEntry(m.getUser().getId(), m.getUser().getDisplayName(),
                        m.getPoints()))
                .sorted((a, b) -> b.getPoints().compareTo(a.getPoints()))
                .collect(Collectors.toList());

        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/scoreboard", scoreboard);
    }

    private void sendQuestion(Long groupId, GroupStudyQuiz quiz, List<GroupStudyQuizQuestion> questions, int index) {
        GroupStudyQuizQuestion q = questions.get(index);

        List<String> options = new ArrayList<>();
        try {
            options = objectMapper.readValue(q.getOptionsJson(), new TypeReference<List<String>>() {
            });
        } catch (Exception e) {
            log.error("Failed to parse optionsJson for question ID={}", q.getId());
        }

        GroupStudySocketDTO.QuestionBroadcastPayload packet = GroupStudySocketDTO.QuestionBroadcastPayload.builder()
                .quizId(quiz.getId())
                .quizTitle(quiz.getTitle())
                .questionId(q.getId())
                .questionText(q.getQuestion())
                .options(options)
                .currentIndex(index)
                .totalQuestions(questions.size())
                .timeLimitSeconds(q.getTimeLimitSeconds())
                .build();

        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/question", packet);
    }
}
