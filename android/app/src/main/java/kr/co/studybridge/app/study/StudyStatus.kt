package kr.co.studybridge.app.study

enum class StudyPhase(val storageKey: String) {
    UNKNOWN("UNKNOWN"),
    IDLE("IDLE"),
    STUDYING("STUDYING"),
    GROUP_STUDYING("GROUP_STUDYING");

    companion object {
        fun fromStorageKey(storageKey: String?): StudyPhase =
            entries.firstOrNull { it.storageKey == storageKey } ?: UNKNOWN
    }
}

enum class StudyIssue(val storageKey: String) {
    NONE("NONE"),
    LOGIN_REQUIRED("LOGIN_REQUIRED"),
    NETWORK("NETWORK"),
    SERVER("SERVER");

    companion object {
        fun fromStorageKey(storageKey: String?): StudyIssue =
            entries.firstOrNull { it.storageKey == storageKey } ?: NONE
    }
}

data class StudySnapshot(
    val phase: StudyPhase,
    val startedAtMillis: Long?,
    val todayCompletedSeconds: Long?,
    val todayDateKey: String?,
    val issue: StudyIssue,
    val updatedAtMillis: Long,
) {
    val isStudying: Boolean get() = phase == StudyPhase.STUDYING

    companion object {
        val EMPTY = StudySnapshot(
            phase = StudyPhase.UNKNOWN,
            startedAtMillis = null,
            todayCompletedSeconds = null,
            todayDateKey = null,
            issue = StudyIssue.NONE,
            updatedAtMillis = 0L,
        )

        fun signedOut(nowMillis: Long): StudySnapshot =
            EMPTY.copy(issue = StudyIssue.LOGIN_REQUIRED, updatedAtMillis = nowMillis)
    }
}

data class TimerSession(
    val id: Long?,
    val groupStudyId: Long?,
    val startedAtMillis: Long,
    val endedAtMillis: Long?,
    val durationSeconds: Long?,
) {
    val isActive: Boolean get() = endedAtMillis == null
    val isPersonal: Boolean get() = groupStudyId == null
}

enum class StudyAction(val storageKey: String) {
    START("START"),
    STOP("STOP"),
    REFRESH("REFRESH");

    companion object {
        fun fromStorageKey(storageKey: String?): StudyAction? =
            entries.firstOrNull { it.storageKey == storageKey }
    }
}

sealed class StudyActionResult {
    data class Started(val session: TimerSession) : StudyActionResult()
    data class AlreadyStudying(val session: TimerSession) : StudyActionResult()
    data class Stopped(val session: TimerSession?) : StudyActionResult()
    object NotStudying : StudyActionResult()
    data class GroupSessionActive(val session: TimerSession) : StudyActionResult()
    data class Refreshed(val snapshot: StudySnapshot) : StudyActionResult()
    object LoginRequired : StudyActionResult()
    object NetworkUnavailable : StudyActionResult()
    object ServerFailed : StudyActionResult()
    object Busy : StudyActionResult()
}
