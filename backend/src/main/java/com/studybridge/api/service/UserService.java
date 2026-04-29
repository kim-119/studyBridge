package com.studybridge.api.service;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class UserService {

    private final UserRepository userRepository;
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
                .password(request.getPassword()) // 생글자로 저장
                .displayName(request.getDisplayName())
                .major(request.getMajor())
                .build();

        User savedUser = userRepository.save(user);

        return UserDTO.Response.builder()
                .id(savedUser.getId())
                .email(savedUser.getEmail())
                .displayName(savedUser.getDisplayName())
                .major(savedUser.getMajor())
                .photoUrl(savedUser.getPhotoUrl())
                .status(savedUser.getStatus())
                .build();
    }
    // 로그인 검사    
    public UserDTO.Response login(UserDTO.LoginRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다."));

        if (!user.getPassword().equals(request.getPassword())) {
            throw new IllegalArgumentException("가입되지 않은 이메일이거나 비밀번호가 틀렸습니다.");
        }

        return UserDTO.Response.builder()
                .id(user.getId())
                .email(user.getEmail())
                .displayName(user.getDisplayName())
                .major(user.getMajor())
                .photoUrl(user.getPhotoUrl())
                .status(user.getStatus())
                .build();
    }

    @Transactional
    public void changePassword(UserDTO.ChangePasswordRequest request) {
        User user = userRepository.findByEmail(request.getEmail())
                .orElseThrow(() -> new IllegalArgumentException("사용자를 찾을 수 없습니다."));

        if (!user.getPassword().equals(request.getCurrentPassword())) {
            throw new IllegalArgumentException("기존 비밀번호가 일치하지 않습니다.");
        }

        if (!request.getNewPassword().equals(request.getNewPasswordConfirm())) {
            throw new IllegalArgumentException("새 비밀번호 확인이 일치하지 않습니다.");
        }

        user.setPassword(request.getNewPassword());
    }
}
