package com.studybridge.api.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;

public class UserDTO {

    @Getter
    @Setter
    public static class RegisterRequest {
        @NotBlank(message = "이메일은 필수 입력값입니다.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        private String email;

        @NotBlank(message = "비밀번호는 필수 입력값입니다.")
        @Size(min = 8, max = 16, message = "비밀번호는 8~16자여야 합니다.")
        private String password;

        @NotBlank(message = "비밀번호 확인은 필수 입력값입니다.")
        private String passwordConfirm;

        @NotBlank(message = "닉네임은 필수 입력값입니다.")
        @Size(min = 2, max = 10, message = "닉네임은 2~10자여야 합니다.")
        private String displayName;

        private String major;
    }

    // 로그인 요청 시 사용하는 DTO
    @Getter
    @Setter
    public static class LoginRequest {
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        private String email;

        @NotBlank(message = "비밀번호를 입력해주세요.")
        private String password;
    }

    // 비밀번호 변경 요청 시 사용하는 DTO
    @Getter
    @Setter
    public static class ChangePasswordRequest {
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        private String email;

        @NotBlank(message = "기존 비밀번호를 입력해주세요.")
        private String currentPassword; // 현재 비밀번호 인증용

        @NotBlank(message = "새 비밀번호를 입력해주세요.")
        @Size(min = 8, max = 16, message = "새 비밀번호는 8~16자여야 합니다.")
        private String newPassword;

        @NotBlank(message = "새 비밀번호 확인을 입력해주세요.")
        private String newPasswordConfirm;
    }

    // 클라이언트에게 사용자 정보를 반환할 때 사용하는 DTO
    @Getter
    @Setter
    @Builder
    public static class Response {
        private Long id;
        private String email;
        private String displayName;
        private String major;
        private String photoUrl;
        private String status;
    }
}
