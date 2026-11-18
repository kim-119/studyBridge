package com.studybridge.api.entity;

/**
 * 그룹스터디 운영 방식. 이번 단계에서는 "종류/정책 정보"이며 별도의 화상 세션을 만들지 않는다
 * (영상/음성은 기존 OpenVidu 룸을 그대로 사용). 표시 라벨은 클라이언트가 매핑한다.
 *  · GENERAL: 일반 스터디
 *  · CAM: 캠 스터디(캠 중심 운영 그룹임을 표시)
 */
public enum GroupStudyType {
    GENERAL,
    CAM
}
