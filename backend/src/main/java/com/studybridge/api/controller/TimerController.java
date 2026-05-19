package com.studybridge.api.controller;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.service.TimerService;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.NoSuchElementException;

@RestController
@RequiredArgsConstructor
@RequestMapping("/api")
public class TimerController {

    private final TimerService timerService;

    // 타이머 시작
    @PostMapping("/timers/start")
    public ResponseEntity<TimerDTO.Response> startTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody TimerDTO.StartRequest request) {
        try {
            TimerDTO.Response response = timerService.startTimer(userDetails.getId(), request);
            return ResponseEntity.status(HttpStatus.CREATED).body(response);
        } catch (IllegalStateException e) {
            return ResponseEntity.status(HttpStatus.CONFLICT).build();
        }
    }

    // 타이머 종료
    @PostMapping("/timers/end")
    public ResponseEntity<TimerDTO.Response> endTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody TimerDTO.EndRequest request) {
        try {
            TimerDTO.Response response = timerService.endTimer(userDetails.getId(), request);
            return ResponseEntity.ok(response);
        } catch (NoSuchElementException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND).build();
        }
    }

    // 사용자별 현재 타이머 조회
    @GetMapping("/timers/current")
    public ResponseEntity<TimerDTO.Response> getCurrentTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        TimerDTO.Response response = timerService.getCurrentTimer(userDetails.getId());
        if (response != null) {
            return ResponseEntity.ok(response);
        } else {
            return ResponseEntity.status(HttpStatus.NO_CONTENT).build();
        }
    }

    // 사용자별 모든 타이머 기록 조회
    @GetMapping("/timers")
    public ResponseEntity<List<TimerDTO.Response>> getUserTimers(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        List<TimerDTO.Response> response = timerService.getUserTimers(userDetails.getId());
        return ResponseEntity.ok(response);
    }

    // 사용자별 일일 학습 시간 조회
    @GetMapping("/study-time/today")
    public ResponseEntity<TimerDTO.TodayStudyTimeResponse> getTodayStudyTime(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        TimerDTO.TodayStudyTimeResponse response = timerService.getTodayStudyTime(userDetails.getId());
        return ResponseEntity.ok(response);
    }

    // 사용자별 주간 학습 시간 조회
    @GetMapping("/study-time/weekly")
    public ResponseEntity<TimerDTO.WeeklyStudyTimeResponse> getWeeklyStudyTime(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        TimerDTO.WeeklyStudyTimeResponse response = timerService.getWeeklyStudyTime(userDetails.getId());
        return ResponseEntity.ok(response);
    }
}
