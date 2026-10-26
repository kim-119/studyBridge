package com.studybridge.api.dto;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/**
 * 비밀번호 찾기(이메일 인증번호) 요청/응답 DTO.
 * 엔드포인트: /api/users/password-reset/{send-code | verify-code | reset}
 */
public class PasswordResetDTO {

    @Getter
    @Setter
    public static class SendCodeRequest {
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        @Size(max = 100, message = "이메일은 100자 이하여야 합니다.")
        private String email;
    }

    @Getter
    @Setter
    public static class VerifyCodeRequest {
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        @Size(max = 100, message = "이메일은 100자 이하여야 합니다.")
        private String email;

        @NotBlank(message = "인증번호를 입력해주세요.")
        @Pattern(regexp = "^\\d{6}$", message = "인증번호는 6자리 숫자입니다.")
        private String code;
    }

    @Getter
    @Setter
    public static class ResetRequest {
        @NotBlank(message = "이메일을 입력해주세요.")
        @Email(message = "올바른 이메일 형식이 아닙니다.")
        @Size(max = 100, message = "이메일은 100자 이하여야 합니다.")
        private String email;

        @NotBlank(message = "새 비밀번호를 입력해주세요.")
        @Size(min = 8, max = 16, message = "비밀번호는 8~16자여야 합니다.")
        private String newPassword;

        /** 선택. 보내면 newPassword 와 일치해야 한다(프론트 확인 입력 서버측 재검증). */
        private String newPasswordConfirm;
    }

    /** 공통 성공 응답. 계정 존재 여부를 드러내지 않는 문구만 담는다. */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private String message;
        /** 인증번호 유효시간(초) — send-code 응답 */
        private Long expiresInSeconds;
        /** 재전송 가능까지 남은 시간(초) — send-code 응답 */
        private Long resendAfterSeconds;
        /** 인증 성공 후 새 비밀번호 설정 가능 시간(초) — verify-code 응답 */
        private Long resetWindowSeconds;
    }
}
