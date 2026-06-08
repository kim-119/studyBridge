package com.studybridge.api.service;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import com.studybridge.api.entity.RefreshToken;
import com.studybridge.api.repository.RefreshTokenRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import org.springframework.security.crypto.password.PasswordEncoder;
import java.time.LocalDateTime;

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;
    private final RefreshTokenRepository refreshTokenRepository;
    private final S3Service s3Service;

    // 회원 가입
    @Transactional
    public UserDTO.Response register(UserDTO.RegisterRequest request) {
        if (userRepository.existsByEmail(request.getEmail())) {
            throw new IllegalArgumentException("이미 사용 중인 이메일입니다.");
        }
        if (!request.getPassword().equals(request.getPasswordConfirm())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        User user = User.builder()
                .email(request.getEmail())
                .password(passwordEncoder.encode(request.getPassword()))
                .displayName(request.getDisplayName())
                .major(request.getMajor())
                .build();

        User savedUser = userRepository.save(user);

        return convertToResponse(savedUser);
    }

    // 로그인
    @Transactional
    public UserDTO.Response login(UserDTO.LoginRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다."));

        if (!passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다.");
        }

        // 계정 정지 여부 검증
        if ("BANNED".equals(user.getStatus())) {
            throw new IllegalArgumentException("영구 정지된 계정입니다. 사유: " + user.getSuspensionReason() + " (메모: " + user.getSuspensionMemo() + ")");
        } else if ("SUSPENDED".equals(user.getStatus())) {
            if (user.getSuspensionEndDate() != null && user.getSuspensionEndDate().isAfter(LocalDateTime.now())) {
                throw new IllegalArgumentException("일시 정지된 계정입니다. 정지 만료일: " + user.getSuspensionEndDate() + ", 사유: " + user.getSuspensionReason() + " (메모: " + user.getSuspensionMemo() + ")");
            } else {
                // 정지 기한이 만료된 경우 정상으로 복구
                user.setStatus("ACTIVE");
                user.setSuspensionEndDate(null);
                user.setSuspensionReason(null);
                user.setSuspensionMemo(null);
                userRepository.save(user);
            }
        }

        // Access Token & Refresh Token 생성
        String accessToken = jwtTokenProvider.createToken(user.getId(), user.getEmail());
        String refreshToken = jwtTokenProvider.createRefreshToken(user.getId(), user.getEmail());

        // Refresh Token DB 저장 또는 업데이트
        RefreshToken tokenEntity = refreshTokenRepository.findByEmail(user.getEmail())
                .orElse(new RefreshToken());

        tokenEntity.setEmail(user.getEmail());
        tokenEntity.setToken(refreshToken);
        tokenEntity.setExpiryDate(LocalDateTime.now().plusWeeks(1)); // 7일 유효
        refreshTokenRepository.save(tokenEntity);

        UserDTO.Response response = convertToResponse(user);
        response.setAccessToken(accessToken);
        response.setRefreshToken(refreshToken);
        return response;
    }

    // 토큰 리프레시
    @Transactional
    public UserDTO.Response refreshToken(String refreshToken) {
        if (!jwtTokenProvider.validateToken(refreshToken)) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 리프레시 토큰입니다.");
        }

        RefreshToken tokenEntity = refreshTokenRepository.findByToken(refreshToken)
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 리프레시 토큰입니다."));

        if (tokenEntity.getExpiryDate().isBefore(LocalDateTime.now())) {
            refreshTokenRepository.delete(tokenEntity);
            throw new IllegalArgumentException("만료된 리프레시 토큰입니다. 다시 로그인해 주세요.");
        }

        User user = userRepository.findByEmail(tokenEntity.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 회원입니다."));

        String newAccessToken = jwtTokenProvider.createToken(user.getId(), user.getEmail());
        String newRefreshToken = jwtTokenProvider.createRefreshToken(user.getId(), user.getEmail());

        tokenEntity.setToken(newRefreshToken);
        tokenEntity.setExpiryDate(LocalDateTime.now().plusWeeks(1));
        refreshTokenRepository.save(tokenEntity);

        UserDTO.Response response = convertToResponse(user);
        response.setAccessToken(newAccessToken);
        response.setRefreshToken(newRefreshToken);
        return response;
    }

    // 로그아웃 (DB에서 리프레시 토큰 삭제)
    @Transactional
    public void logout(String email) {
        refreshTokenRepository.deleteByEmail(email);
    }

    // 비밀번호 변경
    @Transactional
    public void changePassword(UserDTO.ChangePasswordRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        if (!passwordEncoder.matches(request.getCurrentPassword(), user.getPassword())) {
            throw new IllegalArgumentException("기존 비밀번호가 일치하지 않습니다.");
        }

        if (!request.getNewPassword().equals(request.getNewPasswordConfirm())) {
            throw new IllegalArgumentException("새 비밀번호 확인이 일치하지 않습니다.");
        }

        user.setPassword(passwordEncoder.encode(request.getNewPassword()));
    }

    // 프로필 수정
    @Transactional
    public UserDTO.Response updateProfile(Long userId, UserDTO.UpdateProfileRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        user.setDisplayName(request.getDisplayName());
        user.setMajor(request.getMajor());
        user.setPhotoUrl(request.getPhotoUrl());

        return convertToResponse(user);
    }

    // 프로필 조회
    public UserDTO.Response getProfile(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        return convertToResponse(user);
    }

    private UserDTO.Response convertToResponse(User user) {
        String presignedPhotoUrl = user.getPhotoUrl();
        if (presignedPhotoUrl != null && !presignedPhotoUrl.isBlank() && !presignedPhotoUrl.startsWith("http")) {
            try {
                presignedPhotoUrl = s3Service.getPresignedUrl(presignedPhotoUrl);
            } catch (Exception e) {
                log.warn("Failed to generate presigned URL for user profile photo user_id={}: {}", user.getId(), e.getMessage());
            }
        }
        UserDTO.Response response = UserDTO.Response.builder()
                .id(user.getId())
                .email(user.getEmail())
                .displayName(user.getDisplayName())
                .major(user.getMajor())
                .photoUrl(presignedPhotoUrl)
                .status(user.getStatus())
                .isSubscribed(user.getIsSubscribed())
                .suspensionEndDate(user.getSuspensionEndDate())
                .suspensionReason(user.getSuspensionReason())
                .suspensionMemo(user.getSuspensionMemo())
                .build();
        return response;
    }
}