package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User; // User 엔티티 import
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
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Set;
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class TimerService {

    private final TimerRepository timerRepository;
    private final UserRepository userRepository; // UserRepository 주입

    @Transactional
    public TimerDTO.Response startTimer(TimerDTO.StartRequest request) {
        // userId로 User 엔티티 조회
        User user = userRepository.findById(request.getUserId())
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + request.getUserId()));

        timerRepository.findByUserIdAndStatus(request.getUserId(), TimerStatus.STARTED)
                .ifPresent(timer -> {
                    throw new IllegalStateException("User " + request.getUserId() + " already has an active timer.");
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
        return timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                .map(timer -> {
                    timer.setEndTime(request.getEndTime() != null ? request.getEndTime() : LocalDateTime.now());
                    timer.setDurationMinutes(request.getDurationMinutes());
                    timer.setStatus(TimerStatus.COMPLETED);
                    Timer savedTimer = timerRepository.save(timer);
                    return toResponseDTO(savedTimer);
                })
                .orElseThrow(() -> new NoSuchElementException("No active timer found for user " + userId));
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

    // --- 추가된 서비스 로직 ---

    /**
     * 오늘 공부 시간을 조회합니다.
     * @param userId 사용자 ID
     * @return 오늘 공부 시간 (분)
     */
    public TimerDTO.TodayStudyTimeResponse getTodayStudyTime(Long userId) {
        LocalDateTime startOfDay = LocalDate.now().atStartOfDay();
        LocalDateTime endOfDay = LocalDate.now().atTime(LocalTime.MAX);

        List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                userId, TimerStatus.COMPLETED, startOfDay, endOfDay);

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
        LocalDate today = LocalDate.now();
        LocalDate startOfWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        LocalDate endOfWeek = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY));

        LocalDateTime startOfWeekDateTime = startOfWeek.atStartOfDay();
        LocalDateTime endOfWeekDateTime = endOfWeek.atTime(LocalTime.MAX);

        List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                userId, TimerStatus.COMPLETED, startOfWeekDateTime, endOfWeekDateTime);

        // 요일별로 그룹화 및 합산
        Map<LocalDate, Long> dailyMinutesMap = completedTimers.stream()
                .collect(Collectors.groupingBy(
                        timer -> timer.getEndTime().toLocalDate(),
                        Collectors.summingLong(Timer::getDurationMinutes)
                ));

        // 총 공부 시간
        Long totalMinutes = completedTimers.stream()
                .mapToLong(Timer::getDurationMinutes)
                .sum();

        // 출석일 수 (공부 시간이 0분 이상인 날)
        Set<LocalDate> attendanceDaysSet = completedTimers.stream()
                .filter(timer -> timer.getDurationMinutes() > 0)
                .map(timer -> timer.getEndTime().toLocalDate())
                .collect(Collectors.toSet());
        Integer attendanceDays = attendanceDaysSet.size();

        // 평균 공부 시간 (출석일 기준으로 계산)
        Long averageMinutes = (attendanceDays > 0) ? (totalMinutes / attendanceDays) : 0L;


        // 월~일 순서로 데이터 생성, 없는 요일은 0분 처리
        List<TimerDTO.DailyStudyTime> dailyStudyTimes = new ArrayList<>();
        LocalDate currentDay = startOfWeek;
        while (!currentDay.isAfter(endOfWeek)) {
            Long minutes = dailyMinutesMap.getOrDefault(currentDay, 0L);
            dailyStudyTimes.add(TimerDTO.DailyStudyTime.builder()
                    .date(currentDay.toString()) // YYYY-MM-DD 형식
                    .day(currentDay.getDayOfWeek().toString()) // MONDAY, TUESDAY...
                    .minutes(minutes)
                    .build());
            currentDay = currentDay.plusDays(1);
        }

        return TimerDTO.WeeklyStudyTimeResponse.builder()
                .userId(userId)
                .totalMinutes(totalMinutes)
                .averageMinutes(averageMinutes)
                .attendanceDays(attendanceDays)
                .dailyStats(dailyStudyTimes)
                .build();
    }

    private TimerDTO.Response toResponseDTO(Timer timer) {
        return TimerDTO.Response.builder()
                .id(timer.getId())
                .userId(timer.getUser().getId()) // User 엔티티에서 ID 가져오기
                .startTime(timer.getStartTime())
                .endTime(timer.getEndTime())
                .durationMinutes(timer.getDurationMinutes())
                .status(timer.getStatus())
                .createdAt(timer.getCreatedAt())
                .updatedAt(timer.getUpdatedAt())
                .build();
    }
}
