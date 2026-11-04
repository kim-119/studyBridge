package com.studybridge.api.controller;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.studybridge.api.dto.InquiryDTO;
import com.studybridge.api.entity.Inquiry;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.InquiryRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.domain.CustomUserDetails;
import java.time.LocalDateTime;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * 2026-11-04 문의하기 장애 재현: Android 앱 모바일 마이페이지가 {title, content} 만 보내(type 없음)
 * inquiries.type NOT NULL 위반 → 500(10회 연속 클릭 모두 실패). 서버가 type 을 정규화하고, 빈 입력은 400, 연속 클릭은 1건만 저장.
 */
class InquiryControllerTest {

        InquiryRepository inquiries;
        UserRepository users;
        InquiryController controller;
        CustomUserDetails principal;
        User user;

        @BeforeEach
        void setUp() {
                inquiries = mock(InquiryRepository.class);
                users = mock(UserRepository.class);
                controller = new InquiryController(inquiries, users);
                user = new User();
                user.setId(42L);
                user.setDisplayName("학습자");
                when(users.findById(42L)).thenReturn(Optional.of(user));
                principal = mock(CustomUserDetails.class);
                when(principal.getId()).thenReturn(42L);
                when(inquiries.findFirstByAuthorIdOrderByCreatedAtDescIdDesc(42L)).thenReturn(Optional.empty());
                when(inquiries.save(any(Inquiry.class))).thenAnswer(inv -> {
                        Inquiry i = inv.getArgument(0);
                        i.setId(100L);
                        i.setCreatedAt(LocalDateTime.now());
                        return i;
                });
        }

        Inquiry saved() {
                ArgumentCaptor<Inquiry> c = ArgumentCaptor.forClass(Inquiry.class);
                verify(inquiries).save(c.capture());
                return c.getValue();
        }

        @Test
        void androidPayloadWithoutTypeIsStoredWithDefaultType() {
                InquiryDTO.Response res = controller.createInquiry(principal, new InquiryDTO.Request(null, "앱 문의", "알림이 안 와요")).getBody();
                assertEquals("이용문의", saved().getType(), "type 없는 요청(Android) → 기본 유형, NOT NULL 위반 없음");
                assertEquals("이용문의", res.getType());
                assertEquals("대기중", res.getStatus());
                assertEquals(42L, saved().getAuthor().getId(), "작성자 = 인증 사용자");
        }

        @Test
        void webPayloadTypesArePreservedAndUnknownBecomesEtc() {
                controller.createInquiry(principal, new InquiryDTO.Request("버그 및 오류신고", "제목", "내용"));
                assertEquals("버그 및 오류신고", saved().getType());
                InquiryController c2 = new InquiryController(inquiries, users);
                org.mockito.Mockito.clearInvocations(inquiries);
                c2.createInquiry(principal, new InquiryDTO.Request("<script>", "제목2", "내용2"));
                assertEquals("기타", saved().getType());
                assertEquals("이용문의", InquiryController.normalizeType("   "));
                assertEquals("이용 문의", InquiryController.normalizeType(" 이용 문의 "));
        }

        @Test
        void blankTitleOrContentIs400NotDbError() {
                assertThrows(IllegalArgumentException.class, () -> controller.createInquiry(principal, new InquiryDTO.Request("이용문의", "  ", "내용")));
                assertThrows(IllegalArgumentException.class, () -> controller.createInquiry(principal, new InquiryDTO.Request("이용문의", "제목", null)));
                assertThrows(IllegalArgumentException.class, () -> controller.createInquiry(principal, null));
                assertThrows(IllegalArgumentException.class,
                                () -> controller.createInquiry(principal, new InquiryDTO.Request("이용문의", "가".repeat(201), "내용")));
                verify(inquiries, never()).save(any());
        }

        @Test
        void rapidRepeatSubmitReturnsExistingInsteadOfDuplicate() {
                Inquiry prev = Inquiry.builder().id(7L).type("이용문의").title("ㅈㄱㄴ").content("내용").author(user).status("대기중")
                                .createdAt(LocalDateTime.now().minusSeconds(2)).build();
                when(inquiries.findFirstByAuthorIdOrderByCreatedAtDescIdDesc(42L)).thenReturn(Optional.of(prev));
                InquiryDTO.Response res = controller.createInquiry(principal, new InquiryDTO.Request(null, "ㅈㄱㄴ", "내용")).getBody();
                assertEquals(7L, res.getId(), "10초 안 같은 문의 재전송 → 앞선 접수 반환");
                verify(inquiries, never()).save(any());
                Inquiry old = Inquiry.builder().id(8L).type("이용문의").title("ㅈㄱㄴ").content("내용").author(user).status("대기중")
                                .createdAt(LocalDateTime.now().minusSeconds(30)).build();
                when(inquiries.findFirstByAuthorIdOrderByCreatedAtDescIdDesc(42L)).thenReturn(Optional.of(old));
                controller.createInquiry(principal, new InquiryDTO.Request(null, "ㅈㄱㄴ", "내용"));
                verify(inquiries, times(1)).save(any());
        }
}
