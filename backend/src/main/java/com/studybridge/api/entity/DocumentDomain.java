package com.studybridge.api.entity;

/**
 * 자료보관함 문서 도메인(탭 분리 기준)의 단일 출처.
 *  · 학습자료(LEARNING_MATERIAL) / 플래너(PLANNER) / 학습일지(STUDY_JOURNAL) 세 영역을 독립 네임스페이스로 분리한다.
 *  · 폴더(Folder.domain)와 자료(Material.materialType)를 같은 도메인 기준으로 필터링하기 위한 매핑/정규화를 제공한다.
 *  · enum 이 아닌 String 상수 — Folder.domain 을 String 으로 두어 RDS enum check 제약 부담을 피한다.
 */
public final class DocumentDomain {

    public static final String LEARNING_MATERIAL = "LEARNING_MATERIAL";
    public static final String PLANNER = "PLANNER";
    public static final String STUDY_JOURNAL = "STUDY_JOURNAL";
    public static final String MINDMAP = "MINDMAP";

    private DocumentDomain() {}

    /** 도메인 문자열 정규화. 알 수 없거나 비어 있으면 학습자료로 폴백(누락 방지). */
    public static String normalize(String raw) {
        if (raw == null) return LEARNING_MATERIAL;
        String s = raw.trim().toUpperCase();
        switch (s) {
            case PLANNER:
            case "PLAN":
            case "SCHEDULE":
                return PLANNER;
            case STUDY_JOURNAL:
            case "STUDY_LOG":
            case "LEARNING_LOG":
            case "JOURNAL":
            case "DIARY":
                return STUDY_JOURNAL;
            case MINDMAP:
            case "MIND_MAP":
            case "OBSIDIAN_GRAPH":
            case "GRAPH":
                return MINDMAP;
            case LEARNING_MATERIAL:
            case "LEARNING_PDF":
            case "PDF":
            case "MATERIAL":
            case "DOCUMENT":
            case "SYLLABUS":
                return LEARNING_MATERIAL;
            default:
                return LEARNING_MATERIAL;
        }
    }

    /** 자료(MaterialType) → 도메인 매핑. REVIEW_NOTE 는 별도 영역이라 null 반환(자료보관함 노출 제외). */
    public static String forMaterialType(MaterialType type) {
        if (type == null) return LEARNING_MATERIAL;
        switch (type) {
            case PLANNER:
                return PLANNER;
            case STUDY_LOG:
                return STUDY_JOURNAL;
            case MINDMAP:
                return MINDMAP;
            case REVIEW_NOTE:
                return null; // 오답노트는 자료보관함 어떤 도메인에도 노출하지 않음
            case PDF:
            case SYLLABUS:
            default:
                return LEARNING_MATERIAL;
        }
    }
}
