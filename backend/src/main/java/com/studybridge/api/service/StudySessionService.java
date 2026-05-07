package com.studybridge.api.service;

import com.studybridge.api.dto.StudySessionDTO;
import com.studybridge.api.entity.StudySession;
import com.studybridge.api.entity.StudySessionStatus;
import com.studybridge.api.repository.StudySessionRepository;
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
public class StudySessionService {

    private final StudySessionRepository studySessionRepository;

    @Transactional
    public StudySessionDTO.Response startStudySession(StudySessionDTO.StartRequest request) {

        studySessionRepository.findByUserIdAndStatus(request.getUserId(), StudySessionStatus.STARTED)
                .ifPresent(session -> {
                    throw new IllegalStateException("User " + request.getUserId() + " already has an active study session.");
                });

        StudySession studySession = StudySession.builder()
                .userId(request.getUserId())
                .startTime(request.getStartTime() != null ? request.getStartTime() : LocalDateTime.now())
                .status(StudySessionStatus.STARTED)
                .build();

        StudySession savedSession = studySessionRepository.save(studySession);
        return toResponseDTO(savedSession);
    }

    @Transactional
    public StudySessionDTO.Response endStudySession(Long userId, StudySessionDTO.EndRequest request) {
        StudySession studySession = studySessionRepository.findByUserIdAndStatus(userId, StudySessionStatus.STARTED)
                .orElseThrow(() -> new NoSuchElementException("No active study session found for user " + userId));

        studySession.setEndTime(request.getEndTime() != null ? request.getEndTime() : LocalDateTime.now());
        studySession.setDurationMinutes(request.getDurationMinutes());
        studySession.setStatus(StudySessionStatus.COMPLETED);

        StudySession updatedSession = studySessionRepository.save(studySession);
        return toResponseDTO(updatedSession);
    }

    public StudySessionDTO.Response getCurrentStudySession(Long userId) {
        return studySessionRepository.findByUserIdAndStatus(userId, StudySessionStatus.STARTED)
                .map(this::toResponseDTO)
                .orElse(null);
    }

    public List<StudySessionDTO.Response> getUserStudySessions(Long userId) {
        return studySessionRepository.findByUserIdOrderByStartTimeDesc(userId)
                .stream()
                .map(this::toResponseDTO)
                .collect(Collectors.toList());
    }

    private StudySessionDTO.Response toResponseDTO(StudySession studySession) {
        return StudySessionDTO.Response.builder()
                .id(studySession.getId())
                .userId(studySession.getUserId())
                .startTime(studySession.getStartTime())
                .endTime(studySession.getEndTime())
                .durationMinutes(studySession.getDurationMinutes())
                .status(studySession.getStatus())
                .createdAt(studySession.getCreatedAt())
                .updatedAt(studySession.getUpdatedAt())
                .build();
    }
}