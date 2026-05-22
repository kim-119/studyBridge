package com.studybridge.api.service;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.AdminRole;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import com.studybridge.api.entity.RefreshToken;
import com.studybridge.api.repository.RefreshTokenRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import org.springframework.security.crypto.password.PasswordEncoder;
import java.time.LocalDateTime;
import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class UserService {

    private final UserRepository userRepository;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenProvider jwtTokenProvider;
    private final RefreshTokenRepository refreshTokenRepository;

    @Value("${root.email:}")
    private String rootEmail;

    // 회원 가입
    @Transactional
    public UserDTO.Response register(UserDTO.RegisterRequest request) {
        if (userRepository.existsByEmail(request.getEmail())) {
            throw new IllegalArgumentException("이미 사용 중인 이메일입니다.");
        }
        if (!request.getPassword().equals(request.getPasswordConfirm())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        AdminRole role = AdminRole.USER;
        if (StringUtils.hasText(rootEmail) && request.getEmail().equalsIgnoreCase(rootEmail)) {
            role = AdminRole.ADMIN;
        }

        User user = User.builder()
                .email(request.getEmail())
                .password(passwordEncoder.encode(request.getPassword()))
                .displayName(request.getDisplayName())
                .major(request.getMajor())
                .role(role)
                .build();

        User savedUser = userRepository.save(user);

        return convertToResponse(savedUser);
    }

    // 로그인
    @Transactional
    public UserDTO.Response login(UserDTO.LoginRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다."));

        if (user.isBanned()) {
            if (user.getBannedUntil() == null) {
                throw new IllegalStateException("영구적으로 정지된 계정입니다.");
            }
            if (user.getBannedUntil().isAfter(LocalDateTime.now())) {
                throw new IllegalStateException("일시적으로 정지된 계정입니다. 정지 만료: " + user.getBannedUntil());
            }
        }
        
        if (!passwordEncoder.matches(request.getPassword(), user.getPassword())) {
            throw new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다.");
        }

        String accessToken = jwtTokenProvider.createToken(user.getId(), user.getEmail());
        String refreshToken = jwtTokenProvider.createRefreshToken(user.getId(), user.getEmail());

        RefreshToken tokenEntity = refreshTokenRepository.findByEmail(user.getEmail())
                .orElse(new RefreshToken());

        tokenEntity.setEmail(user.getEmail());
        tokenEntity.setToken(refreshToken);
        tokenEntity.setExpiryDate(LocalDateTime.now().plusWeeks(1));
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

    // 로그아웃
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

        return convertToResponse(user);
    }

    // 프로필 조회
    public UserDTO.Response getProfile(Long userId) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        return convertToResponse(user);
    }
    
    // (관리자) 모든 사용자 조회
    public List<UserDTO.Response> getAllUsers() {
        return userRepository.findAll().stream()
                .map(this::convertToResponse)
                .collect(Collectors.toList());
    }

    // (관리자) 사용자 정지/해제
    @Transactional
    public UserDTO.Response banUser(Long userId, UserDTO.UserBanRequest request) {
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));
        
        user.setBanned(request.isBanned());
        user.setBannedUntil(request.isBanned() ? request.getBannedUntil() : null);
        user.setStatus(request.isBanned() ? "BANNED" : "ACTIVE");
        
        // 사용자를 정지시킬 때, 강제 로그아웃을 위해 리프레시 토큰을 삭제
        if (request.isBanned()) {
            refreshTokenRepository.deleteByEmail(user.getEmail());
        }
        
        return convertToResponse(user);
    }

    private UserDTO.Response convertToResponse(User user) {
        boolean actualBanned = user.isBanned() && 
                (user.getBannedUntil() == null || user.getBannedUntil().isAfter(LocalDateTime.now()));

        return UserDTO.Response.builder()
                .id(user.getId())
                .email(user.getEmail())
                .displayName(user.getDisplayName())
                .major(user.getMajor())
                .photoUrl(user.getPhotoUrl())
                .isSubscribed(user.getIsSubscribed())
                .role(user.getRole())
                .banned(actualBanned)
                .bannedUntil(user.getBannedUntil())
                .build();
    }
}
