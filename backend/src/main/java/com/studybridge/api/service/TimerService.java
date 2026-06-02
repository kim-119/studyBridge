package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyAttendance;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.TimerRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class TimerService {

        private final TimerRepository timerRepository;
        private final UserRepository userRepository;
        private final GroupStudyRepository groupStudyRepository;
        private final GroupStudyMemberRepository groupStudyMemberRepository;
        private final GroupStudyAttendanceRepository groupStudyAttendanceRepository;

        @Transactional
        public TimerDTO.Response startTimer(Long userId, TimerDTO.StartRequest request) {
                User user = userRepository.findById(userId)
                                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

                timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                                .ifPresent(timer -> {
                                        throw new IllegalStateException("이미 활성화된 공부 타이머가 존재합니다.");
                                });

                Timer timer = Timer.builder()
                                .user(user)
                                .startTime(request.getStartTime() != null ? request.getStartTime()
                                                : LocalDateTime.now())
                                .status(TimerStatus.STARTED)
                                .groupStudyId(request.getGroupStudyId())
                                .build();

                Timer savedTimer = timerRepository.save(timer);
                log.info("Timer started. timerId={}, userId={}, groupStudyId={}", savedTimer.getId(), userId,
                                request.getGroupStudyId());

                // 그룹스터디 연동이 지정되어 있는 경우 즉시 당일 출석 등록 (출석 체크인)
                if (request.getGroupStudyId() != null) {
                        checkInAttendance(userId, request.getGroupStudyId(), savedTimer.getStartTime());
                }

                return toResponseDTO(savedTimer);
        }

        @Transactional
        public TimerDTO.Response endTimer(Long userId, TimerDTO.EndRequest request) {
                return timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                                .map(timer -> {
                                        timer.setEndTime(request.getEndTime() != null ? request.getEndTime()
                                                        : LocalDateTime.now());
                                        timer.setDurationSeconds(request.getDurationSeconds());
                                        timer.setStatus(TimerStatus.COMPLETED);

                                        Timer savedTimer = timerRepository.save(timer);
                                        log.info("Timer ended. timerId={}, userId={}, durationSeconds={}",
                                                        savedTimer.getId(), userId, request.getDurationSeconds());

                                        // 그룹스터디에 연동되어 학습이 종료된 경우 출석 퇴실 처리 및 총 시간 합산
                                        if (savedTimer.getGroupStudyId() != null) {
                                                checkOutAttendance(userId, savedTimer.getGroupStudyId(),
                                                                savedTimer.getEndTime(),
                                                                savedTimer.getDurationSeconds());
                                        }

                                        return toResponseDTO(savedTimer);
                                })
                                .orElseThrow(() -> new NoSuchElementException(
                                                "활성화된 타이머가 존재하지 않습니다. userId: " + userId));
        }

        @Transactional
        public TimerDTO.Response syncGroupStudyTimer(Long userId, Long groupStudyId) {
                log.info("Synchronizing active timer with groupStudyId. userId={}, groupStudyId={}", userId,
                                groupStudyId);

                Timer timer = timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                                .orElse(null);

                if (timer == null) {
                        log.info("No active timer found to sync for userId={}", userId);
                        return null;
                }

                if (timer.getGroupStudyId() == null) {
                        timer.setGroupStudyId(groupStudyId);
                        timerRepository.save(timer);
                        log.info("Linked active timer id={} to groupStudyId={}", timer.getId(), groupStudyId);
                }

                checkInAttendance(userId, groupStudyId, timer.getStartTime());

                return toResponseDTO(timer);
        }

        public TimerDTO.Response getCurrentTimer(Long userId) {
                return timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                                .map(this::toResponseDTO)
                                .orElse(null);
        }

        public List<TimerDTO.Response> getUserTimers(Long userId) {
                return timerRepository.findByUserIdOrderByStartTimeDesc(userId)
                                .stream()
                                .map(this::toResponseDTO)
                                .collect(Collectors.toList());
        }

        public TimerDTO.TodayStudyTimeResponse getTodayStudyTime(Long userId) {
                LocalDateTime startOfDay = LocalDate.now().atStartOfDay();
                LocalDateTime endOfDay = LocalDate.now().atTime(LocalTime.MAX);

                List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                                userId, TimerStatus.COMPLETED, startOfDay, endOfDay);

                Long totalSeconds = completedTimers.stream()
                                .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds()
                                                : 0L)
                                .sum();

                return TimerDTO.TodayStudyTimeResponse.builder()
                                .userId(userId)
                                .todaySeconds(totalSeconds)
                                .build();
        }

        public TimerDTO.WeeklyStudyTimeResponse getWeeklyStudyTime(Long userId) {
                LocalDate today = LocalDate.now();
                LocalDate startOfWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
                LocalDate endOfWeek = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY));

                LocalDateTime startOfWeekDateTime = startOfWeek.atStartOfDay();
                LocalDateTime endOfWeekDateTime = endOfWeek.atTime(LocalTime.MAX);

                List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                                userId, TimerStatus.COMPLETED, startOfWeekDateTime, endOfWeekDateTime);

                Map<LocalDate, Long> dailySecondsMap = completedTimers.stream()
                                .collect(Collectors.groupingBy(
                                                timer -> timer.getEndTime().toLocalDate(),
                                                Collectors.summingLong(timer -> timer.getDurationSeconds() != null
                                                                ? timer.getDurationSeconds()
                                                                : 0L)));

                Long totalSeconds = completedTimers.stream()
                                .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds()
                                                : 0L)
                                .sum();

                Set<LocalDate> attendanceDaysSet = completedTimers.stream()
                                .filter(timer -> timer.getDurationSeconds() != null && timer.getDurationSeconds() > 0)
                                .map(timer -> timer.getEndTime().toLocalDate())
                                .collect(Collectors.toSet());
                Integer attendanceDays = attendanceDaysSet.size();

                Long averageSeconds = (attendanceDays > 0) ? (totalSeconds / attendanceDays) : 0L;

                List<TimerDTO.DailyStudyTime> dailyStudyTimes = new ArrayList<>();
                LocalDate currentDay = startOfWeek;
                while (!currentDay.isAfter(endOfWeek)) {
                        Long seconds = dailySecondsMap.getOrDefault(currentDay, 0L);
                        dailyStudyTimes.add(TimerDTO.DailyStudyTime.builder()
                                        .date(currentDay.toString())
                                        .day(currentDay.getDayOfWeek().toString())
                                        .seconds(seconds)
                                        .build());
                        currentDay = currentDay.plusDays(1);
                }

                return TimerDTO.WeeklyStudyTimeResponse.builder()
                                .userId(userId)
                                .totalSeconds(totalSeconds)
                                .averageSeconds(averageSeconds)
                                .attendanceDays(attendanceDays)
                                .dailyStats(dailyStudyTimes)
                                .build();
        }

        private void checkInAttendance(Long userId, Long groupStudyId, LocalDateTime checkInTime) {
                log.info("Processing group attendance check-in. userId={}, groupId={}", userId, groupStudyId);

                // 스터디 멤버인지 확인
                if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupStudyId, userId,
                                GroupStudyMemberStatus.JOINED)) {
                        log.warn("User is not a member of group study. Skipping attendance. userId={}, groupId={}",
                                        userId, groupStudyId);
                        return;
                }

                GroupStudy groupStudy = groupStudyRepository.findById(groupStudyId).orElse(null);
                User user = userRepository.findById(userId).orElse(null);

                if (groupStudy == null || user == null)
                        return;

                LocalDate today = LocalDate.now();

                // 이미 오늘 출석 일지가 존재한다면 넘어가기
                groupStudyAttendanceRepository.findByGroupStudyIdAndUserIdAndDate(groupStudyId, userId, today)
                                .ifPresentOrElse(
                                                existing -> log.info(
                                                                "Attendance entry already exists for today. entryId={}",
                                                                existing.getId()),
                                                () -> {
                                                        GroupStudyAttendance attendance = GroupStudyAttendance.builder()
                                                                        .groupStudy(groupStudy)
                                                                        .user(user)
                                                                        .date(today)
                                                                        .checkInTime(checkInTime)
                                                                        .status("PRESENT")
                                                                        .studyDurationSeconds(0L)
                                                                        .build();
                                                        groupStudyAttendanceRepository.save(attendance);
                                                        log.info("New PRESENT attendance entry logged for today. groupId={}, userId={}",
                                                                        groupStudyId, userId);
                                                });
        }

        private void checkOutAttendance(Long userId, Long groupStudyId, LocalDateTime checkOutTime,
                        Long durationSeconds) {
                log.info("Processing group attendance check-out. userId={}, groupId={}, durationSeconds={}", userId,
                                groupStudyId, durationSeconds);

                LocalDate today = LocalDate.now();
                groupStudyAttendanceRepository.findByGroupStudyIdAndUserIdAndDate(groupStudyId, userId, today)
                                .ifPresent(attendance -> {
                                        attendance.setCheckOutTime(checkOutTime);
                                        attendance.setStudyDurationSeconds(
                                                        (attendance.getStudyDurationSeconds() != null
                                                                        ? attendance.getStudyDurationSeconds()
                                                                        : 0L) + durationSeconds);
                                        groupStudyAttendanceRepository.save(attendance);
                                        log.info("Updated attendance study duration. entryId={}, totalSeconds={}",
                                                        attendance.getId(), attendance.getStudyDurationSeconds());
                                });
        }

        private TimerDTO.Response toResponseDTO(Timer timer) {
                return TimerDTO.Response.builder()
                                .id(timer.getId())
                                .userId(timer.getUser().getId())
                                .groupStudyId(timer.getGroupStudyId())
                                .startTime(timer.getStartTime())
                                .endTime(timer.getEndTime())
                                .durationSeconds(timer.getDurationSeconds())
                                .status(timer.getStatus())
                                .createdAt(timer.getCreatedAt())
                                .updatedAt(timer.getUpdatedAt())
                                .build();
        }
}
