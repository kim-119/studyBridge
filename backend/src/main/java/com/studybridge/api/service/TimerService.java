package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.repository.TimerRepository;
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
import java.util.stream.Collectors;
import java.util.stream.IntStream;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class TimerService {

    private final TimerRepository timerRepository;

    @Transactional
    public TimerDTO.Response startTimer(TimerDTO.StartRequest request) {

        timerRepository.findByUserIdAndStatus(request.getUserId(), TimerStatus.STARTED)
                .ifPresent(timer -> {
                    throw new IllegalStateException("User " + request.getUserId() + " already has an active timer.");
                });

        Timer timer = Timer.builder()
                .userId(request.getUserId())
                .startTime(request.getStartTime() != null ? request.getStartTime() : LocalDateTime.now())
                .status(TimerStatus.STARTED)
                .build();

        Timer savedTimer = timerRepository.save(timer);
        return toResponseDTO(savedTimer);
    }

    @Transactional
    public TimerDTO.Response endTimer(Long userId, TimerDTO.EndRequest request) {
        Timer timer = timerRepository.findByUserIdAndStatus(userId, TimerStatus.STARTED)
                .orElseThrow(() -> new NoSuchElementException("No active timer found for user " + userId));

        timer.setEndTime(request.getEndTime() != null ? request.getEndTime() : LocalDateTime.now());
        timer.setDurationMinutes(request.getDurationMinutes());
        timer.setStatus(TimerStatus.COMPLETED);

        Timer updatedTimer = timerRepository.save(timer);
        return toResponseDTO(updatedTimer);
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
        // 이번 주 월요일 (ISO 8601 기준)
        LocalDate startOfWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        // 이번 주 일요일
        LocalDate endOfWeek = today.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY));

        LocalDateTime startOfWeekDateTime = startOfWeek.atStartOfDay();
        LocalDateTime endOfWeekDateTime = endOfWeek.atTime(LocalTime.MAX);

        List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                userId, TimerStatus.COMPLETED, startOfWeekDateTime, endOfWeekDateTime);

        // 요일별로 그룹화 및 합산
        Map<DayOfWeek, Long> weeklyMinutesMap = completedTimers.stream()
                .collect(Collectors.groupingBy(
                        timer -> timer.getEndTime().getDayOfWeek(),
                        Collectors.summingLong(Timer::getDurationMinutes)
                ));

        // 월~일 순서로 데이터 생성, 없는 요일은 0분 처리
        List<TimerDTO.DailyStudyTime> dailyStudyTimes = new ArrayList<>();
        DayOfWeek[] daysOfWeek = {DayOfWeek.MONDAY, DayOfWeek.TUESDAY, DayOfWeek.WEDNESDAY,
                                  DayOfWeek.THURSDAY, DayOfWeek.FRIDAY, DayOfWeek.SATURDAY, DayOfWeek.SUNDAY};
        String[] dayNames = {"월", "화", "수", "목", "금", "토", "일"};

        IntStream.range(0, daysOfWeek.length).forEach(i -> {
            DayOfWeek day = daysOfWeek[i];
            String dayName = dayNames[i];
            Long minutes = weeklyMinutesMap.getOrDefault(day, 0L);
            dailyStudyTimes.add(TimerDTO.DailyStudyTime.builder()
                    .day(dayName)
                    .minutes(minutes)
                    .build());
        });

        return TimerDTO.WeeklyStudyTimeResponse.builder()
                .userId(userId)
                .data(dailyStudyTimes)
                .build();
    }

    private TimerDTO.Response toResponseDTO(Timer timer) {
        return TimerDTO.Response.builder()
                .id(timer.getId())
                .userId(timer.getUserId())
                .startTime(timer.getStartTime())
                .endTime(timer.getEndTime())
                .durationMinutes(timer.getDurationMinutes())
                .status(timer.getStatus())
                .createdAt(timer.getCreatedAt())
                .updatedAt(timer.getUpdatedAt())
                .build();
    }
}
