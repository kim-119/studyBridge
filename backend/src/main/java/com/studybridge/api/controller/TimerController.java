package com.studybridge.api.controller;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.service.TimerService;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.NoSuchElementException;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api/users/{userId}/timers")
@CrossOrigin(origins = "http://localhost:3000")
public class TimerController {

    private final TimerService timerService;

    @PostMapping("/start")
    public ResponseEntity<TimerDTO.Response> startTimer(
            @PathVariable Long userId,
            @RequestBody TimerDTO.StartRequest request) {
        if (!userId.equals(request.getUserId())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).build();
        }

        try {
            TimerDTO.Response response = timerService.startTimer(request);
            return ResponseEntity.status(HttpStatus.CREATED).body(response);
        } catch (IllegalStateException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).build();
        }
    }

    @PostMapping("/end")
    public ResponseEntity<TimerDTO.Response> endTimer(
            @PathVariable Long userId,
            @RequestBody TimerDTO.EndRequest request) {
        try {
            TimerDTO.Response response = timerService.endTimer(userId, request);
            return ResponseEntity.ok(response);
        } catch (NoSuchElementException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }
    }

    @GetMapping("/current")
    public ResponseEntity<TimerDTO.Response> getCurrentTimer(@PathVariable Long userId) {
        TimerDTO.Response response = timerService.getCurrentTimer(userId);
        if (response != null) {
            return ResponseEntity.ok(response);
        } else {
            return ResponseEntity.status(HttpStatus.NO_CONTENT).build();
        }
    }

    @GetMapping
    public ResponseEntity<List<TimerDTO.Response>> getUserTimers(@PathVariable Long userId) {
        List<TimerDTO.Response> response = timerService.getUserTimers(userId);
        return ResponseEntity.ok(response);
    }
}
