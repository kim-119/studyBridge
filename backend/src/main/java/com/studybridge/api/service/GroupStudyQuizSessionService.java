package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.stereotype.Service;
import org.springframework.context.event.EventListener;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import jakarta.annotation.PostConstruct;

import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ScheduledFuture;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class GroupStudyQuizSessionService {

    private static final int QUIZ_DURATION_SECONDS = 30;
    private static final int REVEAL_DISPLAY_SECONDS = 3;

    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final GroupStudyQuizRepository groupStudyQuizRepository;
    private final GroupStudyQuizQuestionRepository groupStudyQuizQuestionRepository;
    private final GroupStudyQuizSessionRepository groupStudyQuizSessionRepository;
    private final GroupStudyQuizSessionAnswerRepository groupStudyQuizSessionAnswerRepository;
    private final SimpMessagingTemplate messagingTemplate;
    private final ThreadPoolTaskScheduler quizTaskScheduler;
    private final ObjectMapper objectMapper;
    private final PlatformTransactionManager transactionManager;

    private TransactionTemplate transactionTemplate;

    private final Map<Long, Object> sessionLocks = new ConcurrentHashMap<>();
    private final Map<Long, ScheduledFuture<?>> timerTasks = new ConcurrentHashMap<>();
    private final Map<Long, ScheduledFuture<?>> transitionTasks = new ConcurrentHashMap<>();

    @PostConstruct
    void initTransactionTemplate() {
        this.transactionTemplate = new TransactionTemplate(transactionManager);
    }

    // 스케줄러 스레드(quiz-task-*)에서 실행되는 작업은 OSIV(Open-Session-In-View)가 없어
    // LAZY 연관(member.user 등) 접근 시 LazyInitializationException이 발생한다.
    // 모든 스케줄 콜백을 트랜잭션 경계로 감싸 영속성 컨텍스트를 열어준다.
    private void runInTransaction(Runnable task) {
        transactionTemplate.executeWithoutResult(status -> task.run());
    }

    @EventListener(ApplicationReadyEvent.class)
    @Transactional
    public void restoreActiveSessions() {
        List<GroupStudyQuizSessionStatus> statuses = List.of(
                GroupStudyQuizSessionStatus.QUESTION,
                GroupStudyQuizSessionStatus.REVEALING
        );

        for (GroupStudyQuizSession session : groupStudyQuizSessionRepository.findByStatusInOrderByCreatedAtDesc(statuses)) {
            synchronized (lockForSession(session.getId())) {
                if (session.getStatus() == GroupStudyQuizSessionStatus.QUESTION) {
                    if (session.getQuestionEndsAt() == null) {
                        log.warn("Skipping quiz restore because questionEndsAt is null. sessionId={}", session.getId());
                        continue;
                    }
                    if (session.getQuestionEndsAt().isBefore(LocalDateTime.now())) {
                        revealQuestion(session.getId());
                    } else {
                        scheduleCountdown(session.getId());
                        scheduleReveal(session.getId());
                    }
                } else if (session.getStatus() == GroupStudyQuizSessionStatus.REVEALING) {
                    if (session.getNextQuestionAt() == null) {
                        log.warn("Skipping quiz restore because nextQuestionAt is null. sessionId={}", session.getId());
                        continue;
                    }
                    if (session.getNextQuestionAt().isBefore(LocalDateTime.now())) {
                        advanceQuestion(session.getId());
                    } else {
                        scheduleNextTransition(session.getId());
                    }
                }
            }
        }
    }

    @Transactional
    public GroupStudySocketDTO.QuizSessionPayload startQuiz(Long groupId, Long quizId, Long userId) {
        synchronized (lockForGroup(groupId)) {
            validateMember(groupId, userId);

            GroupStudyQuiz quiz = groupStudyQuizRepository.findById(quizId)
                    .orElseThrow(() -> new NoSuchElementException("Quiz not found with ID: " + quizId));

            if (!quiz.getGroupStudy().getId().equals(groupId)) {
                throw new IllegalArgumentException("해당 그룹의 퀴즈가 아닙니다.");
            }

            List<GroupStudyQuizSessionStatus> activeStatuses = List.of(
                    GroupStudyQuizSessionStatus.QUESTION,
                    GroupStudyQuizSessionStatus.REVEALING
            );

            Optional<GroupStudyQuizSession> activeSession = groupStudyQuizSessionRepository
                    .findTopByGroupStudyIdAndStatusInOrderByCreatedAtDesc(groupId, activeStatuses);

            // 만료됐는데 진행되지 못하고 멈춘 좀비 세션은 재발행하지 않고 폐기한 뒤 새로 시작한다.
            // (과거 스케줄 실패로 status=QUESTION & questionEndsAt이 과거인 채 남으면
            //  remainingSeconds=0 으로 스냅샷되어 "0초/선택불가/더미 문제"가 발생한다.)
            if (activeSession.isPresent() && isStaleSession(activeSession.get())) {
                abortSession(activeSession.get());
                activeSession = Optional.empty();
            }

            if (activeSession.isPresent() && !activeSession.get().getQuiz().getId().equals(quizId)) {
                return buildSnapshot(activeSession.get(), userId, "다른 퀴즈가 이미 진행 중입니다.");
            }

            if (activeSession.isPresent()) {
                GroupStudyQuizSession session = activeSession.get();
                publishSessionSnapshot(session, buildSnapshot(session, userId, null), "/topic/group/" + groupId + "/quiz/session");
                return buildSnapshot(session, userId, null);
            }

            List<GroupStudyQuizQuestion> questions = getOrderedQuestions(quizId);
            if (questions.isEmpty()) {
                throw new IllegalStateException("퀴즈 문제가 없습니다.");
            }

            LocalDateTime now = LocalDateTime.now();

            GroupStudyQuizSession session = GroupStudyQuizSession.builder()
                    .groupStudy(quiz.getGroupStudy())
                    .quiz(quiz)
                    .quizTitleSnapshot(quiz.getTitle())
                    .status(GroupStudyQuizSessionStatus.QUESTION)
                    .currentQuestionIndex(0)
                    .questionDurationSeconds(QUIZ_DURATION_SECONDS)
                    .questionOrderJson(writeQuestionOrder(questions))
                    .currentQuestionId(questions.get(0).getId())
                    .questionStartedAt(now)
                    .questionEndsAt(now.plusSeconds(QUIZ_DURATION_SECONDS))
                    .build();
            session = groupStudyQuizSessionRepository.save(session);

            cancelScheduledTasks(session.getId());
            publishQuestion(session, questions.get(0), "QUESTION", groupId);
            scheduleCountdown(session.getId());
            scheduleReveal(session.getId());

            return buildSnapshot(session, userId, null);
        }
    }

    @Transactional
    public GroupStudySocketDTO.QuizSubmissionAckPayload submitAnswer(Long groupId, GroupStudySocketDTO.AnswerSubmitPayload payload) {
        synchronized (lockForGroup(groupId)) {
            validateMember(groupId, payload.getUserId());

            GroupStudyQuizSession session = findActiveSession(groupId)
                    .orElseThrow(() -> new IllegalStateException("진행 중인 퀴즈 세션이 없습니다."));

            if (session.getCurrentQuestionId() == null || !session.getCurrentQuestionId().equals(payload.getQuestionId())) {
                return GroupStudySocketDTO.QuizSubmissionAckPayload.builder()
                        .sessionId(session.getId())
                        .questionId(payload.getQuestionId())
                        .userId(payload.getUserId())
                        .accepted(false)
                        .duplicate(false)
                        .submittedAt(LocalDateTime.now())
                        .message("현재 문제와 일치하지 않습니다.")
                        .build();
            }

            LocalDateTime now = LocalDateTime.now();
            if (session.getQuestionEndsAt() != null && now.isAfter(session.getQuestionEndsAt())) {
                return GroupStudySocketDTO.QuizSubmissionAckPayload.builder()
                        .sessionId(session.getId())
                        .questionId(payload.getQuestionId())
                        .userId(payload.getUserId())
                        .accepted(false)
                        .duplicate(false)
                        .submittedAt(now)
                        .message("제한 시간이 종료되었습니다.")
                        .build();
            }

            Optional<GroupStudyQuizSessionAnswer> existing = groupStudyQuizSessionAnswerRepository
                    .findBySessionIdAndUserIdAndQuestionId(session.getId(), payload.getUserId(), payload.getQuestionId());

            if (existing.isPresent()) {
                GroupStudySocketDTO.QuizSubmissionAckPayload ack = GroupStudySocketDTO.QuizSubmissionAckPayload.builder()
                        .sessionId(session.getId())
                        .questionId(payload.getQuestionId())
                        .userId(payload.getUserId())
                        .accepted(true)
                        .duplicate(true)
                        .submittedAt(existing.get().getSubmittedAt())
                        .message("이미 제출된 답안입니다.")
                        .build();
                messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/submitted", ack);
                return ack;
            }

            GroupStudyQuizSessionAnswer answer = GroupStudyQuizSessionAnswer.builder()
                    .session(session)
                    .userId(payload.getUserId())
                    .questionId(payload.getQuestionId())
                    .submittedAnswer(payload.getSubmittedAnswer())
                    .submittedAt(now)
                    .build();
            groupStudyQuizSessionAnswerRepository.save(answer);

            GroupStudySocketDTO.QuizSubmissionAckPayload ack = GroupStudySocketDTO.QuizSubmissionAckPayload.builder()
                    .sessionId(session.getId())
                    .questionId(payload.getQuestionId())
                    .userId(payload.getUserId())
                    .accepted(true)
                    .duplicate(false)
                    .submittedAt(now)
                    .message("제출이 접수되었습니다.")
                    .build();
            messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/submitted", ack);
            return ack;
        }
    }

    @Transactional
    public GroupStudySocketDTO.QuizSessionPayload getCurrentSession(Long groupId, Long userId) {
        validateMember(groupId, userId);
        Optional<GroupStudyQuizSession> active = findActiveSession(groupId);
        if (active.isPresent()) {
            // 좀비(만료·정지) 세션이면 진행 중인 퀴즈로 노출하지 않는다. 폐기 후 "세션 없음" 처리.
            if (isStaleSession(active.get())) {
                abortSession(active.get());
            } else {
                return buildSnapshot(active.get(), userId, null);
            }
        }

        return findLatestSession(groupId)
                .filter(session -> session.getStatus() == GroupStudyQuizSessionStatus.COMPLETED
                        && session.getCompletedAt() != null
                        && session.getCompletedAt().isAfter(LocalDateTime.now().minusMinutes(30)))
                .map(session -> buildSnapshot(session, userId, null))
                .orElse(null);
    }

    private Optional<GroupStudyQuizSession> findActiveSession(Long groupId) {
        return groupStudyQuizSessionRepository.findTopByGroupStudyIdAndStatusInOrderByCreatedAtDesc(groupId,
                List.of(GroupStudyQuizSessionStatus.QUESTION, GroupStudyQuizSessionStatus.REVEALING));
    }

    // 스케줄러가 진행시키지 못해 만료된 채 멈춘 세션(좀비) 판별.
    // QUESTION 인데 종료시각이 유예시간을 넘겨 지났거나, REVEALING 인데 다음문제시각이 지나도록 정지된 경우.
    private boolean isStaleSession(GroupStudyQuizSession session) {
        LocalDateTime now = LocalDateTime.now();
        if (session.getStatus() == GroupStudyQuizSessionStatus.QUESTION) {
            return session.getQuestionEndsAt() == null
                    || session.getQuestionEndsAt().plusSeconds(REVEAL_DISPLAY_SECONDS + 5).isBefore(now);
        }
        if (session.getStatus() == GroupStudyQuizSessionStatus.REVEALING) {
            return session.getNextQuestionAt() == null
                    || session.getNextQuestionAt().plusSeconds(5).isBefore(now);
        }
        return false;
    }

    private void abortSession(GroupStudyQuizSession session) {
        cancelScheduledTasks(session.getId());
        session.setStatus(GroupStudyQuizSessionStatus.ABORTED);
        session.setCompletedAt(LocalDateTime.now());
        groupStudyQuizSessionRepository.save(session);
        log.warn("Aborted stale quiz session. sessionId={}, status was stuck/expired", session.getId());
    }

    private Optional<GroupStudyQuizSession> findLatestSession(Long groupId) {
        return groupStudyQuizSessionRepository.findTopByGroupStudyIdOrderByCreatedAtDesc(groupId);
    }

    private void validateMember(Long groupId, Long userId) {
        if (userId == null || !groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(
                groupId, userId, GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 퀴즈를 진행할 수 있습니다.");
        }
    }

    private Object lockForGroup(Long groupId) {
        return sessionLocks.computeIfAbsent(groupId, key -> new Object());
    }

    private List<GroupStudyQuizQuestion> getOrderedQuestions(Long quizId) {
        return groupStudyQuizQuestionRepository.findByQuizIdOrderByIdAsc(quizId);
    }

    private String writeQuestionOrder(List<GroupStudyQuizQuestion> questions) {
        List<Long> ids = questions.stream().map(GroupStudyQuizQuestion::getId).toList();
        try {
            return objectMapper.writeValueAsString(ids);
        } catch (Exception e) {
            throw new IllegalStateException("퀴즈 문제 순서를 저장하지 못했습니다.", e);
        }
    }

    private List<Long> readQuestionOrder(GroupStudyQuizSession session) {
        try {
            Long[] ids = objectMapper.readValue(session.getQuestionOrderJson(), Long[].class);
            return List.of(ids);
        } catch (Exception e) {
            log.warn("Failed to parse quiz question order. sessionId={}", session.getId());
            return List.of();
        }
    }

    private Integer resolveTotalQuestions(GroupStudyQuizSession session) {
        List<Long> order = readQuestionOrder(session);
        return order.isEmpty() ? getOrderedQuestions(session.getQuiz().getId()).size() : order.size();
    }

    private String normalizePhase(GroupStudyQuizSessionStatus status) {
        if (status == null) {
            return "QUESTION";
        }
        return switch (status) {
            case QUESTION -> "QUESTION";
            case REVEALING -> "REVEAL";
            case COMPLETED -> "ENDED";
            case ABORTED -> "ABORTED";
        };
    }

    private GroupStudyQuizQuestion getCurrentQuestion(GroupStudyQuizSession session) {
        if (session.getCurrentQuestionId() != null) {
            return groupStudyQuizQuestionRepository.findById(session.getCurrentQuestionId())
                    .orElseThrow(() -> new NoSuchElementException("Quiz question not found with ID: " + session.getCurrentQuestionId()));
        }

        List<Long> order = readQuestionOrder(session);
        if (order.isEmpty() || session.getCurrentQuestionIndex() == null || session.getCurrentQuestionIndex() >= order.size()) {
            throw new IllegalStateException("현재 퀴즈 문제를 찾을 수 없습니다.");
        }
        return groupStudyQuizQuestionRepository.findById(order.get(session.getCurrentQuestionIndex()))
                .orElseThrow(() -> new NoSuchElementException("Quiz question not found in session order."));
    }

    private List<GroupStudySocketDTO.ScoreboardEntry> buildScoreboard(Long groupId) {
        return groupStudyMemberRepository.findByGroupStudyIdAndStatus(groupId, GroupStudyMemberStatus.JOINED).stream()
                .map(member -> new GroupStudySocketDTO.ScoreboardEntry(
                        member.getUser().getId(),
                        member.getUser().getDisplayName(),
                        member.getPoints()))
                .sorted(Comparator
                        .comparingInt((GroupStudySocketDTO.ScoreboardEntry entry) -> entry.getPoints() != null ? entry.getPoints() : 0)
                        .reversed()
                        .thenComparing(entry -> entry.getDisplayName() != null ? entry.getDisplayName() : ""))
                .collect(Collectors.toList());
    }

    private GroupStudySocketDTO.QuizSessionPayload buildSnapshot(GroupStudyQuizSession session, Long userId, String message) {
        GroupStudyQuizQuestion question = session.getCurrentQuestionId() != null ? getCurrentQuestion(session) : null;
        Integer remaining = null;
        if (session.getQuestionEndsAt() != null) {
            remaining = Math.max(0, (int) Duration.between(LocalDateTime.now(), session.getQuestionEndsAt()).toSeconds());
        }

        GroupStudyQuizSessionAnswer currentUserAnswer = null;
        if (userId != null && session.getCurrentQuestionId() != null) {
            currentUserAnswer = groupStudyQuizSessionAnswerRepository
                    .findBySessionIdAndUserIdAndQuestionId(session.getId(), userId, session.getCurrentQuestionId())
                    .orElse(null);
        }

        return GroupStudySocketDTO.QuizSessionPayload.builder()
                .sessionId(session.getId())
                .quizId(session.getQuiz().getId())
                .quizTitle(session.getQuizTitleSnapshot())
                .phase(normalizePhase(session.getStatus()))
                .questionId(question != null ? question.getId() : session.getCurrentQuestionId())
                .questionText(question != null ? question.getQuestion() : null)
                .options(question != null ? parseOptions(question) : List.of())
                .currentIndex(session.getCurrentQuestionIndex())
                .totalQuestions(resolveTotalQuestions(session))
                .timeLimitSeconds(session.getQuestionDurationSeconds())
                .remainingSeconds(remaining)
                .correctAnswer(session.getStatus() == GroupStudyQuizSessionStatus.REVEALING || session.getStatus() == GroupStudyQuizSessionStatus.COMPLETED
                        ? question != null ? question.getCorrectAnswer() : null
                        : null)
                .pointsAwarded(null)
                .submittedCount(session.getCurrentQuestionId() != null
                        ? groupStudyQuizSessionAnswerRepository.findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(session.getId(), session.getCurrentQuestionId()).size()
                        : 0)
                .userSubmitted(currentUserAnswer != null)
                .userSubmittedAnswer(currentUserAnswer != null ? currentUserAnswer.getSubmittedAnswer() : null)
                .userPointsAwarded(currentUserAnswer != null ? currentUserAnswer.getPointsAwarded() : null)
                .userAnswerCorrect(currentUserAnswer != null ? currentUserAnswer.getIsCorrect() : null)
                .questionStartedAt(session.getQuestionStartedAt())
                .questionEndsAt(session.getQuestionEndsAt())
                .revealAt(session.getRevealAt())
                .nextQuestionAt(session.getNextQuestionAt())
                .completedAt(session.getCompletedAt())
                .scoreboard(buildScoreboard(session.getGroupStudy().getId()))
                .message(message)
                .build();
    }

    private void publishQuestion(GroupStudyQuizSession session, GroupStudyQuizQuestion question, String phase, Long groupId) {
        GroupStudySocketDTO.QuizSessionPayload payload = GroupStudySocketDTO.QuizSessionPayload.builder()
                .sessionId(session.getId())
                .quizId(session.getQuiz().getId())
                .quizTitle(session.getQuizTitleSnapshot())
                .phase(phase)
                .questionId(question.getId())
                .questionText(question.getQuestion())
                .options(parseOptions(question))
                .currentIndex(session.getCurrentQuestionIndex())
                .totalQuestions(resolveTotalQuestions(session))
                .timeLimitSeconds(QUIZ_DURATION_SECONDS)
                .remainingSeconds(QUIZ_DURATION_SECONDS)
                .questionStartedAt(session.getQuestionStartedAt())
                .questionEndsAt(session.getQuestionEndsAt())
                .scoreboard(buildScoreboard(groupId))
                .build();

        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/" + ("QUESTION".equals(phase) ? "question" : "next"), payload);
        messagingTemplate.convertAndSend("/topic/group/" + groupId + "/quiz/session", payload);
    }

    private List<String> parseOptions(GroupStudyQuizQuestion question) {
        try {
            return objectMapper.readValue(question.getOptionsJson(), new com.fasterxml.jackson.core.type.TypeReference<List<String>>() {
            });
        } catch (Exception e) {
            return List.of();
        }
    }

    private void scheduleCountdown(Long sessionId) {
        cancelTimerTask(sessionId);
        // 첫 틱을 1초 뒤로 미뤄, startQuiz/advanceQuestion 트랜잭션이 커밋되기 전에
        // 다른 스레드의 broadcastTimer가 세션을 못 찾고 타이머를 자가 취소하는 레이스를 방지한다.
        ScheduledFuture<?> future = quizTaskScheduler.scheduleAtFixedRate(
                () -> runInTransaction(() -> broadcastTimer(sessionId)),
                new Date(System.currentTimeMillis() + 1000L), 1000L);
        timerTasks.put(sessionId, future);
    }

    private void broadcastTimer(Long sessionId) {
        synchronized (lockForSession(sessionId)) {
            GroupStudyQuizSession session = groupStudyQuizSessionRepository.findById(sessionId).orElse(null);
            if (session == null || session.getStatus() != GroupStudyQuizSessionStatus.QUESTION || session.getQuestionEndsAt() == null) {
                cancelTimerTask(sessionId);
                return;
            }

            int remaining = Math.max(0, (int) Duration.between(LocalDateTime.now(), session.getQuestionEndsAt()).toSeconds());
            messagingTemplate.convertAndSend("/topic/group/" + session.getGroupStudy().getId() + "/quiz/timer",
                    GroupStudySocketDTO.QuizTimerPayload.builder()
                            .sessionId(sessionId)
                            .questionId(session.getCurrentQuestionId())
                            .currentIndex(session.getCurrentQuestionIndex())
                            .remainingSeconds(remaining)
                            .questionEndsAt(session.getQuestionEndsAt())
                            .build());

            if (remaining <= 0) {
                cancelTimerTask(sessionId);
            }
        }
    }

    private void scheduleReveal(Long sessionId) {
        cancelTransitionTask(sessionId);
        GroupStudyQuizSession session = groupStudyQuizSessionRepository.findById(sessionId).orElseThrow();
        if (session.getQuestionEndsAt() == null) {
            return;
        }
        ScheduledFuture<?> future = quizTaskScheduler.schedule(() -> runInTransaction(() -> revealQuestion(sessionId)),
                Date.from(session.getQuestionEndsAt().atZone(ZoneId.systemDefault()).toInstant()));
        transitionTasks.put(sessionId, future);
    }

    private void revealQuestion(Long sessionId) {
        synchronized (lockForSession(sessionId)) {
            GroupStudyQuizSession session = groupStudyQuizSessionRepository.findById(sessionId).orElse(null);
            if (session == null || session.getStatus() != GroupStudyQuizSessionStatus.QUESTION) {
                return;
            }

            GroupStudyQuizQuestion question = getCurrentQuestion(session);
            List<GroupStudyQuizSessionAnswer> answers = groupStudyQuizSessionAnswerRepository
                    .findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(sessionId, question.getId());
            LocalDateTime now = LocalDateTime.now();
            int totalPointsAwarded = 0;

            for (GroupStudyQuizSessionAnswer answer : answers) {
                if (answer.getGradedAt() != null) {
                    continue;
                }

                boolean isCorrect = answer.getSubmittedAnswer() != null && answer.getSubmittedAnswer().equals(question.getCorrectAnswer());
                int points = 0;
                if (isCorrect) {
                    points = session.getQuiz().getRewardPoints() != null ? session.getQuiz().getRewardPoints() : 10;
                    int timeTaken = answer.getSubmittedAt() != null
                            ? Math.max(0, (int) Duration.between(session.getQuestionStartedAt(), answer.getSubmittedAt()).toSeconds())
                            : QUIZ_DURATION_SECONDS;
                    int bonus = Math.max(0, (QUIZ_DURATION_SECONDS - Math.min(timeTaken, QUIZ_DURATION_SECONDS))) / 2;
                    points += bonus;
                }

                final int awardedPoints = points;
                if (isCorrect) {
                    groupStudyMemberRepository.findByGroupStudyIdAndUserIdAndStatus(session.getGroupStudy().getId(),
                            answer.getUserId(), GroupStudyMemberStatus.JOINED)
                            .ifPresent(member -> {
                                member.setPoints((member.getPoints() != null ? member.getPoints() : 0) + awardedPoints);
                                groupStudyMemberRepository.save(member);
                            });
                    totalPointsAwarded += awardedPoints;
                }

                answer.setIsCorrect(isCorrect);
                answer.setPointsAwarded(points);
                answer.setGradedAt(now);
                groupStudyQuizSessionAnswerRepository.save(answer);
            }

            session.setStatus(GroupStudyQuizSessionStatus.REVEALING);
            session.setRevealAt(now);
            session.setNextQuestionAt(now.plusSeconds(REVEAL_DISPLAY_SECONDS));
            groupStudyQuizSessionRepository.save(session);

            GroupStudySocketDTO.QuizSessionPayload revealPayload = GroupStudySocketDTO.QuizSessionPayload.builder()
                    .sessionId(session.getId())
                    .quizId(session.getQuiz().getId())
                    .quizTitle(session.getQuizTitleSnapshot())
                    .phase("REVEAL")
                    .questionId(question.getId())
                    .questionText(question.getQuestion())
                    .options(parseOptions(question))
                    .currentIndex(session.getCurrentQuestionIndex())
                    .totalQuestions(resolveTotalQuestions(session))
                    .timeLimitSeconds(QUIZ_DURATION_SECONDS)
                    .remainingSeconds(0)
                    .correctAnswer(question.getCorrectAnswer())
                    .pointsAwarded(totalPointsAwarded)
                    .submittedCount(answers.size())
                    .questionStartedAt(session.getQuestionStartedAt())
                    .questionEndsAt(session.getQuestionEndsAt())
                    .revealAt(now)
                    .nextQuestionAt(session.getNextQuestionAt())
                    .scoreboard(buildScoreboard(session.getGroupStudy().getId()))
                    .message("정답이 공개되었습니다.")
                    .build();

            messagingTemplate.convertAndSend("/topic/group/" + session.getGroupStudy().getId() + "/quiz/reveal", revealPayload);
            messagingTemplate.convertAndSend("/topic/group/" + session.getGroupStudy().getId() + "/quiz/scoreboard", revealPayload);

            cancelTimerTask(sessionId);
            scheduleNextTransition(sessionId);
        }
    }

    private void scheduleNextTransition(Long sessionId) {
        cancelTransitionTask(sessionId);
        GroupStudyQuizSession session = groupStudyQuizSessionRepository.findById(sessionId).orElse(null);
        if (session == null || session.getNextQuestionAt() == null) {
            return;
        }

        ScheduledFuture<?> future = quizTaskScheduler.schedule(() -> runInTransaction(() -> advanceQuestion(sessionId)),
                Date.from(session.getNextQuestionAt().atZone(ZoneId.systemDefault()).toInstant()));
        transitionTasks.put(sessionId, future);
    }

    private void advanceQuestion(Long sessionId) {
        synchronized (lockForSession(sessionId)) {
            GroupStudyQuizSession session = groupStudyQuizSessionRepository.findById(sessionId).orElse(null);
            if (session == null || session.getStatus() != GroupStudyQuizSessionStatus.REVEALING) {
                return;
            }

            List<GroupStudyQuizQuestion> questions = getOrderedQuestions(session.getQuiz().getId());
            int nextIndex = session.getCurrentQuestionIndex() + 1;

            if (nextIndex >= questions.size()) {
                completeSession(session);
                return;
            }

            GroupStudyQuizQuestion nextQuestion = questions.get(nextIndex);
            LocalDateTime now = LocalDateTime.now();
            session.setStatus(GroupStudyQuizSessionStatus.QUESTION);
            session.setCurrentQuestionIndex(nextIndex);
            session.setCurrentQuestionId(nextQuestion.getId());
            session.setQuestionStartedAt(now);
            session.setQuestionEndsAt(now.plusSeconds(QUIZ_DURATION_SECONDS));
            session.setRevealAt(null);
            session.setNextQuestionAt(null);
            groupStudyQuizSessionRepository.save(session);

            publishQuestion(session, nextQuestion, "NEXT", session.getGroupStudy().getId());
            scheduleCountdown(session.getId());
            scheduleReveal(session.getId());
        }
    }

    private void completeSession(GroupStudyQuizSession session) {
        LocalDateTime now = LocalDateTime.now();
        session.setStatus(GroupStudyQuizSessionStatus.COMPLETED);
        session.setCompletedAt(now);
        session.setRevealAt(now);
        session.setNextQuestionAt(null);
        groupStudyQuizSessionRepository.save(session);

        GroupStudyQuizQuestion question = getCurrentQuestion(session);
        GroupStudySocketDTO.QuizSessionPayload endPayload = GroupStudySocketDTO.QuizSessionPayload.builder()
                .sessionId(session.getId())
                .quizId(session.getQuiz().getId())
                .quizTitle(session.getQuizTitleSnapshot())
                .phase("ENDED")
                .questionId(question.getId())
                .questionText(question.getQuestion())
                .options(parseOptions(question))
                .currentIndex(session.getCurrentQuestionIndex())
                .totalQuestions(resolveTotalQuestions(session))
                .timeLimitSeconds(QUIZ_DURATION_SECONDS)
                .remainingSeconds(0)
                .correctAnswer(question.getCorrectAnswer())
                .questionStartedAt(session.getQuestionStartedAt())
                .questionEndsAt(session.getQuestionEndsAt())
                .revealAt(now)
                .completedAt(now)
                .scoreboard(buildScoreboard(session.getGroupStudy().getId()))
                .message("퀴즈가 종료되었습니다.")
                .build();

        messagingTemplate.convertAndSend("/topic/group/" + session.getGroupStudy().getId() + "/quiz/end", endPayload);
        messagingTemplate.convertAndSend("/topic/group/" + session.getGroupStudy().getId() + "/quiz/scoreboard", endPayload);

        cancelScheduledTasks(session.getId());
    }

    private Object lockForSession(Long sessionId) {
        return sessionLocks.computeIfAbsent(-sessionId, key -> new Object());
    }

    private void publishSessionSnapshot(GroupStudyQuizSession session, GroupStudySocketDTO.QuizSessionPayload payload, String destination) {
        messagingTemplate.convertAndSend(destination, payload);
    }

    private void cancelScheduledTasks(Long sessionId) {
        cancelTimerTask(sessionId);
        cancelTransitionTask(sessionId);
    }

    private void cancelTimerTask(Long sessionId) {
        ScheduledFuture<?> future = timerTasks.remove(sessionId);
        if (future != null) {
            future.cancel(false);
        }
    }

    private void cancelTransitionTask(Long sessionId) {
        ScheduledFuture<?> future = transitionTasks.remove(sessionId);
        if (future != null) {
            future.cancel(false);
        }
    }
}
