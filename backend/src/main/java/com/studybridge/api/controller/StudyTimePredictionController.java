package com.studybridge.api.controller;

import com.studybridge.api.dto.StudyTimePredictionDTO;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.StudyTimePredictionService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@Slf4j
@RequestMapping("/api")
public class StudyTimePredictionController {

    private final StudyTimePredictionService studyTimePredictionService;

    /**
     * 다음 날의 학습 예측 시간을 조회합니다.
     */
    @GetMapping("/study-time/predict")
    public ResponseEntity<StudyTimePredictionDTO.Response> predictStudyTime(
            @AuthenticationPrincipal CustomUserDetails userDetails) {
        
        log.info("Received request for study time prediction. userId={}", userDetails.getId());
        StudyTimePredictionDTO.Response response = studyTimePredictionService.predictTomorrow(userDetails.getId());
        return ResponseEntity.ok(response);
    }
}
