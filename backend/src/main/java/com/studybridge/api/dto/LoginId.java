package com.studybridge.api.dto;

import jakarta.validation.Constraint;
import jakarta.validation.Payload;
import jakarta.validation.ReportAsSingleViolation;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.Pattern;
import org.hibernate.validator.constraints.CompositionType;
import org.hibernate.validator.constraints.ConstraintComposition;

import java.lang.annotation.Documented;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 로그인 ID: 이메일 형식(@Email 판정 그대로) 또는 전시 체험 계정 별칭(test1 등, 대소문자 무관) — 둘 중 하나면 통과(OR 합성).
 * 체험 계정 별칭(exhibit.accounts)은 이 패턴 안에서 정해야 한다. 회원가입·비밀번호 변경은 여전히 @Email 만 허용한다.
 */
@ConstraintComposition(CompositionType.OR)
@Email
@Pattern(regexp = "\\s*[tT][eE][sS][tT][0-9]{1,2}\\s*")
@ReportAsSingleViolation
@Target({ElementType.FIELD})
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = {})
@Documented
public @interface LoginId {
    String message() default "올바른 이메일 형식이 아닙니다.";

    Class<?>[] groups() default {};

    Class<? extends Payload>[] payload() default {};
}
