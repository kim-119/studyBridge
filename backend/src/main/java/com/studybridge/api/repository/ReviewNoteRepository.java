package com.studybridge.api.repository;

import com.studybridge.api.entity.ReviewNote;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.Optional;

public interface ReviewNoteRepository extends JpaRepository<ReviewNote, Long> {
    List<ReviewNote> findByUserIdOrderByCreatedAtDesc(Long userId);

    /** AI 학습 내비게이터: 로드맵 출처 자료로 푼 최근 퀴즈의 오답노트(사용자 격리). */
    List<ReviewNote> findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(Long userId, Long sourceMaterialId);
    Optional<ReviewNote> findByReviewNoteIdAndUserId(Long reviewNoteId, Long userId);
}
