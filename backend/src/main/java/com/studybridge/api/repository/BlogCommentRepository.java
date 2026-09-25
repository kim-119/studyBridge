package com.studybridge.api.repository;

import com.studybridge.api.entity.BlogComment;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface BlogCommentRepository extends JpaRepository<BlogComment, Long> {
    List<BlogComment> findByBlog_BlogIdOrderByCreatedAtAsc(Long blogId);
}
