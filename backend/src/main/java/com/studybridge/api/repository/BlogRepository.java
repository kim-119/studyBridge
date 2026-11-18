package com.studybridge.api.repository;

import com.studybridge.api.entity.Blog;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface BlogRepository extends JpaRepository<Blog, Long> {
    List<Blog> findAllByOrderByCreatedAtDesc();
    List<Blog> findAllByOrderByCreatedAtAsc();
    List<Blog> findByTitleContainingIgnoreCaseOrContentContainingIgnoreCaseOrAuthor_DisplayNameContainingIgnoreCaseOrderByCreatedAtDesc(
            String title, String content, String authorDisplayName);
    List<Blog> findByTitleContainingIgnoreCaseOrContentContainingIgnoreCaseOrAuthor_DisplayNameContainingIgnoreCaseOrderByCreatedAtAsc(
            String title, String content, String authorDisplayName);

    // 인기순: 좋아요 수 → 댓글 수 → 최신. (viewCount/popularityScore 컬럼은 없으므로 기존 like/comment 관계만 사용)
    @Query("SELECT b FROM Blog b LEFT JOIN b.likes l LEFT JOIN b.comments c " +
           "GROUP BY b ORDER BY COUNT(DISTINCT l) DESC, COUNT(DISTINCT c) DESC, b.createdAt DESC")
    List<Blog> findAllOrderByPopularity();

    @Query("SELECT b FROM Blog b LEFT JOIN b.likes l LEFT JOIN b.comments c " +
           "WHERE LOWER(b.title) LIKE LOWER(CONCAT('%', :keyword, '%')) " +
           "   OR LOWER(b.content) LIKE LOWER(CONCAT('%', :keyword, '%')) " +
           "   OR LOWER(b.author.displayName) LIKE LOWER(CONCAT('%', :keyword, '%')) " +
           "GROUP BY b ORDER BY COUNT(DISTINCT l) DESC, COUNT(DISTINCT c) DESC, b.createdAt DESC")
    List<Blog> searchOrderByPopularity(@Param("keyword") String keyword);
}
