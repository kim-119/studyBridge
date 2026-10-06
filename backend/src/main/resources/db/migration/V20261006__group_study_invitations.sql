-- 비공개 그룹스터디 초대 링크(group_study_invitations).
--  - additive 전용. 개발/운영 모두 spring.jpa.hibernate.ddl-auto=update 가 엔티티(GroupStudyInvitation)로 테이블/제약/인덱스를
--    자동 생성하지만, ddl-auto 를 validate/none 로 운영하는 환경을 위해 멱등 스크립트를 함께 둔다.
--  - DROP/TRUNCATE/데이터 삭제 없음.
CREATE TABLE IF NOT EXISTS group_study_invitations (
    group_study_invitation_id bigserial PRIMARY KEY,
    group_study_id            bigint       NOT NULL REFERENCES group_studies (group_study_id),
    token                     varchar(64)  NOT NULL,
    created_by                bigint       NOT NULL REFERENCES users (user_id),
    created_at                timestamp,
    expires_at                timestamp,
    active                    boolean      NOT NULL DEFAULT true,
    used_count                integer      NOT NULL DEFAULT 0,
    max_uses                  integer
);
-- token 조회(초대 링크 열기/수락)는 unique index 로 O(log n), 그룹별 활성 링크 조회는 group_study_id 인덱스.
CREATE UNIQUE INDEX IF NOT EXISTS uk_group_study_invitations_token ON group_study_invitations (token);
CREATE INDEX IF NOT EXISTS idx_group_study_invitations_group ON group_study_invitations (group_study_id);
