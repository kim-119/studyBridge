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
import com.studybridge.api.security.exhibit.ExhibitSessionService;
import java.time.LocalDateTime;
import java.util.Date;

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
    private final ExhibitSessionService exhibitSessionService;

    // users.photo_url 컬럼 길이(ddl-auto 기본 varchar(255)).
    static final int PHOTO_KEY_MAX_LENGTH = 255;

    // 회원 가입
    @Transactional
    public UserDTO.Response register(UserDTO.RegisterRequest request) {
        if (userRepository.existsByEmail(request.getEmail())) {
            throw new IllegalArgumentException("이미 사용 중인 이메일입니다.");
        }
        if (!request.getPassword().equals(request.getPasswordConfirm())) {
            throw new IllegalArgumentException("비밀번호가 일치하지 않습니다.");
        }

        User savedUser = createUser(request.getEmail(), request.getPassword(), request.getDisplayName(), request.getMajor());

        return convertToResponse(savedUser);
    }

    // 사용자 행 생성(회원가입·체험 계정 생성 공용). 비밀번호는 PasswordEncoder 로 해시한다. 입력 정책 검증은 호출자 책임.
    @Transactional
    public User createUser(String email, String rawPassword, String displayName, String major) {
        User user = User.builder()
                .email(email)
                .password(passwordEncoder.encode(rawPassword))
                .displayName(displayName)
                .major(major)
                .build();
        return userRepository.save(user);
    }

    // 로그인
    @Transactional
    public UserDTO.Response login(UserDTO.LoginRequest request) {
        // 체험 계정은 별칭(test1)으로도 찾는다. 일반 사용자 입력은 그대로 조회한다.
        String loginEmail = exhibitSessionService.resolveLoginId(request.getEmail()).orElse(request.getEmail());
        User user = userRepository.findByEmail(loginEmail)
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

        if (exhibitSessionService.isExhibitEmail(user.getEmail())) {
            return openExhibitSession(user);
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

    // 체험 계정 로그인: 기기별 세션 슬롯(sid)을 열고 그 sid 를 담은 토큰을 발급한다. 한도면 ExhibitSessionException(409).
    //  refresh_tokens(email unique) 는 계정당 1행이라 두 기기가 서로의 리프레시 토큰을 덮어쓰므로, 체험 세션은 Redis 슬롯에만 둔다.
    private UserDTO.Response openExhibitSession(User user) {
        String sessionId = exhibitSessionService.newSessionId();
        long expiresAt = exhibitSessionService.sessionExpiresAt();
        String accessToken = jwtTokenProvider.createToken(user.getId(), user.getEmail(), sessionId);
        String refreshToken = jwtTokenProvider.createRefreshToken(user.getId(), user.getEmail(), sessionId, new Date(expiresAt));
        exhibitSessionService.admit(user.getId(), sessionId, expiresAt, refreshToken);

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

        JwtTokenProvider.TokenClaims claims = jwtTokenProvider.getTokenClaims(refreshToken);
        if (claims.sessionId() != null) {
            return refreshExhibitSession(refreshToken, claims);
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

    // 체험 계정 리프레시: 같은 슬롯에서 토큰만 회전한다(만료 시각은 로그인 때 정한 절대 만료 그대로).
    private UserDTO.Response refreshExhibitSession(String refreshToken, JwtTokenProvider.TokenClaims claims) {
        User user = userRepository.findByEmail(claims.email())
                .orElseThrow(() -> new IllegalArgumentException("존재하지 않는 회원입니다."));
        if (claims.userId() == null || !claims.userId().equals(user.getId())) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 리프레시 토큰입니다.");
        }
        // 전시 종료 후 정지(BANNED/SUSPENDED)된 체험 계정은 로그인뿐 아니라 리프레시로도 이어 쓸 수 없다.
        boolean suspended = "SUSPENDED".equals(user.getStatus())
                && user.getSuspensionEndDate() != null && user.getSuspensionEndDate().isAfter(LocalDateTime.now());
        if ("BANNED".equals(user.getStatus()) || suspended) {
            exhibitSessionService.release(user.getId(), claims.sessionId());
            throw new IllegalArgumentException("사용이 중지된 계정입니다.");
        }

        String newAccessToken = jwtTokenProvider.createToken(user.getId(), user.getEmail(), claims.sessionId());
        String newRefreshToken = jwtTokenProvider.createRefreshToken(user.getId(), user.getEmail(), claims.sessionId(), claims.expiresAt());
        exhibitSessionService.rotate(user.getId(), claims.sessionId(), refreshToken, newRefreshToken);

        UserDTO.Response response = convertToResponse(user);
        response.setAccessToken(newAccessToken);
        response.setRefreshToken(newRefreshToken);
        return response;
    }

    // 로그아웃 (DB에서 리프레시 토큰 삭제)
    //  체험 계정(sessionId 있음)은 이 기기 슬롯만 반환한다 — 같은 계정으로 접속한 다른 기기는 그대로 유지된다.
    @Transactional
    public void logout(String email, String sessionId) {
        if (sessionId != null) {
            userRepository.findByEmail(email).ifPresent(user -> exhibitSessionService.release(user.getId(), sessionId));
            return;
        }
        refreshTokenRepository.deleteByEmail(email);
    }

    // 비밀번호 변경
    @Transactional
    public void changePassword(UserDTO.ChangePasswordRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        // 체험 계정은 여러 방문객이 함께 쓰므로 비밀번호를 바꿀 수 없다(한 명이 바꾸면 나머지가 로그인하지 못한다).
        if (exhibitSessionService.isExhibitEmail(user.getEmail())) {
            throw new IllegalArgumentException("체험 계정은 비밀번호를 변경할 수 없습니다.");
        }

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

        user.setDisplayName(request.getDisplayName().trim());
        if (request.getMajor() != null) {
            user.setMajor(request.getMajor().trim());
        }
        user.setPhotoUrl(resolvePhotoUrlForUpdate(user.getPhotoUrl(), request.getPhotoUrl()));

        return convertToResponse(user);
    }

    /**
     * 프로필 수정 요청의 photoUrl 을 저장할 값(S3 key)으로 정규화한다.
     *  - null/빈 문자열: 사진 미변경 → 기존 키 유지(사진이 없는 계정은 그대로 없음).
     *  - http(s) 절대 URL: 조회 응답(presigned URL, 400자+)을 그대로 되돌려 보낸 경우 → 기존 키 유지.
     *    photo_url 컬럼은 varchar(255) 라 presigned URL 저장 시도는 DataIntegrityViolation → 500 이었다.
     *  - 그 외(업로드 응답의 s3Key): 길이 한도 안이면 새 키로 교체.
     * 클라이언트 userId 는 받지 않으며, 이메일/역할/상태는 이 경로에서 건드리지 않는다.
     */
    static String resolvePhotoUrlForUpdate(String currentPhotoKey, String requestedPhotoUrl) {
        if (requestedPhotoUrl == null) {
            return currentPhotoKey;
        }
        String trimmed = requestedPhotoUrl.trim();
        if (trimmed.isEmpty()) {
            return currentPhotoKey;
        }
        if (trimmed.regionMatches(true, 0, "http://", 0, 7) || trimmed.regionMatches(true, 0, "https://", 0, 8)) {
            return currentPhotoKey;
        }
        if (trimmed.length() > PHOTO_KEY_MAX_LENGTH) {
            return currentPhotoKey;
        }
        return trimmed;
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
                .role(user.getRole())
                .isSubscribed(user.getIsSubscribed())
                .suspensionEndDate(user.getSuspensionEndDate())
                .suspensionReason(user.getSuspensionReason())
                .suspensionMemo(user.getSuspensionMemo())
                .exhibitAccount(exhibitSessionService.isExhibitEmail(user.getEmail()))
                .build();
        return response;
    }
}