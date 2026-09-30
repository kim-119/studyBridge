package com.studybridge.api.repository;

import com.studybridge.api.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);

    boolean existsByEmail(String email);

    boolean existsByDisplayName(String displayName);

    /** 사용자 단위 직렬화 잠금(공부 세션 START 경합 방지: 두 START 가 동시에 "활성 없음"을 보고 이중 세션을 만들지 못하게). */
    @org.springframework.data.jpa.repository.Lock(jakarta.persistence.LockModeType.PESSIMISTIC_WRITE)
    @org.springframework.data.jpa.repository.Query("SELECT u FROM User u WHERE u.id = :id")
    java.util.Optional<User> findByIdForUpdate(@org.springframework.data.repository.query.Param("id") Long id);
}
