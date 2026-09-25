package com.studybridge.api.controller;

import com.studybridge.api.dto.PasswordResetDTO;
import com.studybridge.api.service.PasswordResetService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 비밀번호 찾기(이메일 인증번호). 비로그인 공개 엔드포인트(SecurityConfig permitAll: /api/users/password-reset/**).
 * 오류는 PasswordResetException → GlobalExceptionHandler 가 {status, message, reason, retryAfterSeconds} 로 변환한다.
 */
@RestController
@RequestMapping("/api/users/password-reset")
@RequiredArgsConstructor
public class PasswordResetController {

    private final PasswordResetService passwordResetService;

    /** 1) 인증번호 발송 — 가입 여부와 무관하게 동일한 200 응답(계정 열거 방지). */
    @PostMapping("/send-code")
    public ResponseEntity<PasswordResetDTO.Response> sendCode(@Valid @RequestBody PasswordResetDTO.SendCodeRequest request,
                                                              HttpServletRequest http) {
        return ResponseEntity.ok(passwordResetService.sendCode(request.getEmail(), clientIp(http)));
    }

    /** 2) 인증번호 검증 — 성공 시 verified 상태(10분) 부여, 코드는 즉시 폐기. */
    @PostMapping("/verify-code")
    public ResponseEntity<PasswordResetDTO.Response> verifyCode(@Valid @RequestBody PasswordResetDTO.VerifyCodeRequest request) {
        return ResponseEntity.ok(passwordResetService.verifyCode(request.getEmail(), request.getCode()));
    }

    /** 3) 새 비밀번호 설정 — 서버측 verified 상태가 없으면 403. */
    @PostMapping("/reset")
    public ResponseEntity<PasswordResetDTO.Response> reset(@Valid @RequestBody PasswordResetDTO.ResetRequest request) {
        return ResponseEntity.ok(passwordResetService.reset(
                request.getEmail(), request.getNewPassword(), request.getNewPasswordConfirm()));
    }

    /** nginx 가 X-Forwarded-For 를 붙여 준다(spring 포트는 127.0.0.1 바인딩이라 외부 직접 접근 불가). */
    private static String clientIp(HttpServletRequest request) {
        String forwarded = request.getHeader("X-Forwarded-For");
        if (forwarded != null && !forwarded.isBlank()) {
            String first = forwarded.split(",")[0].trim();
            if (!first.isEmpty()) return first;
        }
        String realIp = request.getHeader("X-Real-IP");
        if (realIp != null && !realIp.isBlank()) return realIp.trim();
        return request.getRemoteAddr();
    }
}
