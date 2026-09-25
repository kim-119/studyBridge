package com.studybridge.api.repository;

import com.studybridge.api.entity.BlogLike;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface BlogLikeRepository extends JpaRepository<BlogLike, Long> {
    Optional<BlogLike> findByBlog_BlogIdAndUser_Id(Long blogId, Long userId);
    long countByBlog_BlogId(Long blogId);
    boolean existsByBlog_BlogIdAndUser_Id(Long blogId, Long userId);
}
