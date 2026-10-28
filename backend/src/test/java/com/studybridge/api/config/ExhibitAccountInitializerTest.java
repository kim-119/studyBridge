package com.studybridge.api.config;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.studybridge.api.entity.User;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.security.exhibit.ExhibitAccountProperties;
import com.studybridge.api.service.UserService;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;

/** 체험 계정 생성: 없는 것만 회원가입 생성 경로로 만들고, 있는 계정(정지된 것 포함)은 손대지 않는다. 재실행해도 중복 없음. */
class ExhibitAccountInitializerTest {

    private UserRepository userRepository;
    private UserService userService;
    private ExhibitAccountProperties props;
    private ExhibitAccountInitializer initializer;

    @BeforeEach
    void setUp() {
        userRepository = mock(UserRepository.class);
        userService = mock(UserService.class);
        props = new ExhibitAccountProperties();
        initializer = new ExhibitAccountInitializer(props, userRepository, userService);
        when(userRepository.findByEmail(anyString())).thenReturn(Optional.empty());
        when(userService.createUser(anyString(), anyString(), anyString(), isNull()))
                .thenAnswer(inv -> User.builder().id(1L).email(inv.getArgument(0)).role("USER").build());
    }

    @Test
    void createsMissingAccounts_withInitialPassword() {
        initializer.run();

        for (int i = 1; i <= 4; i++) {
            verify(userService).createUser(eq("test" + i + "@studybridge.co.kr"), eq("1234"), eq("test" + i), isNull());
        }
    }

    @Test
    void existingAccountsAreLeftUnchanged_soRerunIsIdempotent() {
        User banned = User.builder().id(201L).email("test2@studybridge.co.kr").status("BANNED").role("USER").build();
        when(userRepository.findByEmail("test2@studybridge.co.kr")).thenReturn(Optional.of(banned));

        initializer.run();

        verify(userService, never()).createUser(eq("test2@studybridge.co.kr"), anyString(), anyString(), isNull());
        verify(userService, times(3)).createUser(anyString(), anyString(), anyString(), isNull());
        verify(userRepository, never()).save(banned);
    }

    @Test
    void concurrentCreateOnAnotherInstance_isTreatedAsExisting() {
        when(userService.createUser(eq("test3@studybridge.co.kr"), anyString(), anyString(), isNull()))
                .thenThrow(new DataIntegrityViolationException("duplicate key"));

        initializer.run(); // 예외 없이 나머지 계정 계속

        verify(userService).createUser(eq("test4@studybridge.co.kr"), anyString(), anyString(), isNull());
    }

    @Test
    void provisionOff_doesNothing() {
        props.setProvisionOnStartup(false);
        initializer.run();
        verifyNoInteractions(userService);
    }
}
