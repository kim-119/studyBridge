package com.studybridge.api.repository;

import com.studybridge.api.entity.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {
    Optional<User> findByEmail(String email);

    boolean existsByEmail(String email);

    long countByCreatedAtAfter(LocalDateTime date);
    
    List<User> findByEmailContainingIgnoreCaseOrDisplayNameContainingIgnoreCase(String email, String displayName);
}