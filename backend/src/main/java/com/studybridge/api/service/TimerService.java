package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.repository.TimerRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;

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