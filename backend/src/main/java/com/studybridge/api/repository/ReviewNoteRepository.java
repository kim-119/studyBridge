package com.studybridge.api.repository;

import com.studybridge.api.entity.ReviewNote;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ReviewNoteRepository extends JpaRepository<ReviewNote, Long> {
    List<ReviewNote> findByUserIdOrderByCreatedAtDesc(Long userId);
    Optional<ReviewNote> findByReviewNoteIdAndUserId(Long reviewNoteId, Long userId);
}
