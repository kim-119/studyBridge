package kr.co.studybridge.app.tile

import kr.co.studybridge.app.study.StudyAction
import kr.co.studybridge.app.study.StudyIssue
import kr.co.studybridge.app.study.StudyPhase
import kr.co.studybridge.app.study.StudySnapshot

enum class StudyTileMode {
    START,
    STUDYING,
    GROUP_STUDYING,
    LOGIN_REQUIRED,
    CONNECTION_ERROR,
    WORKING,
}

data class StudyTileDisplay(
    val mode: StudyTileMode,
    val label: String,
    val isActive: Boolean,
    val clickAction: StudyAction?,
)

object StudyTileDisplays {

    fun of(snapshot: StudySnapshot, hasUsableSession: Boolean, isWorking: Boolean): StudyTileDisplay {
        if (isWorking) return StudyTileDisplay(StudyTileMode.WORKING, "처리 중", isActive = false, clickAction = null)
        if (!hasUsableSession || snapshot.issue == StudyIssue.LOGIN_REQUIRED) {
            val action = if (snapshot.isStudying) StudyAction.STOP else StudyAction.START
            return StudyTileDisplay(StudyTileMode.LOGIN_REQUIRED, "로그인 필요", isActive = false, clickAction = action)
        }
        if (snapshot.issue == StudyIssue.NETWORK || snapshot.issue == StudyIssue.SERVER) {
            return StudyTileDisplay(StudyTileMode.CONNECTION_ERROR, "연결 오류", isActive = false, clickAction = StudyAction.REFRESH)
        }
        return when (snapshot.phase) {
            StudyPhase.STUDYING -> StudyTileDisplay(StudyTileMode.STUDYING, "공부 중", isActive = true, clickAction = StudyAction.STOP)
            StudyPhase.GROUP_STUDYING -> StudyTileDisplay(StudyTileMode.GROUP_STUDYING, "그룹 스터디 중", isActive = false, clickAction = StudyAction.REFRESH)
            StudyPhase.IDLE, StudyPhase.UNKNOWN -> StudyTileDisplay(StudyTileMode.START, "공부 시작", isActive = false, clickAction = StudyAction.START)
        }
    }

    fun subtitleOf(display: StudyTileDisplay): String = when (display.mode) {
        StudyTileMode.STUDYING -> "눌러서 공부 종료"
        StudyTileMode.START -> "StudyBridge"
        StudyTileMode.GROUP_STUDYING -> "스터디룸에서 종료"
        StudyTileMode.LOGIN_REQUIRED -> "눌러서 앱 열기"
        StudyTileMode.CONNECTION_ERROR -> "눌러서 다시 확인"
        StudyTileMode.WORKING -> "StudyBridge"
    }
}
