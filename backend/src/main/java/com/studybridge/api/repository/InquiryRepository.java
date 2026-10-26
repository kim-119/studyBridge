package com.studybridge.api.repository;

import com.studybridge.api.entity.Inquiry;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.List;

public interface InquiryRepository extends JpaRepository<Inquiry, Long> {
    List<Inquiry> findAllByAuthorIdOrderByCreatedAtDesc(Long authorId);
    List<Inquiry> findAllByOrderByCreatedAtDesc();
}
