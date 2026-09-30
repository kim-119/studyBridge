package com.studybridge.api.service;

import com.studybridge.api.entity.GroupStudyType;

import java.util.List;

/**
 * 그룹스터디 운영 정책 필드(스터디 타입·하루 목표시간·가입 질문·닉네임 규칙)의 서버 측 검증 단일 지점.
 * 생성/수정/가입 서비스가 모두 이 클래스를 거치므로 프론트 검증을 우회한 직접 호출도 같은 규칙으로 거절된다.
 * 위반은 IllegalArgumentException → GlobalExceptionHandler 가 400 으로 변환한다.
 *
 * <p>정규화 규칙: enabled=false 이면 question/rule 은 항상 null 로 저장한다(프로젝트 계약: "" 가 아니라 null).</p>
 */
public final class GroupStudySettingsPolicy {

    /** 하루 목표 공부시간 허용값(분). 4시간~10시간, 1시간 단위. 기존 그룹 default 는 최솟값 240. */
    public static final int TARGET_STUDY_MINUTES_DEFAULT = 240;
    public static final int TARGET_STUDY_MINUTES_MIN = 240;
    public static final int TARGET_STUDY_MINUTES_MAX = 600;
    public static final int TARGET_STUDY_MINUTES_STEP = 60;

    public static final int JOIN_QUESTION_MAX_LENGTH = 200;
    public static final int JOIN_ANSWER_MAX_LENGTH = 500;
    public static final int NICKNAME_RULE_MAX_LENGTH = 100;
    public static final int NICKNAME_MAX_LENGTH = 30;
    public static final int STUDY_ICON_ID_MAX_LENGTH = 50;

    /** 카드 지표(출석률/평균 공부시간) 집계 창(일). 오늘 포함 최근 N일. */
    public static final int ACTIVITY_WINDOW_DAYS = 7;

    private GroupStudySettingsPolicy() {
    }

    public static List<Integer> allowedTargetStudyMinutes() {
        java.util.ArrayList<Integer> values = new java.util.ArrayList<>();
        for (int m = TARGET_STUDY_MINUTES_MIN; m <= TARGET_STUDY_MINUTES_MAX; m += TARGET_STUDY_MINUTES_STEP) {
            values.add(m);
        }
        return values;
    }

    public static GroupStudyType requireStudyType(GroupStudyType studyType) {
        if (studyType == null) {
            throw new IllegalArgumentException("스터디 방식(studyType)은 GENERAL 또는 CAM 이어야 합니다.");
        }
        return studyType;
    }

    public static int requireTargetStudyMinutes(Integer minutes) {
        if (minutes == null
                || minutes < TARGET_STUDY_MINUTES_MIN
                || minutes > TARGET_STUDY_MINUTES_MAX
                || (minutes - TARGET_STUDY_MINUTES_MIN) % TARGET_STUDY_MINUTES_STEP != 0) {
            throw new IllegalArgumentException("하루 목표 공부시간은 4시간~10시간(1시간 단위)만 선택할 수 있습니다.");
        }
        return minutes;
    }

    /** enabled=true 면 비어 있지 않은 질문(최대 200자)을 요구하고, false 면 null 로 정규화한다. */
    public static String normalizeJoinQuestion(boolean enabled, String question) {
        return normalizeToggleText(enabled, question, JOIN_QUESTION_MAX_LENGTH,
                "가입 질문을 사용하려면 질문 내용을 입력해야 합니다.",
                "가입 질문은 " + JOIN_QUESTION_MAX_LENGTH + "자 이내로 입력해주세요.");
    }

    /** enabled=true 면 비어 있지 않은 규칙 안내(최대 100자)를 요구하고, false 면 null 로 정규화한다. */
    public static String normalizeNicknameRule(boolean enabled, String rule) {
        return normalizeToggleText(enabled, rule, NICKNAME_RULE_MAX_LENGTH,
                "그룹 닉네임 규칙을 사용하려면 규칙 안내 문구를 입력해야 합니다.",
                "그룹 닉네임 규칙은 " + NICKNAME_RULE_MAX_LENGTH + "자 이내로 입력해주세요.");
    }

    public static String normalizeStudyIconId(String iconId) {
        if (iconId == null || iconId.isBlank()) {
            return null;
        }
        String trimmed = iconId.trim();
        if (trimmed.length() > STUDY_ICON_ID_MAX_LENGTH || !trimmed.matches("[A-Za-z0-9_\\-]+")) {
            throw new IllegalArgumentException("스터디 아이콘 식별자 형식이 올바르지 않습니다.");
        }
        return trimmed;
    }

    /** 가입 시: 그룹이 질문을 켰다면 답변 필수(최대 500자). 껐다면 보낸 값이 있어도 null 로 버린다. */
    public static String requireJoinAnswer(boolean questionEnabled, String answer) {
        if (!questionEnabled) {
            return null;
        }
        if (answer == null || answer.isBlank()) {
            throw new IllegalArgumentException("이 그룹은 가입 질문에 대한 답변이 필요합니다.");
        }
        String trimmed = answer.trim();
        if (trimmed.length() > JOIN_ANSWER_MAX_LENGTH) {
            throw new IllegalArgumentException("가입 질문 답변은 " + JOIN_ANSWER_MAX_LENGTH + "자 이내로 입력해주세요.");
        }
        return trimmed;
    }

    /** 가입 시: 그룹이 닉네임 규칙을 켰다면 그룹 닉네임 필수(최대 30자). 껐다면 선택 입력(빈 값은 null). */
    public static String requireNickname(boolean ruleEnabled, String nickname) {
        String trimmed = nickname == null ? null : nickname.trim();
        if (trimmed == null || trimmed.isEmpty()) {
            if (ruleEnabled) {
                throw new IllegalArgumentException("이 그룹은 그룹 닉네임 입력이 필요합니다.");
            }
            return null;
        }
        if (trimmed.length() > NICKNAME_MAX_LENGTH) {
            throw new IllegalArgumentException("그룹 닉네임은 " + NICKNAME_MAX_LENGTH + "자 이내로 입력해주세요.");
        }
        return trimmed;
    }

    private static String normalizeToggleText(boolean enabled, String text, int maxLength,
                                              String emptyMessage, String tooLongMessage) {
        if (!enabled) {
            return null;
        }
        if (text == null || text.isBlank()) {
            throw new IllegalArgumentException(emptyMessage);
        }
        String trimmed = text.trim();
        if (trimmed.length() > maxLength) {
            throw new IllegalArgumentException(tooLongMessage);
        }
        return trimmed;
    }
}
