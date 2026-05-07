package com.studybridge.api.controller;

import com.studybridge.api.dto.StudySessionDTO;
import com.studybridge.api.service.StudySessionService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.NoSuchElementException;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/study-sessions")
@CrossOrigin(origins = "http://localhost:3000")
public class StudySessionController {

    private final StudySessionService studySessionService;

    @PostMapping("/start")
    public ResponseEntity<StudySessionDTO.Response> startStudySession(
            @PathVariable Long userId,
            @RequestBody StudySessionDTO.StartRequest request) {
        if (!userId.equals(request.getUserId())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }

        try {
            StudySessionDTO.Response response = studySessionService.startStudySession(request);
            return ResponseEntity.status(HttpStatus.CREATED).body(response);
        } catch (IllegalStateException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).build();
        }
    }

    @PostMapping("/end")
    public ResponseEntity<StudySessionDTO.Response> endStudySession(
            @PathVariable Long userId,
            @RequestBody StudySessionDTO.EndRequest request) {
        try {
            StudySessionDTO.Response response = studySessionService.endStudySession(userId, request);
            return ResponseEntity.ok(response);
        } catch (NoSuchElementException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }
    }

    @GetMapping("/current")
    public ResponseEntity<StudySessionDTO.Response> getCurrentStudySession(@PathVariable Long userId) {
        StudySessionDTO.Response response = studySessionService.getCurrentStudySession(userId);
        if (response != null) {
            return ResponseEntity.ok(response);
        } else {
            return ResponseEntity.status(HttpStatus.NO_CONTENT).build();
        }
    }

    @GetMapping
    public ResponseEntity<List<StudySessionDTO.Response>> getUserStudySessions(@PathVariable Long userId) {
        List<StudySessionDTO.Response> response = studySessionService.getUserStudySessions(userId);
        return ResponseEntity.ok(response);
    }
}
