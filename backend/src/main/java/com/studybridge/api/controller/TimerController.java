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
@RequestMapping("/api/users/{userId}") // 상위 경로를 /api/users/{userId}로 유지
@CrossOrigin(origins = "http://localhost:3000")
public class TimerController {

    private final TimerService timerService;

    // 기존 타이머 관리 API들은 /api/users/{userId}/timers 로 매핑
    @PostMapping("/timers/start")
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

    @PostMapping("/timers/end")
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

    @GetMapping("/timers/current")
    public ResponseEntity<TimerDTO.Response> getCurrentTimer(@PathVariable Long userId) {
        TimerDTO.Response response = timerService.getCurrentTimer(userId);
        if (response != null) {
            return ResponseEntity.ok(response);
        } else {
            return ResponseEntity.status(HttpStatus.NO_CONTENT).build();
        }
    }

    @GetMapping("/timers")
    public ResponseEntity<List<TimerDTO.Response>> getUserTimers(@PathVariable Long userId) {
        List<TimerDTO.Response> response = timerService.getUserTimers(userId);
        return ResponseEntity.ok(response);
    }

    // --- 추가된 study-time 집계 API ---
    // 요청하신 /api/timers/weekly?userId={userId} 형식에 맞추기 위해 @GetMapping에 전체 경로 명시
    // userId는 @RequestParam으로 받음

    @GetMapping("/api/timers/today") // 전체 경로 명시
    public ResponseEntity<TimerDTO.TodayStudyTimeResponse> getTodayStudyTime(@RequestParam Long userId) {
        TimerDTO.TodayStudyTimeResponse response = timerService.getTodayStudyTime(userId);
        return ResponseEntity.ok(response);
    }

    @GetMapping("/api/timers/weekly") // 전체 경로 명시
    public ResponseEntity<TimerDTO.WeeklyStudyTimeResponse> getWeeklyStudyTime(@RequestParam Long userId) {
        TimerDTO.WeeklyStudyTimeResponse response = timerService.getWeeklyStudyTime(userId);
        return ResponseEntity.ok(response);
    }
}
