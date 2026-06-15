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

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
