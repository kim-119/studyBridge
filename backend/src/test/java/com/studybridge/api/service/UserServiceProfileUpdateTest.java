package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import com.studybridge.api.dto.UserDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.RefreshTokenRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.jwt.JwtTokenProvider;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * PUT /api/users/profile 계약: photoUrl 이 비었거나 presigned/절대 URL(조회 응답 echo)이면 기존 S3 키를 보존하고,
 * 업로드 응답의 s3Key 만 새 값으로 저장한다. 이름/전공만 바꿔도 사진·이메일·역할은 그대로다.
 */
class UserServiceProfileUpdateTest {

    private static final String KEY = "blogs/user_85/30e86d53-ab2a-40ed-ac02-05a28348d906.png";
    private static final String PRESIGNED = "https://studybridge-materials-seoul.s3.ap-northeast-2.amazonaws.com/" + KEY
            + "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=20261007T110000Z&X-Amz-SignedHeaders=host&X-Amz-Credential=AKIA%2F20261007%2Fap-northeast-2%2Fs3%2Faws4_request&X-Amz-Expires=3600&X-Amz-Signature=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    private UserRepository userRepository;
    private S3Service s3Service;
    private UserService service;

    @BeforeEach
    void setUp() {
        userRepository = Mockito.mock(UserRepository.class);
        s3Service = Mockito.mock(S3Service.class);
        service = new UserService(userRepository, Mockito.mock(PasswordEncoder.class), Mockito.mock(JwtTokenProvider.class),
                Mockito.mock(RefreshTokenRepository.class), s3Service);
        Mockito.when(s3Service.getPresignedUrl(KEY)).thenReturn(PRESIGNED);
    }

    @Test
    void resolvePhotoUrl_rules() {
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, null), "null → 기존 키 유지");
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, ""), "빈 문자열 → 기존 키 유지");
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, "   "), "공백 → 기존 키 유지");
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, PRESIGNED), "presigned URL echo → 기존 키 유지");
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, "HTTP://example.com/a.png"), "절대 URL(대소문자) → 기존 키 유지");
        assertEquals(KEY, UserService.resolvePhotoUrlForUpdate(KEY, "x".repeat(256)), "컬럼 길이 초과 → 기존 키 유지");
        assertEquals("blogs/user_85/new.png", UserService.resolvePhotoUrlForUpdate(KEY, " blogs/user_85/new.png "), "새 s3Key → 교체(trim)");
        assertNull(UserService.resolvePhotoUrlForUpdate(null, ""), "사진 없는 계정 + 빈 값 → 그대로 없음");
        assertNull(UserService.resolvePhotoUrlForUpdate(null, PRESIGNED), "사진 없는 계정 + URL → 그대로 없음");
    }

    private User userWithPhoto() {
        return User.builder().id(85L).email("b@x").password("p").displayName("애드온B").major("전산학")
                .photoUrl(KEY).role("USER").status("ACTIVE").build();
    }

    @Test
    void nameOnly_keepsPhotoKey_major_email_role() {
        User user = userWithPhoto();
        Mockito.when(userRepository.findById(85L)).thenReturn(Optional.of(user));
        UserDTO.UpdateProfileRequest req = new UserDTO.UpdateProfileRequest();
        req.setDisplayName("새이름");
        req.setMajor("전산학");
        req.setPhotoUrl(PRESIGNED); // 구버전 프론트가 조회 응답을 그대로 echo 하는 경우

        UserDTO.Response res = service.updateProfile(85L, req);

        assertEquals("새이름", user.getDisplayName());
        assertEquals("전산학", user.getMajor());
        assertEquals(KEY, user.getPhotoUrl(), "presigned URL 은 저장되지 않고 기존 키가 유지된다");
        assertEquals("b@x", user.getEmail());
        assertEquals("USER", user.getRole());
        assertEquals(PRESIGNED, res.getPhotoUrl(), "응답은 기존 키의 presigned URL");
    }

    @Test
    void majorOnly_withoutPhotoField_keepsPhoto() {
        User user = userWithPhoto();
        Mockito.when(userRepository.findById(85L)).thenReturn(Optional.of(user));
        UserDTO.UpdateProfileRequest req = new UserDTO.UpdateProfileRequest();
        req.setDisplayName("애드온B");
        req.setMajor(" 컴퓨터공학 ");

        service.updateProfile(85L, req);

        assertEquals("컴퓨터공학", user.getMajor());
        assertEquals(KEY, user.getPhotoUrl());
    }

    @Test
    void newUploadKey_replacesPhoto() {
        User user = userWithPhoto();
        Mockito.when(userRepository.findById(85L)).thenReturn(Optional.of(user));
        UserDTO.UpdateProfileRequest req = new UserDTO.UpdateProfileRequest();
        req.setDisplayName("애드온B");
        req.setPhotoUrl("blogs/user_85/new.png");

        service.updateProfile(85L, req);

        assertEquals("blogs/user_85/new.png", user.getPhotoUrl());
        assertEquals("전산학", user.getMajor(), "major 미전송 → 유지");
    }
}
