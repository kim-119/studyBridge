package com.studybridge.api.controller;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.service.UserService;
import com.studybridge.api.security.domain.CustomUserDetails;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;

    // 회원가입
    @PostMapping("/register")
    public ResponseEntity<?> register(@Valid @RequestBody UserDTO.RegisterRequest request) {
        try {
            UserDTO.Response response = userService.register(request);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 로그인
    @PostMapping("/login")
    public ResponseEntity<?> login(@Valid @RequestBody UserDTO.LoginRequest request) {
        try {
            UserDTO.Response response = userService.login(request);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(401).body(e.getMessage());
        }
    }

    // 리프레시 토큰
    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(@RequestParam String refreshToken) {
        try {
            UserDTO.Response response = userService.refreshToken(refreshToken);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(401).body(e.getMessage());
        }
    }

    // 로그아웃
    @PostMapping("/logout")
    public ResponseEntity<?> logout(java.security.Principal principal) {
        if (principal == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            userService.logout(principal.getName());
            return ResponseEntity.ok("성공적으로 로그아웃되었습니다.");
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 비밀번호 변경
    @PutMapping("/password")
    public ResponseEntity<?> changePassword(@Valid @RequestBody UserDTO.ChangePasswordRequest request) {
        try {
            userService.changePassword(request);
            return ResponseEntity.ok("비밀번호가 성공적으로 변경되었습니다.");
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 사용자 프로필 조회
    @GetMapping("/profile")
    public ResponseEntity<?> getProfile(@AuthenticationPrincipal CustomUserDetails userDetails) {
        if (userDetails == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            UserDTO.Response response = userService.getProfile(userDetails.getId());
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 사용자 프로필 수정
    @PutMapping("/profile")
    public ResponseEntity<?> updateProfile(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @Valid @RequestBody UserDTO.UpdateProfileRequest request) {
        if (userDetails == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            UserDTO.Response response = userService.updateProfile(userDetails.getId(), request);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }
}