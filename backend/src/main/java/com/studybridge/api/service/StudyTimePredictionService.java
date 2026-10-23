package com.studybridge.api.service;

import com.studybridge.api.dto.StudyTimePredictionDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.repository.TimerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.ArrayList;
import java.util.List;

/**
 * 내일 학습 시간 예측. FastAPI /api/ai/predict-study-time 계약(weeklyStudySeconds[7], 초 단위)에 맞춰 호출하고
 * 응답(predictedStudySeconds/method/confidence)을 프론트 계약(predictedSeconds/confidence/message)으로 명시 변환한다.
 *
 * 폴백 정책: 네트워크/5xx 장애에만 로컬 가중평균 폴백. 4xx(계약/설정 오류)는 [AI-CONTRACT] ERROR 로 명시 기록한다
 *  (400 을 폴백으로 영구히 숨기지 않기 위함 — 계약 회귀가 로그에서 즉시 드러나야 한다).
 */
@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class StudyTimePredictionService {

    static final String PREDICT_PATH = "/api/ai/predict-study-time";

    private final TimerRepository timerRepository;
    private final WebClient fastApiWebClient;

    @Value("${ai.server.fastapi.predict-timeout-seconds:20}")
    private long predictTimeoutSeconds;

    public StudyTimePredictionDTO.Response predictTomorrow(Long userId) {
        log.info("Starting study time prediction for userId={}", userId);

        List<Double> weeklySeconds = collectWeeklyStudySeconds(userId);
        StudyTimePredictionDTO.Request request = StudyTimePredictionDTO.Request.builder()
                .userId(userId)
                .weeklyStudySeconds(weeklySeconds)
                .build();

        try {
            log.info("Sending prediction request to FastAPI userId={} weeklyStudySeconds={}", userId, weeklySeconds);
            // MVC(Tomcat) 요청 스레드에서의 block() — reactor 이벤트 루프가 아니므로 허용.
            StudyTimePredictionDTO.FastApiResponse remote = fastApiWebClient.post()
                    .uri(PREDICT_PATH)
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(StudyTimePredictionDTO.FastApiResponse.class)
                    .block(Duration.ofSeconds(Math.max(3, predictTimeoutSeconds)));

            StudyTimePredictionDTO.Response adapted = toResponse(userId, remote);
            if (adapted != null) {
                return adapted;
            }
            log.warn("[predict-study-time] FastAPI 응답에 predictedStudySeconds 가 없어 로컬 폴백 userId={}", userId);
        } catch (WebClientResponseException e) {
            if (e.getStatusCode().is4xxClientError()) {
                // 계약/설정 오류: 다른 경로로 숨기지 않고 명시적으로 남긴다.
                log.error("[AI-CONTRACT] predict-study-time status={} body={} — 요청 계약(weeklyStudySeconds[7]) 확인 필요",
                        e.getStatusCode().value(), truncate(e.getResponseBodyAsString()));
            } else {
                log.warn("[predict-study-time] FastAPI {} — 로컬 폴백 userId={}", e.getStatusCode().value(), userId);
            }
        } catch (Exception e) {
            log.warn("[predict-study-time] FastAPI 연결 실패 — 로컬 폴백 userId={} err={}", userId, e.toString());
        }

        return localFallback(userId, weeklySeconds);
    }

    /** 최근 7일(오래된 날 → 오늘) 완료 타이머 합계(초). 항상 정확히 7개. */
    List<Double> collectWeeklyStudySeconds(Long userId) {
        List<Double> weeklySeconds = new ArrayList<>(StudyTimePredictionDTO.WEEK_DAYS);
        LocalDate today = LocalDate.now();
        for (int i = StudyTimePredictionDTO.WEEK_DAYS - 1; i >= 0; i--) {
            LocalDate targetDate = today.minusDays(i);
            LocalDateTime startOfDay = targetDate.atStartOfDay();
            LocalDateTime endOfDay = targetDate.atTime(LocalTime.MAX);

            List<Timer> completedTimers = timerRepository.findByUserIdAndStatusAndEndTimeBetween(
                    userId, TimerStatus.COMPLETED, startOfDay, endOfDay);

            long totalSeconds = completedTimers.stream()
                    .mapToLong(timer -> timer.getDurationSeconds() != null ? timer.getDurationSeconds() : 0L)
                    .sum();
            weeklySeconds.add((double) Math.max(0L, totalSeconds));
        }
        return weeklySeconds;
    }

    /** FastAPI 응답 → 프론트 계약 어댑터. predictedStudySeconds 가 없으면 null(호출자가 폴백). */
    static StudyTimePredictionDTO.Response toResponse(Long userId, StudyTimePredictionDTO.FastApiResponse remote) {
        if (remote == null || remote.getPredictedStudySeconds() == null) {
            return null;
        }
        double predicted = Math.max(0.0, Math.round(remote.getPredictedStudySeconds()));
        String method = remote.getMethod() != null ? remote.getMethod() : "unknown";
        double confidence = remote.getConfidence() != null ? remote.getConfidence() : 0.5;
        String message = "transformer".equalsIgnoreCase(method)
                ? String.format("AI 예측 모델이 최근 7일 학습 패턴으로 예상한 내일 공부 시간(약 %.1f시간)입니다.", predicted / 3600.0)
                : String.format("최근 7일 학습 패턴 가중 평균(약 %.1f시간)을 바탕으로 예측된 공부 시간입니다.", predicted / 3600.0);
        return StudyTimePredictionDTO.Response.builder()
                .userId(userId)
                .predictedSeconds(predicted)
                .confidence(confidence)
                .message(message)
                .source("fastapi:" + method)
                .build();
    }

    static StudyTimePredictionDTO.Response localFallback(Long userId, List<Double> weeklySeconds) {
        double sumHours = weeklySeconds.stream().mapToDouble(Double::doubleValue).sum() / 3600.0;
        double averageHours = sumHours / StudyTimePredictionDTO.WEEK_DAYS;
        if (averageHours < 0.1) {
            averageHours = 2.0;
        }
        double predictedSeconds = Math.round(averageHours * 3600.0);
        return StudyTimePredictionDTO.Response.builder()
                .userId(userId)
                .predictedSeconds(predictedSeconds)
                .confidence(0.7)
                .message(String.format("최근 7일 학습 패턴 평균(약 %.1f시간)을 바탕으로 예측된 공부 시간입니다.", averageHours))
                .source("spring:local_fallback")
                .build();
    }

    private static String truncate(String s) {
        if (s == null) return "";
        return s.length() > 300 ? s.substring(0, 300) + "…" : s;
    }
}
