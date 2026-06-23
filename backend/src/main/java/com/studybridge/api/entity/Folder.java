package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 자료보관함 폴더. Material(자료)과는 분리된 테이블로 관리하여 기존 자료 id 체계/AI 연동을 건드리지 않는다.
 * parentId 가 null 이면 루트(홈) 폴더. ddl-auto=update 로 folders 테이블이 자동 생성된다.
 */
@Entity
@Table(name = "folders")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Folder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long folderId;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false, length = 200)
    private String name;

    /** 상위 폴더 id. null 이면 루트(홈) 위치의 폴더. 자기참조이지만 단순 Long 으로 보관(자료 id 체계와 무관). */
    @Column(name = "parent_id")
    private Long parentId;

    /**
     * 문서 도메인(자료보관함 탭 분리 기준). LEARNING_MATERIAL / PLANNER / STUDY_JOURNAL.
     * 폴더는 반드시 한 도메인에만 속한다(학습자료 폴더가 플래너 탭에 노출되는 버그 방지).
     * enum 대신 String 으로 보관 — RDS check 제약 자동 생성/수동 ALTER 부담을 피한다.
     * 레거시(null) 폴더는 조회 시 LEARNING_MATERIAL 로 폴백 처리(파괴적 마이그레이션 없이 호환).
     */
    @Column(name = "domain", length = 40)
    private String domain;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
