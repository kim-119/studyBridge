package com.studybridge.api.controller;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.service.UserService;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.security.exhibit.ExhibitSessionException;
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import com.studybridge.api.service.S3Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/users")
@RequiredArgsConstructor
public class UserController {

    private final UserService userService;
    private final S3Service s3Service;

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
        } catch (ExhibitSessionException e) {
            // 체험 계정 동시 접속 한도(409) — 이미 접속한 기기는 그대로 유지된다.
            return ResponseEntity.status(e.getStatus()).body(e.getMessage());
        }
    }

    // 리프레시 토큰
    //  refreshToken 은 JSON body({"refreshToken": ...}) 로 받는 것이 기본이다(URL 쿼리는 nginx access log 에 토큰이 남는다).
    //  구버전 프론트 호환으로 ?refreshToken= 쿼리도 계속 받는다.
    @PostMapping("/refresh")
    public ResponseEntity<?> refresh(
            @RequestParam(value = "refreshToken", required = false) String refreshTokenParam,
            @RequestBody(required = false) java.util.Map<String, Object> body) {
        try {
            String refreshToken = refreshTokenParam;
            if ((refreshToken == null || refreshToken.isBlank()) && body != null && body.get("refreshToken") != null) {
                refreshToken = String.valueOf(body.get("refreshToken"));
            }
            if (refreshToken == null || refreshToken.isBlank()) {
                return ResponseEntity.status(401).body("refreshToken 이 필요합니다.");
            }
            UserDTO.Response response = userService.refreshToken(refreshToken);
            return ResponseEntity.ok(response);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(401).body(e.getMessage());
        } catch (ExhibitSessionException e) {
            return ResponseEntity.status(e.getStatus()).body(e.getMessage());
        }
    }

    // 로그아웃
    @PostMapping("/logout")
    public ResponseEntity<?> logout(java.security.Principal principal, HttpServletRequest request) {
        if (principal == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            // 체험 계정 토큰이면 JwtAuthenticationFilter 가 넣어 둔 이 기기 세션 id — 그 슬롯만 반환한다.
            Object sessionId = request.getAttribute(ExhibitSessionService.SESSION_ID_ATTRIBUTE);
            userService.logout(principal.getName(), sessionId instanceof String sid ? sid : null);
            return ResponseEntity.ok("성공적으로 로그아웃되었습니다.");
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }

    // 세션 유지 확인(체험 계정 웹 클라이언트가 주기적으로 호출). 인증 필터가 이 기기 슬롯의 마지막 사용 시각을 갱신한다.
    @PostMapping("/session/keepalive")
    public ResponseEntity<?> keepalive(java.security.Principal principal) {
        if (principal == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        return ResponseEntity.noContent().build();
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

    // 사용자 프로필 이미지 업로드
    @PostMapping(value = "/profile/image", consumes = org.springframework.http.MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<?> uploadProfileImage(
            @AuthenticationPrincipal CustomUserDetails userDetails,
            @RequestParam("file") MultipartFile file) {
        if (userDetails == null) {
            return ResponseEntity.status(401).body("로그인이 필요한 서비스입니다.");
        }
        try {
            String s3Key = s3Service.uploadBlogFile(file, userDetails.getId());
            String presignedUrl = s3Service.getPresignedUrl(s3Key);
            java.util.Map<String, String> response = new java.util.HashMap<>();
            response.put("s3Key", s3Key);
            response.put("photoUrl", presignedUrl);
            return ResponseEntity.ok(response);
        } catch (Exception e) {
            return ResponseEntity.badRequest().body(e.getMessage());
        }
    }
}