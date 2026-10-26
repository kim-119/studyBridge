package com.studybridge.api.controller;

import com.studybridge.api.dto.GroupStudyReportDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyReportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api/groups")
public class GroupStudyReportController {

    private final GroupStudyReportService groupStudyReportService;

    @PostMapping("/{groupId}/reports")
    public ResponseEntity<GroupStudyReportDTO.Response> report(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @PathVariable Long groupId,
            @RequestBody GroupStudyReportDTO.Request request) {
        
        log.info("Received report request. reporterId={}, groupId={}", userDetails.getId(), groupId);
        GroupStudyReportDTO.Response response = groupStudyReportService.fileReport(userDetails.getId(), groupId, request);
        return ResponseEntity.status(HttpStatus.CREATED).body(response);
    }
}
