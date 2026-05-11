package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.TimerRepository;
import com.studybridge.api.repository.UserRepository; // UserRepository import
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class TimerService {

    private final TimerRepository timerRepository;
    private final UserRepository userRepository; // UserRepository 주입

    // userId로 User 엔티티를 찾는 헬퍼 메서드
    private User findUserById(Long userId) {
        return userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with id: " + userId));
    }

    @Transactional
    public TimerDTO.Response startTimer(TimerDTO.StartRequest request) {
        User user = findUserById(request.getUserId()); // User 엔티티 조회

        timerRepository.findByUserAndStatus(user, TimerStatus.STARTED) // User 엔티티 사용
                .ifPresent(timer -> {
                    throw new IllegalStateException("User " + user.getId() + " already has an active timer.");
                });

        Timer timer = Timer.builder()
                .user(user) // User 엔티티 설정
                .startTime(request.getStartTime() != null ? request.getStartTime() : LocalDateTime.now())
                .status(TimerStatus.STARTED)
                .build();

        Timer savedTimer = timerRepository.save(timer);
        return toResponseDTO(savedTimer);
    }

    @Transactional
    public TimerDTO.Response endTimer(Long userId, TimerDTO.EndRequest request) {
        User user = findUserById(userId); // User 엔티티 조회

        Timer timer = timerRepository.findByUserAndStatus(user, TimerStatus.STARTED) // User 엔티티 사용
                .orElseThrow(() -> new NoSuchElementException("No active timer found for user " + userId));

        timer.setEndTime(request.getEndTime() != null ? request.getEndTime() : LocalDateTime.now());
        timer.setDurationMinutes(request.getDurationMinutes());
        timer.setStatus(TimerStatus.COMPLETED);

        Timer updatedTimer = timerRepository.save(timer);
        return toResponseDTO(updatedTimer);
    }

    public TimerDTO.Response getCurrentTimer(Long userId) {
        User user = findUserById(userId); // User 엔티티 조회
        return timerRepository.findByUserAndStatus(user, TimerStatus.STARTED) // User 엔티티 사용
                .map(this::toResponseDTO)
                .orElse(null);
    }

    public List<TimerDTO.Response> getUserTimers(Long userId) {
        User user = findUserById(userId); // User 엔티티 조회
        return timerRepository.findByUserOrderByStartTimeDesc(user) // User 엔티티 사용
                .stream()
                .map(this::toResponseDTO)
                .collect(Collectors.toList());
    }

    /**
     * 오늘 공부 시간을 조회합니다.
     * @param userId 사용자 ID
     * @return 오늘 공부 시간 (분)
     */
    public TimerDTO.TodayStudyTimeResponse getTodayStudyTime(Long userId) {
        User user = findUserById(userId); // User 엔티티 조회
        LocalDateTime startOfDay = LocalDate.now().atStartOfDay();
        LocalDateTime endOfDay = LocalDate.now().atTime(LocalTime.MAX);

        List<Timer> completedTimers = timerRepository.findByUserAndStatusAndEndTimeBetween( // User 엔티티 사용
                user, TimerStatus.COMPLETED, startOfDay, endOfDay);

        Long totalMinutes = completedTimers.stream()
                .mapToLong(Timer::getDurationMinutes)
                .sum();

        return TimerDTO.TodayStudyTimeResponse.builder()
                .userId(userId)
                .todayMinutes(totalMinutes)
                .build();
    }

    /**
     * 주간 공부 시간을 조회합니다. (월요일부터 일요일까지)
     * @param userId 사용자 ID
     * @return 주간 공부 시간 데이터
     */
    public TimerDTO.WeeklyStudyTimeResponse getWeeklyStudyTime(Long userId) {
        User user = findUserById(userId); // User 엔티티 조회
        LocalDate today = LocalDate.now();
        // 이번 주 월요일 (ISO 8601 기준)
        LocalDate startOfWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        // 이번 주 일요일
        LocalDate endOfWeek = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY));

        LocalDateTime startOfWeekDateTime = startOfWeek.atStartOfDay();
        LocalDateTime endOfWeekDateTime = endOfWeek.atTime(LocalTime.MAX);

        List<Timer> completedTimers = timerRepository.findByUserAndStatusAndEndTimeBetween( // User 엔티티 사용
                user, TimerStatus.COMPLETED, startOfWeekDateTime, endOfWeekDateTime);

        // 날짜별로 그룹화 및 합산
        Map<LocalDate, Long> dailyMinutesMap = completedTimers.stream()
                .collect(Collectors.groupingBy(
                        timer -> timer.getEndTime().toLocalDate(),
                        Collectors.summingLong(Timer::getDurationMinutes)
                ));

        // 주간 통계 계산
        long totalMinutes = 0L;
        int attendanceDays = 0;

        List<TimerDTO.DailyStudyStats> dailyStats = new ArrayList<>();
        // 월요일부터 일요일까지 순회하며 데이터 생성
        for (int i = 0; i < 7; i++) {
            LocalDate currentDate = startOfWeek.plusDays(i);
            DayOfWeek dayOfWeek = currentDate.getDayOfWeek();
            String dayName = dayOfWeek.toString(); // MONDAY, TUESDAY 등

            Long minutes = dailyMinutesMap.getOrDefault(currentDate, 0L);
            totalMinutes += minutes;
            if (minutes > 0) {
                attendanceDays++;
            }

            dailyStats.add(TimerDTO.DailyStudyStats.builder()
                    .date(currentDate)
                    .day(dayName)
                    .minutes(minutes)
                    .build());
        }

        Long averageMinutes = attendanceDays > 0 ? totalMinutes / attendanceDays : 0L;


        return TimerDTO.WeeklyStudyTimeResponse.builder()
                .userId(userId)
                .totalMinutes(totalMinutes)
                .averageMinutes(averageMinutes)
                .attendanceDays(attendanceDays)
                .dailyStats(dailyStats)
                .build();
    }

    private TimerDTO.Response toResponseDTO(Timer timer) {
        return TimerDTO.Response.builder()
                .id(timer.getId())
                .userId(timer.getUser().getId()) // User 엔티티에서 userId 추출
                .startTime(timer.getStartTime())
                .endTime(timer.getEndTime())
                .durationMinutes(timer.getDurationMinutes())
                .status(timer.getStatus())
                .createdAt(timer.getCreatedAt())
                .updatedAt(timer.getUpdatedAt())
                .build();
    }
}
