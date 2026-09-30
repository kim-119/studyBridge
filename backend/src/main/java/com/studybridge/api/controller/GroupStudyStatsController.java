package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudyStatsDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyStatsService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;

/**
 * 그룹 출석부 / 개인 공부 통계 (웹·Android 공통).
 *  GET /api/groups/{groupId}/attendance?range=DAY|WEEK|MONTH&date=YYYY-MM-DD[&month=YYYY-MM]
 *  GET /api/groups/{groupId}/study-stats/me?range=DAY|WEEK|MONTH&date=YYYY-MM-DD[&month=YYYY-MM]
 * 권한: JWT + 그룹 멤버(비멤버 403, 없는 그룹 404, 잘못된 range/month 400). 타인 userId 조회 파라미터는 제공하지 않는다.
 */
@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups/{groupId}")
public class GroupStudyStatsController {

    private final GroupStudyStatsService statsService;

    @GetMapping("/attendance")
    public ResponseEntity<GroupStudyStatsDTO.AttendanceBoard> attendance(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestParam(value = "range", required = false) String range,
            @RequestParam(value = "date", required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(value = "month", required = false) String month) {
        GroupStudyStatsService.Period period = statsService.resolvePeriod(range, date, month);
        log.info("Attendance board. userId={}, groupId={}, range={}, {}~{}", userDetails.getId(), groupId, period.range(), period.start(), period.end());
        return ResponseEntity.ok(statsService.getAttendanceBoard(userDetails.getId(), groupId, period));
    }

    @GetMapping("/study-stats/me")
    public ResponseEntity<GroupStudyStatsDTO.MyStudyStats> myStats(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestParam(value = "range", required = false) String range,
            @RequestParam(value = "date", required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate date,
            @RequestParam(value = "month", required = false) String month) {
        GroupStudyStatsService.Period period = statsService.resolvePeriod(range, date, month);
        log.info("My study stats. userId={}, groupId={}, range={}, {}~{}", userDetails.getId(), groupId, period.range(), period.start(), period.end());
        return ResponseEntity.ok(statsService.getMyStats(userDetails.getId(), groupId, period));
    }
}
