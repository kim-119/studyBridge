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

@RestController
@RequiredArgsConstructor
@RequestMapping("/api")
public class TimerController {

    private final TimerService timerService;

    // 타이머 시작 — 활성 세션이 같은 컨텍스트면 그대로 반환(200, resumed=true), 새로 만들면 201. 다른 컨텍스트의 활성 세션은 자동 종료 후 교체.
    @PostMapping("/timers/start")
    public ResponseEntity<TimerDTO.Response> startTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody(required = false) TimerDTO.StartRequest request) {
        TimerDTO.Response response = timerService.startTimer(userDetails.getId(), request);
        HttpStatus status = Boolean.TRUE.equals(response.getResumed()) ? HttpStatus.OK : HttpStatus.CREATED;
        return ResponseEntity.status(status).body(response);
    }

    // heartbeat(30초 권장): 진행분을 출석 원장에 크레딧. 활성 세션 없음 → 204
    @PostMapping("/timers/heartbeat")
    public ResponseEntity<TimerDTO.Response> heartbeat(@AuthenticationPrincipal CustomUserDetails userDetails) {
        TimerDTO.Response response = timerService.heartbeat(userDetails.getId());
        return response != null ? ResponseEntity.ok(response) : ResponseEntity.noContent().build();
    }

    // 타이머 종료(멱등): 활성 세션이 없으면 최근 세션을 그대로 반환(200), 세션이 전혀 없으면 204.
    @PostMapping("/timers/end")
    public ResponseEntity<TimerDTO.Response> endTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestBody(required = false) TimerDTO.EndRequest request) {
        TimerDTO.Response response = timerService.endTimer(userDetails.getId(), request);
        return response != null ? ResponseEntity.ok(response) : ResponseEntity.noContent().build();
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

    // 그룹스터디 입장 시: 이 그룹의 공부 세션을 보장(없으면 시작, 다른 컨텍스트면 교체). 비멤버 → 403
    @PostMapping("/timers/sync/{groupStudyId}")
    public ResponseEntity<TimerDTO.Response> syncTimer(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupStudyId,
            @RequestParam(value = "heartbeat", required = false, defaultValue = "false") boolean supportsHeartbeat) {
        TimerDTO.Response response = timerService.syncGroupStudyTimer(userDetails.getId(), groupStudyId, supportsHeartbeat);
        return ResponseEntity.ok(response);
    }
}
