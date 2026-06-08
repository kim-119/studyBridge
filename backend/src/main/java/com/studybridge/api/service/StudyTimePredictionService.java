package com.studybridge.api.service;

import com.studybridge.api.dto.StudyTimePredictionDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.repository.TimerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class StudyTimePredictionService {

    private final TimerRepository timerRepository;
    private final WebClient fastApiWebClient;

    public StudyTimePredictionDTO.Response predictTomorrow(Long userId) {
        log.info("Starting study time prediction for userId={}", userId);

        List<Double> last7DaysHours = new ArrayList<>();
        LocalDate today = LocalDate.now();

        for (int i = 6; i >= 0; i--) {
            LocalDate targetDate = today.minusDays(i);
            LocalDateTime startOfDay = targetDate.atStartOfDay();
            LocalDateTime endOfDay = targetDate.atTime(LocalTime.MAX);

            List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                    userId, TimerStatus.COMPLETED, startOfDay, endOfDay);

            long totalSeconds = completedTimers.stream()
                    .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds() : 0L)
                    .sum();

            double hours = totalSeconds / 3600.0;
            last7DaysHours.add(hours);
        }

        StudyTimePredictionDTO.Request request = StudyTimePredictionDTO.Request.builder()
                .userId(userId)
                .last7DaysHours(last7DaysHours)
                .build();

        try {
            log.info("Sending prediction request to FastAPI for userId={}, hours={}", userId, last7DaysHours);
            StudyTimePredictionDTO.Response response = fastApiWebClient.post()
                    .uri("/api/ai/predict-study-time")
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(StudyTimePredictionDTO.Response.class)
                    .block();

            if (response != null) {
                return response;
            }
        } catch (Exception e) {
            log.error("Failed to connect or receive prediction from FastAPI. Activating fallback. Error: ", e);
        }

        double sumHours = last7DaysHours.stream().mapToDouble(Double::doubleValue).sum();
        double averageHours = sumHours / 7.0;

        if (averageHours < 0.1) {
            averageHours = 2.0; 
        }

        double predictedSeconds = Math.round(averageHours * 3600.0);
        String fallbackMessage = String.format(
                "최근 7일 학습 패턴 평균(약 %.1f시간)을 바탕으로 예측된 공부 시간입니다.", 
                averageHours);

        return StudyTimePredictionDTO.Response.builder()
                .userId(userId)
                .predictedSeconds(predictedSeconds)
                .confidence(0.7)
                .message(fallbackMessage)
                .build();
    }
}
