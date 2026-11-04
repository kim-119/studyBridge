package com.studybridge.api.controller;

import com.studybridge.api.ai.training.TrainingConsentService;
import com.studybridge.api.security.domain.CustomUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 모델 학습 데이터 활용 동의(선택, 기본 OFF). 신원은 인증 principal 만 — 본문의 userId 등은 받지 않는다.
 *  - GET    /api/ai/training-consent        : 현재 상태 + 현재 고지문
 *  - POST   /api/ai/training-consent        : 동의 { consentVersion, ageConfirmed14Plus:true, source? }
 *  - DELETE /api/ai/training-consent        : 철회(미전송 후보 즉시 파기 + ai07 철회 요청)
 */
@RestController
@RequestMapping("/api/ai/training-consent")
@RequiredArgsConstructor
public class AiTrainingConsentController {

    private final TrainingConsentService consentService;

    @GetMapping
    public ResponseEntity<Map<String, Object>> status(@AuthenticationPrincipal CustomUserDetails user) {
        return ResponseEntity.ok(body(consentService.status(user.getId())));
    }

    @PostMapping
    public ResponseEntity<Map<String, Object>> grant(@AuthenticationPrincipal CustomUserDetails user,
                                                     @RequestBody(required = false) Map<String, Object> req) {
        Map<String, Object> r = req != null ? req : Map.of();
        try {
            return ResponseEntity.ok(body(consentService.grant(user.getId(), str(r.get("consentVersion")),
                    Boolean.TRUE.equals(r.get("ageConfirmed14Plus")), str(r.get("source")))));
        } catch (TrainingConsentService.ConsentRejected e) {
            return ResponseEntity.status(e.status()).body(Map.of("errorCode", e.errorCode(), "message", e.getMessage()));
        }
    }

    @DeleteMapping
    public ResponseEntity<Map<String, Object>> withdraw(@AuthenticationPrincipal CustomUserDetails user) {
        return ResponseEntity.ok(body(consentService.withdraw(user.getId(), "WEB")));
    }

    private Map<String, Object> body(TrainingConsentService.Status s) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("purpose", TrainingConsentService.PURPOSE);
        m.put("granted", s.granted());
        m.put("consentVersion", s.consentVersion());
        m.put("currentVersion", s.currentVersion());
        m.put("updatedAt", s.updatedAt());
        m.put("needsReconsent", s.needsReconsent());
        m.put("notice", consentService.notice(s.currentVersion()));
        return m;
    }

    private static String str(Object o) {
        return o == null ? null : o.toString();
    }
}
