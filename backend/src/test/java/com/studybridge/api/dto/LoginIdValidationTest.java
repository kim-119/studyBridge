package com.studybridge.api.dto;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validation;
import jakarta.validation.Validator;
import jakarta.validation.ValidatorFactory;
import java.util.Set;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

/** 로그인 ID 검증: 이메일은 기존 @Email 판정 그대로, 추가로 체험 계정 별칭(test1 등)만 허용. 회원가입은 여전히 @Email 만. */
class LoginIdValidationTest {

    private static ValidatorFactory factory;
    private static Validator validator;

    @BeforeAll
    static void init() {
        factory = Validation.buildDefaultValidatorFactory();
        validator = factory.getValidator();
    }

    @AfterAll
    static void close() {
        factory.close();
    }

    private static Set<ConstraintViolation<UserDTO.LoginRequest>> validate(String id) {
        UserDTO.LoginRequest r = new UserDTO.LoginRequest();
        r.setEmail(id);
        r.setPassword("1234");
        return validator.validate(r);
    }

    @Test
    void emailsAndExhibitAliasesPass() {
        for (String ok : new String[] {"user@example.com", "test1@test.com", "test1@studybridge.co.kr", "test1", "TEST4", " test2 "}) {
            assertTrue(validate(ok).isEmpty(), ok);
        }
    }

    @Test
    void otherNonEmailsStillRejectedWithSameMessage() {
        for (String bad : new String[] {"abc", "test", "test123", "admin", "a@", "@b.com"}) {
            Set<ConstraintViolation<UserDTO.LoginRequest>> v = validate(bad);
            assertEquals(1, v.size(), bad);
            assertEquals("올바른 이메일 형식이 아닙니다.", v.iterator().next().getMessage(), bad);
        }
        assertEquals(1, validate("").size(), "빈 값은 @NotBlank");
    }

    @Test
    void registerStillRequiresEmail() {
        UserDTO.RegisterRequest r = new UserDTO.RegisterRequest();
        r.setEmail("test1");
        r.setPassword("password1!");
        r.setPasswordConfirm("password1!");
        r.setDisplayName("체험");
        assertTrue(validator.validate(r).stream().anyMatch(v -> v.getPropertyPath().toString().equals("email")),
                "회원가입은 별칭 형식 ID 를 받지 않는다");
        r.setPassword("1234");
        r.setEmail("x@example.com");
        assertTrue(validator.validate(r).stream().anyMatch(v -> v.getPropertyPath().toString().equals("password")),
                "회원가입 비밀번호 정책(8~16자)은 그대로");
    }
}
